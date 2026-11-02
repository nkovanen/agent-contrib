"""Opt-in, report-only ownership and resolution signals from the issue timeline and comments (#5, #6).

Nothing here changes approval, overlap or readiness gates; `blocking_if_adopted` only previews them.
"""
import datetime as dt
import re

from . import core, remote

MAX_PR_DETAILS = 50
STALE_DAYS = 30
SCAN_LIMIT = 65536
CLAIMS = [('working on it', re.compile(r"(?i)\bI(?:'m| am)\s+(?:currently\s+)?working on\b")),
          ('will take it', re.compile(r"(?i)\bI(?:'ll| will)\s+take\b")),
          ('asks to work on it', re.compile(r'(?i)\bcan I\s+(?:work on|take|pick up)\b')),
          ('/assign command', re.compile(r'(?im)^[ \t]{0,8}/assign\b')),
          ('asks for assignment', re.compile(r'(?i)\bassign\s+(?:this\s+|it\s+)?(?:to\s+)?me\b'))]


def _event_key(item):
    return item['id'] if type(item.get('id')) is int else core.canonical_hash(item)


def _days(value, now):
    try:
        return max(0, (now - dt.datetime.fromisoformat(value.replace('Z', '+00:00'))).days)
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None


def _login(value, what):
    return core.safe_text(remote.user(value, what)['login'], 100)


def _pull_detail(repository, repository_id, number, source, issue_number, client):
    pr = core.require(client.request(f'repos/{repository}/pulls/{number}'), dict, 'pull request')
    if remote.positive(pr.get('number'), 'pull request number') != number:
        remote.bad('pull request identity (different number returned)')
    base = core.require(pr.get('base'), dict, 'pull request base')
    name, base_id = remote.repository(base.get('repo'), 'pull request base repository')
    if name.casefold() != repository.casefold() or base_id != repository_id:
        remote.bad('pull request repository identity (differs from the timeline reference)')
    url = remote.pull_url(pr.get('html_url'), repository, number)
    state = remote.choice(pr.get('state'), {'open', 'closed'}, 'pull request state')
    merged = remote.flag(pr.get('merged'), 'pull request merged flag')
    merged_at = remote.text(pr.get('merged_at'), 'pull request merge time', nullable=True)
    closed_at = remote.text(pr.get('closed_at'), 'pull request close time', nullable=True)
    if merged and (state != 'closed' or merged_at is None) or state == 'closed' and closed_at is None:
        remote.bad('pull request state/merge combination')
    [entry] = core.index_prs([pr])
    exact = ((source.casefold(), issue_number) in entry['references'] or
             (repository.casefold() == source.casefold() and issue_number in entry['local']))
    return {'repository': name, 'repository_id': base_id, 'number': number, 'url': core.safe_text(url, 500),
            'state': state, 'draft': remote.flag(pr.get('draft'), 'pull request draft flag'), 'merged': merged,
            'merged_at': merged_at, 'closed_at': closed_at, 'exact_reference': exact}


