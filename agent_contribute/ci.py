"""Opt-in, report-only GitHub CI observations for the evidence head (#17). Never affects readiness."""
from . import core, remote
from .feedback import check_runs

STATUS_STATES = {'success', 'failure', 'pending', 'error'}


def _status(item):
    return remote.positive(item.get('id'), 'status ID'), {
        'context': core.safe_text(remote.text(item.get('context'), 'status context'), 200),
        'state': remote.choice(item.get('state'), STATUS_STATES, 'status state'),
        'url': core.safe_text(remote.text(item.get('target_url'), 'status URL', nullable=True) or '', 500)}


def combined_status(client, repository, sha):
    states = []

    def check_page(data, errors):
        if remote.sha(data.get('sha'), 'combined status commit') != sha:
            remote.bad('combined status commit (different commit returned)')
        state = remote.choice(data.get('state'), STATUS_STATES, 'combined status state')
        if states and state != states[-1]:
            errors.append('Combined status changed during pagination')
        states.append(state)

    statuses, errors, finished = remote.counted_pages(
        client, f'repos/{repository}/commits/{sha}/status', 'statuses', _status, page='combined status',
        count='Combined status count', noun='status', oversize='Invalid GitHub status page size', check_page=check_page)
    return {'state': states[-1] if finished else None, 'statuses': statuses, 'complete': finished and not errors}, errors


def observe(task, evidence, client=None):
    target = task.get('execution', {}).get('target_repository') or task['source']['repository']
    result = {'repository': target, 'head_sha': None, 'complete': False, 'errors': [],
              'notice': 'Observation only. It never changes readiness, does not prove the evidence checks equal the '
                        'CI checks, and queued, pending, approval-required or missing runs are not success.'}
    head = evidence.get('git_head') if isinstance(evidence, dict) else None
    if not isinstance(head, str) or not remote.SHA.fullmatch(head):
        result['errors'].append('No valid evidence git_head to observe')
        return result
    result['head_sha'] = head
    client = client or core.GitHub()
    try:
        core.parse_repository(target)
    except core.ProtocolError as exc:
        result['errors'].append(str(exc))
        return result
    runs, run_errors = check_runs(client, target, head)
    status, status_errors = combined_status(client, target, head)
    current = [run for run in runs if run['head_sha'] == head]
    result.update(check_runs=current, other_head_runs=len(runs) - len(current), check_runs_complete=not run_errors,
                  combined_status=status, errors=run_errors + status_errors)
    result['complete'] = not result['errors']
    return result
