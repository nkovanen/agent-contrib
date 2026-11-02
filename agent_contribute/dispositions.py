"""Host-asserted overlap dispositions (#7). A disposition removes one topical overlap with one open PR from
the blocking lists while every bound observation still holds; it never waives anything else."""
from __future__ import annotations

import re
from urllib.parse import quote

from . import authorization, core

DIRECT = 'Explicit reference to this issue'
TOPICAL = 'Potential title/checklist overlap; review manually'


def report():
    return {'status': 'absent', 'trust': 'host-asserted', 'sha256': None, 'errors': [], 'waived': [], 'unused': []}


def content_hash(pr):
    return core.canonical_hash({'title': pr['title'], 'body': pr['body'] or '', 'head_ref': pr['head']['ref'],
                                'base_ref': pr['base']['ref']})


def section_errors(task, context, record, authority, now):
    """The record's own bindings (design step 1); no GitHub reads."""
    errors = []
    if record['event']['binding_sha256'] != authorization.event_hash(record):
        errors.append('Overlap disposition event binding hash differs')
    if record['contract_sha256'] != core.canonical_hash(task):
        errors.append('Overlap disposition contract hash differs')
    if record['mandate_sha256'] != authority['mandate_sha256']:
        errors.append('Overlap disposition mandate hash differs')
    if not authority['historical_valid']:
        errors.append('Overlap disposition requires a valid mandate')
    actor = authority['credential_actor']
    if actor is None or actor['id'] != record['credential_actor_id']:
        errors.append('Overlap disposition credential actor differs')
    for other, name in ((context['mandate'], 'mandate'), (context.get('final_signoff'), 'final sign-off')):
        if other and (record['id'] == other['id'] or record['nonce'] == other['nonce'] or
                      record['event']['reference'] == other['event']['reference']):
            errors.append(f'Overlap disposition reuses the {name} event identity')
    seen = set()
    for entry in record['dispositions']:
        number, key = entry['pr_number'], (entry['repository_id'], entry['pr_number'])
        if key in seen:
            errors.append(f'Overlap disposition repeats a PR: #{number}')
        seen.add(key)
        if entry['repository_id'] != task['source']['repository_id']:
            errors.append(f'Overlap disposition names another repository: #{number}')
        if entry['author_id'] == record['credential_actor_id']:
            errors.append(f'Overlap disposition names a PR by the credential actor: #{number}')
        if entry['comparison']['head_sha'] != entry['head_sha']:
            errors.append(f'Overlap disposition comparison head differs from bound head: #{number}')
    errors.extend(expiry_errors(record, now))
    return list(dict.fromkeys(errors))


def expiry_errors(record, now):
    try:
        _, expires = authorization.interval(record, now)
    except (ValueError, OverflowError) as exc:
        return [str(exc)]
    return ['Overlap disposition record expired'] if now >= expires else []


def _positive(value):
    return type(value) is int and value > 0


def _pull(source, number, client):
    pr = core.require(client.request(f'repos/{source}/pulls/{number}'), dict, 'pull request')
    user, head, base = pr.get('user'), pr.get('head'), pr.get('base')
    if not (_positive(pr.get('id')) and pr.get('number') == number and isinstance(pr.get('title'), str) and
            isinstance(pr.get('html_url'), str) and pr.get('state') in ('open', 'closed') and
            type(pr.get('draft')) is bool and 'body' in pr and (pr['body'] is None or isinstance(pr['body'], str)) and
            isinstance(user, dict) and _positive(user.get('id')) and isinstance(head, dict) and isinstance(base, dict) and
            isinstance(head.get('ref'), str) and isinstance(head.get('sha'), str) and
            re.fullmatch('[0-9a-f]{40}', head['sha']) and isinstance(base.get('ref'), str) and
            isinstance(base.get('repo'), dict) and _positive(base['repo'].get('id')) and
            (head.get('repo') is None or (isinstance(head['repo'], dict) and _positive(head['repo'].get('id'))))):
        raise core.ProtocolError('api_shape', 'Malformed pull request detail')
    authorization.timestamp(pr.get('updated_at'))
    return pr


def _tip(source, ref, client):
    if not authorization.valid_ref(ref):
        raise core.ProtocolError('api_shape', 'Invalid base ref')
    value = core.require(client.request(f'repos/{source}/git/ref/heads/{quote(ref, safe="/")}'), dict, 'base ref')
    target = value.get('object')
    if (value.get('ref') != 'refs/heads/' + ref or not isinstance(target, dict) or target.get('type') != 'commit' or
            not isinstance(target.get('sha'), str) or not re.fullmatch('[0-9a-f]{40}', target['sha'])):
        raise core.ProtocolError('api_shape', 'Malformed base ref')
    return target['sha']


