"""Opt-in completion gate on GitHub-observed CI for the exact head (#17). Any ambiguity fails closed.

For each reviewed {check, app_id}, the requirement is met only when every check run whose raw name is exactly
check, from that app, on the head is completed with success; every check suite of that app on the head is
completed; at least one such run exists; and both reads are complete, consistent and below GitHub's suite window.
There is no latest-attempt selection. Design: docs/design/2026-11-03-ci-gating.md.
"""
from . import core, remote

MAX_REQUIREMENTS = 20
SUITE_WINDOW = 1000  # the commit check-runs endpoint only covers a ref's newest 1,000 suites
READ_BUDGET = 50  # logical GET requests for both reads together
STATUSES = frozenset({'queued', 'in_progress', 'completed', 'waiting', 'requested', 'pending'})
CONCLUSIONS = frozenset({'success', 'failure', 'neutral', 'cancelled', 'skipped', 'timed_out', 'action_required',
                         'stale', 'startup_failure'})
FAILED = frozenset({'failure', 'timed_out', 'cancelled', 'stale', 'startup_failure'})
NOT_MET = frozenset({'neutral', 'skipped'})
GITHUB_EDIT = 'CI requirements cannot be met by a change that edits .github/'
NOTICE = ('Observation of the check runs GitHub currently retains for the exact head. It does not prove which tree a '
          'job checked out, does not reconcile CI with the evidence, and never replaces review or sign-off.')


def requirements(task):
    return task.get('ci_requirements') or []


def _positive(value, what):
    if type(value) is not int or value <= 0:
        remote.bad(what)
    return value


def _choice(value, allowed, what, nullable=False):
    if value is None and nullable:
        return None
    if not isinstance(value, str) or value not in allowed:  # type first: an unhashable value is malformed
        remote.bad(what)
    return value


def _app_id(item, what):
    app = item.get('app')
    if not isinstance(app, dict):
        remote.bad(what + ' app')
    return _positive(app.get('id'), what + ' app ID')


def parse_suite(item, head):
    """Raw fields only; nothing is sanitised, because these values decide identity and state."""
    suite_id = _positive(item.get('id'), 'check suite ID')
    if item.get('head_sha') != head:
        remote.bad('check suite head (not the exact head)')
    return suite_id, {'id': suite_id, 'app_id': _app_id(item, 'check suite'),
                      'status': _choice(item.get('status'), STATUSES, 'check suite status')}


def parse_run(item, head):
    run_id = _positive(item.get('id'), 'check run ID')
    name = item.get('name')
    if not isinstance(name, str):
        remote.bad('check run name')
    if item.get('head_sha') != head:
        remote.bad('check run head (not the exact head)')
    status = _choice(item.get('status'), STATUSES, 'check run status')
    conclusion = _choice(item.get('conclusion'), CONCLUSIONS, 'check run conclusion', nullable=True)
    if (status == 'completed') != (conclusion is not None):
        remote.bad('check run status/conclusion combination')
    suite = item.get('check_suite')
    if not isinstance(suite, dict):
        remote.bad('check run suite')
    url = item.get('html_url')
    return run_id, {'id': run_id, 'name': name, 'app_id': _app_id(item, 'check run'), 'status': status,
                    'conclusion': conclusion, 'suite_id': _positive(suite.get('id'), 'check run suite ID'),
                    'url': url if isinstance(url, str) else ''}


class _Budget:
    """Caps the logical GET requests of one gate evaluation; exhaustion is an unknown result, never a pass."""
    def __init__(self, client, limit):
        self.client, self.limit, self.used = client, limit, 0

    def request(self, endpoint):
        if self.used >= self.limit:
            raise core.ProtocolError('ci_budget', 'CI read budget exhausted; not observed')
        self.used += 1
        return self.client.request(endpoint)


def _window(data, errors):
    count = data.get('total_count')
    if type(count) is int and count >= SUITE_WINDOW:
        raise core.ProtocolError('ci_window', f'{count} check suites on the head reach the {SUITE_WINDOW}-suite '
                                              'window; coverage cannot be proven')


