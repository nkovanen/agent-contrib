"""Host-asserted draft-update rounds (#21), slice 1: the record is parsed and its own bindings are checked, but this
version never evaluates an update, so nothing is authorized and no gate, read or exit status changes."""
from __future__ import annotations

from . import authorization, core

NOTE = 'Parsed only: this version does not evaluate draft updates, so nothing is authorized'


def report():
    return {'status': 'invalid', 'trust': 'host-asserted', 'sha256': None, 'from_head': None, 'candidate_head': None,
            'current': False, 'errors': [], 'note': NOTE}


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
