"""Opt-in, report-only GitHub CI observations for the evidence head (#17). Never affects readiness."""
from . import core, remote
from .feedback import check_runs

STATUS_STATES = {'success', 'failure', 'pending', 'error'}


def combined_status(client, repository, sha):
    statuses, errors, seen, state, total = [], [], set(), None, None
    for page in range(1, core.MAX_PAGES + 1):
        try:
            data = core.require(client.request(f'repos/{repository}/commits/{sha}/status?per_page=100&page={page}'),
                                dict, 'combined status')
            if remote.sha(data.get('sha'), 'combined status commit') != sha:
                remote.bad('combined status commit (different commit returned)')
            page_state = remote.choice(data.get('state'), STATUS_STATES, 'combined status state')
            if state is not None and page_state != state:
                errors.append('Combined status changed during pagination')
            state = page_state
            count = data.get('total_count')
            if type(count) is not int or count < 0:
                remote.bad('combined status count')
            if total is not None and count != total:
                errors.append('Combined status count changed during pagination')
            total = count
            batch = core.require(data.get('statuses'), list, 'statuses')
            if len(batch) > 100:
                remote.bad('status page size')
            for item in batch:
                item = core.require(item, dict, 'status')
                status_id = remote.positive(item.get('id'), 'status ID')
                if status_id in seen:
                    errors.append('Pagination repeated a status; results may have moved')
                    continue
                seen.add(status_id)
                statuses.append({'context': core.safe_text(remote.text(item.get('context'), 'status context'), 200),
                                 'state': remote.choice(item.get('state'), STATUS_STATES, 'status state'),
                                 'url': core.safe_text(remote.text(item.get('target_url'), 'status URL', nullable=True) or '', 500)})
            if len(batch) < 100:
                if len(seen) != total:
                    errors.append('Combined status count does not match total_count')
                return {'state': state, 'statuses': statuses, 'complete': not errors}, errors
        except core.ProtocolError as exc:
            return {'state': None, 'statuses': statuses, 'complete': False}, errors + [str(exc)]
    return {'state': None, 'statuses': statuses, 'complete': False}, errors + ['Pagination reached the 40-page limit']


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