def observe(client, target, head):
    """Suites first (coverage and pending state), then every run. Returns (suites, runs, errors, complete)."""
    budget = _Budget(client, READ_BUDGET)
    suites, errors, finished = remote.counted_pages(
        budget, f'repos/{target}/commits/{head}/check-suites', 'check_suites', lambda item: parse_suite(item, head),
        page='check suites page', count='Check suite count', noun='check suite',
        oversize='Check suites page exceeds 100 items', malformed='Malformed check suite: ', check_page=_window)
    if errors or not finished:
        return suites, [], errors or ['Check suite read is incomplete'], False
    runs, run_errors, finished = remote.counted_pages(
        budget, f'repos/{target}/commits/{head}/check-runs?filter=all', 'check_runs', lambda item: parse_run(item, head),
        page='check runs page', count='Check run count', noun='check run',
        oversize='Check runs page exceeds 100 items', malformed='Malformed check run: ')
    errors = list(run_errors)
    known = {suite['id'] for suite in suites}
    orphans = sorted(run['id'] for run in runs if run['suite_id'] not in known)
    if orphans:
        errors.append(f'{len(orphans)} check run(s) name a suite missing from the suite read; reads are inconsistent')
    return suites, runs, errors, finished and not errors


def decide(items, suites, runs, complete):
    """One state per requirement, the first applicable row of the design table winning."""
    out = []
    for item in items:
        check, app_id = item['check'], item['app_id']
        matching = sorted((run for run in runs if run['name'] == check and run['app_id'] == app_id),
                          key=lambda run: run['id'])
        blocking = sorted(suite['id'] for suite in suites if suite['app_id'] == app_id and suite['status'] != 'completed')
        if not complete:
            state = 'unknown'
        elif any(run['conclusion'] in FAILED for run in matching):
            state = 'failed'
        elif any(run['conclusion'] in NOT_MET for run in matching):
            state = 'not_met'
        elif any(run['status'] != 'completed' or run['conclusion'] == 'action_required' for run in matching):
            state = 'pending'
        elif blocking:
            state = 'pending'
        elif not matching:
            state = 'missing'
        elif all(run['conclusion'] == 'success' for run in matching):
            state = 'met'
        else:
            state = 'unknown'
        out.append({'check': core.safe_text(check, 200), 'app_id': app_id, 'state': state,
                    'runs': [{'id': run['id'], 'status': run['status'], 'conclusion': run['conclusion'],
                              'url': core.safe_text(run['url'], 500)} for run in matching],
                    'blocking_suites': blocking,
                    'other_app_runs': sum(run['name'] == check and run['app_id'] != app_id for run in runs)})
    return out


def _edits_github(directory, base, head):
    """True/False from the validated commit diff (renames as both sides); None when it cannot be read."""
    try:
        paths = core.implementation_paths(directory, base, head)
    except core.ProtocolError:
        return None
    return any(path.split('/', 1)[0].casefold() == '.github' for path in paths)


def evaluate(task, evidence, repo_dir, publication, client):
    """The ci_gate report and its completion blockers. Nothing is read until the exact-head draft is verified."""
    items = requirements(task)
    result = {'head_sha': None, 'complete': False, 'suites_read': 0, 'github_paths_changed': None,
              'requirements': [], 'errors': [], 'notice': NOTICE}
    if not publication.get('verified'):
        result['errors'].append('Not evaluated until an exact-head published draft is verified')
        result['requirements'] = decide(items, [], [], False)
    else:
        head = evidence['git_head']
        result['head_sha'] = head
        result['github_paths_changed'] = _edits_github(repo_dir, evidence['base_commit'], head)
        if result['github_paths_changed'] is None:
            result['errors'].append('Could not read the implementation diff for the .github/ rule')
        try:
            suites, runs, errors, complete = observe(client, task['execution']['target_repository'], head)
        except core.ProtocolError as exc:
            suites, runs, errors, complete = [], [], [str(exc)], False
        result.update(suites_read=len(suites), complete=complete and result['github_paths_changed'] is not None)
        result['errors'] += errors
        result['requirements'] = decide(items, suites, runs, complete)
    blockers = [f'CI requirement {item["check"]} (app {item["app_id"]}) is {item["state"]}'
                for item in result['requirements'] if item['state'] != 'met']
    if result['github_paths_changed'] is not False:
        blockers.append(GITHUB_EDIT if result['github_paths_changed'] else
                        'CI requirements: the .github/ rule could not be evaluated')
    return result, blockers
