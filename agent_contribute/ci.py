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
    _, target, head, error = core.observation_target(task, evidence)
    result = {'repository': target, 'head_sha': head, 'complete': False, 'errors': [],
              'notice': 'Observation only. It never changes readiness, does not prove the evidence checks equal the '
                        'CI checks, and queued, pending, approval-required or missing runs are not success.'}
    if error:
        result['errors'].append(error)
        return result
    client = client or core.GitHub()
    runs, run_errors = check_runs(client, target, head)
    status, status_errors = combined_status(client, target, head)
    current = [run for run in runs if run['head_sha'] == head]
    result.update(check_runs=current, other_head_runs=len(runs) - len(current), check_runs_complete=not run_errors,
                  combined_status=status, errors=run_errors + status_errors)
    result['complete'] = not result['errors']
    return result
