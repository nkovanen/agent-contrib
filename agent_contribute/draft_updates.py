"""Host-asserted draft-update rounds (#21). Slice 1 parses the record and checks its own bindings; slice 2 recognizes
the draft after its one fast-forward push. Pre-push readiness (round open, ready to push) is not evaluated yet, so
this version never reports implement_update or push_update and grants no new publication capability."""
from __future__ import annotations

from . import authorization, core

NOTE = ('Recognition after the one host push only: pre-push readiness is not evaluated, so this report never '
        'authorizes a push')


def report():
    return {'status': 'invalid', 'trust': 'host-asserted', 'sha256': None, 'from_head': None, 'candidate_head': None,
            'live_head': None, 'current': False, 'errors': [], 'note': NOTE}


def evaluate(task, context, authority, now):
    """Report a host-context 0.2 draft_update section. No GitHub reads; candidate_head stays null in this slice."""
    result = report()
    if core.schema_errors(context, core.host_context_schema(context)):
        return dict(result, errors=['Host context schema is invalid'])
    record = context['draft_update']
    errors = result['errors']
    result.update(sha256=core.canonical_hash(record), from_head=record['from_head'])
    if record['event']['binding_sha256'] != authorization.event_hash(record):
        errors.append('Draft update event binding hash differs')
    if record['contract_sha256'] != core.canonical_hash(task):
        errors.append('Draft update contract hash differs')
    if record['mandate_sha256'] != authority['mandate_sha256']:
        errors.append('Draft update mandate hash differs')
    if not authority['historical_valid']:
        errors.append('Draft update requires a valid mandate')
    actor = authority['credential_actor']
    if actor is None or actor['id'] != record['credential_actor_id']:
        errors.append('Draft update credential actor differs')
    if record['repository_id'] != task['source']['repository_id']:
        errors.append('Draft update names another repository')
    claim = context.get('publication')
    if claim is None:
        errors.append('Draft update requires a publication claim')
    else:
        if record['pr_number'] != claim['pr_number']:
            errors.append('Draft update names another pull request than the publication claim')
        if record['pr_id'] != claim['pr_id']:
            errors.append('Draft update names another pull request ID than the publication claim')
    for other, name in ((context['mandate'], 'mandate'), (context.get('final_signoff'), 'final sign-off'),
                        (context.get('overlap_dispositions'), 'overlap disposition')):
        if other and (record['id'] == other['id'] or record['nonce'] == other['nonce'] or
                      record['event']['reference'] == other['event']['reference']):
            errors.append(f'Draft update reuses the {name} event identity')
    try:
        issued, expires = authorization.interval(record, now)
        result['current'] = issued <= now < expires
    except (ValueError, OverflowError) as exc:
        errors.append(str(exc))
    result['errors'] = list(dict.fromkeys(errors))
    result['status'] = 'invalid' if result['errors'] else 'not_evaluated'
    return result


def technical_errors(task, record, evidence, repo_dir):
    """T(E) rules that apply only to an update (DU-04): the reviewed base exactly, no merge commit in from_head..E,
    and validations that started inside the round. check_evidence and the independent review are judged by the
    caller as for creation."""
    errors = []
    if evidence['base_commit'] != task['source']['commit']:
        errors.append('A draft update requires evidence based on the reviewed source commit exactly')
    try:
        issued = authorization.timestamp(record['issued_at'])
        if any(authorization.timestamp(item['started_at']) < issued for item in evidence['validations']):
            errors.append('Every validation must start after the draft update round was issued')
    except (ValueError, OverflowError):
        errors.append('Validation or draft update timestamps are invalid')
    try:
        if core.git_read(repo_dir, 'rev-list', '--merges', '--max-count=1',
                         record['from_head'] + '..' + evidence['git_head']):
            errors.append('A draft update round must not contain merge commits')
    except (core.ProtocolError, TypeError):
        errors.append('Draft update history from from_head could not be read')
    return errors


def finish(report, publication, live_head, evidence, now):
    """The final report: currency judged after every read; recognized only with a fully verified updated draft."""
    if report['status'] == 'invalid':
        return report
    report = dict(report, live_head=live_head, current=report['current'])
    if live_head is not None and live_head == report['from_head']:
        return dict(report, status='not_evaluated')
    if publication.get('verified') is True:
        return dict(report, status='recognized', candidate_head=evidence['git_head'])
    return dict(report, status='blocked',
                errors=list(dict.fromkeys(publication.get('errors', []) + publication.get('stage_errors', []))))