def ownership_signals(source, number, client, now=None, *, max_pages=core.MAX_PAGES, max_pr_details=MAX_PR_DETAILS,
                      comments_out=None):
    """The caps bound reads for discover --check-top; reaching either one makes the report incomplete.
    comments_out, when given, receives the validated comments (body, association, age) for a stricter caller-side
    predicate; nothing about them is added to the report."""
    now = now or dt.datetime.now(dt.timezone.utc)
    errors = []
    timeline = core.paginate(client, f'repos/{source}/issues/{number}/timeline', key=_event_key, max_pages=max_pages)
    comments = core.paginate(client, f'repos/{source}/issues/{number}/comments', max_pages=max_pages)
    errors += timeline['errors'] + comments['errors']
    referenced, assignments, connections, commits = {}, [], [], []
    for event in timeline['items']:
        try:
            kind = remote.text(event.get('event'), 'timeline event kind')  # unknown kinds are ignored, not wrong types
            if kind == 'cross-referenced':
                origin = core.require(core.require(event.get('source'), dict, 'cross-reference source').get('issue'),
                                      dict, 'cross-referenced issue')
                if origin.get('pull_request') is None:
                    continue  # a plain issue mentioned this one
                core.require(origin.get('pull_request'), dict, 'cross-referenced pull request')
                name, repo_id = remote.repository(origin.get('repository'), 'cross-referenced repository')
                pr_number = remote.positive(origin.get('number'), 'cross-referenced PR number')
                known = referenced.setdefault((name.casefold(), pr_number), (name, repo_id, pr_number))
                if known[1] != repo_id:  # one name/number, two numeric repositories: identity is unresolved
                    errors.append(f'Conflicting repository IDs for cross-referenced PR {name}#{pr_number}')
            elif kind in ('assigned', 'unassigned'):
                assignments.append({'event': kind, 'assignee': _login(event.get('assignee'), 'assignee'),
                                    'actor': _login(event.get('actor'), 'actor'),
                                    'created_at': remote.text(event.get('created_at'), 'event time')})
            elif kind in ('connected', 'disconnected'):
                connections.append({'event': kind, 'actor': _login(event.get('actor'), 'actor'),
                                    'created_at': remote.text(event.get('created_at'), 'event time')})
            elif kind == 'referenced':
                commit = remote.sha(event.get('commit_id'), 'referencing commit', nullable=True)
                if commit:
                    commits.append({'commit_id': commit, 'url': core.safe_text(
                        remote.text(event.get('commit_url'), 'commit URL', nullable=True) or '', 500)})
        except core.ProtocolError as exc:
            errors.append('Malformed timeline event: ' + str(exc))
    pulls = []
    targets = sorted(referenced.values(), key=lambda item: (item[0].casefold(), item[2]))
    if len(targets) > max_pr_details:
        errors.append(f'More than {max_pr_details} cross-referenced PRs; details are incomplete')
    for name, repo_id, pr_number in targets[:max_pr_details]:
        try:
            pulls.append(_pull_detail(name, repo_id, pr_number, source, number, client))
        except (core.ProtocolError, ValueError) as exc:
            errors.append(f'Could not read cross-referenced PR {name}#{pr_number}: {exc}')
    claims = []
    for comment in comments['items']:
        try:
            body = remote.text(comment.get('body'), 'comment body', nullable=True) or ''
            author = _login(comment.get('user'), 'comment author')
            association = remote.choice(comment.get('author_association'), remote.ASSOCIATIONS, 'author association')
            created = remote.text(comment.get('created_at'), 'comment time')
        except core.ProtocolError as exc:
            errors.append('Malformed comment: ' + str(exc))
            continue
        if comments_out is not None:
            comments_out.append({'body': body, 'author': author, 'author_association': association,
                                 'age_days': _days(created, now)})
        for label, pattern in CLAIMS:
            match = pattern.search(body[:SCAN_LIMIT])
            if match:
                start = max(0, match.start() - 80)
                age = _days(created, now)
                claims.append({'pattern': label, 'author': author, 'author_association': association,
                               'age_days': age, 'stale': age is None or age > STALE_DAYS,
                               'untrusted_excerpt': core.safe_text(body[start:start + 280], 280)})
                break
    fixed = [pr for pr in pulls if pr['merged'] and pr['exact_reference']]
    rejected = [pr for pr in pulls if pr['state'] == 'closed' and not pr['merged'] and pr['exact_reference']]
    open_refs = [pr for pr in pulls if pr['state'] == 'open']
    preview = ['Open cross-referenced PR: ' + pr['url'] for pr in open_refs]
    preview += ['Possibly already fixed by merged PR: ' + pr['url'] for pr in fixed]
    if errors:
        preview.append('Timeline, comment or PR detail reads are incomplete')
    return {'complete': not errors, 'errors': errors,
            'reads': {'timeline': {k: v for k, v in timeline.items() if k != 'items'},
                      'comments': {k: v for k, v in comments.items() if k != 'items'},
                      'pull_details': len(pulls)},
            'cross_referenced_prs': pulls, 'assignment_history': assignments, 'connected_events': connections,
            'referencing_commits': commits, 'claims': claims,
            'resolution_signals': {'possibly_already_fixed': fixed, 'rejected_approaches': rejected,
                                   'status': 'complete' if not errors else 'unknown'},
            'blocking_if_adopted': preview,
            'notice': 'Report only. These signals never change approval, overlap or readiness gates, and comment '
                      'text cannot prove or remove ownership. An incomplete read is unknown, never "not fixed".'}


def ownership(reference, client=None):
    repository, number = core.parse_issue(reference)
    client = client or core.GitHub()
    context, _ = core.resolve_repository(repository, client)
    context['reference'] = f'{repository}#{number}'
    if context.get('complete') is False:
        return context
    signals = ownership_signals(context['issue_source_repository'], number, client)
    return {**context, 'complete': signals['complete'], 'ownership_signals': signals}