def evaluate(task, context, authority, current, client, now):
    """Return (report, waived PR numbers, extra blocking entries). Only topical, fully re-observed overlaps waive."""
    result = report()
    record = context.get('overlap_dispositions')
    if record is None:
        return result, set(), []
    source = task['source']
    repository = source['repository']
    result['sha256'] = core.canonical_hash(record)
    errors = result['errors']
    errors.extend(section_errors(task, context, record, authority, now))
    if errors:
        result['status'] = 'invalid'
        return result, set(), []
    result['status'] = 'evaluated'
    if not current or 'source' not in current or not current['complete'] or current.get('duplicate_scan') != 'complete':
        errors.append('Overlap disposition needs a complete open-PR scan')
        return result, set(), []
    issue = {'number': source['issue'], 'title': current['untrusted_issue']['title'],
             'body': current['untrusted_issue']['body']}
    live = [dict(item, repository=repository) for item in current['duplicates']]
    prepared = [item for item in task['discovery']['duplicate_prs'] if item.get('repository') == repository]
    actor = authority['credential_actor']['id']
    canonical = 'https://github.com/{}/pull/{}'
    waived, extra, tips = set(), [], {}

    def block(number, reason, message):
        errors.append(message)
        extra.append({'number': number, 'url': canonical.format(repository, number), 'reason': reason,
                      'repository': repository})

    for entry in record['dispositions']:
        number = entry['pr_number']
        listed = [item for item in live if item['number'] == number]
        saved = [item for item in prepared if item['number'] == number]
        try:
            pr = _pull(repository, number, client)
            findings = core.duplicate_prs(repository, issue, core.index_prs([pr]))
        except (core.ProtocolError, ValueError):
            block(number, 'Overlap disposition read failed', f'Overlap disposition read failed for PR #{number}')
            continue
        finding = findings[0] if findings else None
        if finding and finding['reason'] == DIRECT:
            block(number, DIRECT + ' (observed in disposition read)',
                  f'Overlap disposition read found an explicit reference: PR #{number}')
            continue
        if finding is None and not listed:
            if saved:
                errors.append(f'Overlap disposition cannot clear prepared PR #{number} that no longer matches')
            else:
                result['unused'].append(number)
            continue
        if finding is None or not listed:
            block(number, 'Overlap scan and disposition read disagree',
                  f'Overlap scan and disposition read disagree for PR #{number}')
            continue
        reasons = {item['reason'] for item in listed + saved}
        checks = [
            ('reason', reasons == {finding['reason']} == {entry['match_reason']} and
             finding['reason'].startswith(TOPICAL)),
            ('pr_id', pr['id'] == entry['pr_id']),
            ('repository', pr['base']['repo']['id'] == entry['repository_id'] == source['repository_id']),
            ('url', pr['html_url'] == canonical.format(repository, number)),
            ('author', pr['user']['id'] == entry['author_id'] and pr['user']['id'] != actor),
            ('state', pr['state'] == entry['pr_state'] == 'open'),
            ('draft', pr['draft'] is entry['draft']),
            ('head repository', pr['head']['repo'] is not None and pr['head']['repo']['id'] == entry['head_repository_id']),
            ('head', pr['head']['sha'] == entry['head_sha'] == entry['comparison']['head_sha']),
            ('updated_at', pr['updated_at'] == entry['updated_at']),
            ('content', content_hash(pr) == entry['content_sha256']),
        ]
        stale = [name for name, ok in checks if not ok]
        ref = pr['base']['ref']
        try:
            if ref not in tips:
                tips[ref] = _tip(repository, ref, client)
            if tips[ref] != entry['comparison']['base_tip_sha']:
                stale.append('base tip')
        except (core.ProtocolError, ValueError):
            errors.append(f'Overlap disposition base tip read failed for PR #{number}')
            continue
        if stale:
            errors.extend(f'Overlap disposition stale for PR #{number}: {name}' for name in stale)
            continue
        waived.add(number)
        result['waived'].append({'repository': repository, 'number': number, 'url': pr['html_url'],
                                 'reason': finding['reason'], 'pr_id': pr['id'], 'head_sha': pr['head']['sha'],
                                 'base_tip_sha': tips[ref], 'updated_at': pr['updated_at'],
                                 'untrusted_rationale': core.safe_text(entry['rationale'], 2000)})
    return result, waived, extra
