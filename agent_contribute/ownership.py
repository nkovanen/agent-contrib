"""Opt-in, report-only ownership and resolution signals from the issue timeline and comments (#5, #6).

Nothing here changes approval, overlap or readiness gates; `blocking_if_adopted` only previews them.
"""
import datetime as dt
import re

from . import core

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


def _login(value):
    return core.safe_text(value['login'], 100) if isinstance(value, dict) and isinstance(value.get('login'), str) else None


def _pull_detail(repository, number, source, issue_number, client):
    pr = core.require(client.request(f'repos/{repository}/pulls/{number}'), dict, 'pull request')
    base = core.require(pr.get('base'), dict, 'pull request base')
    repo = core.require(base.get('repo'), dict, 'pull request base repository')
    repo_id = core.require(repo.get('id'), int, 'pull request repository ID')
    state = core.require(pr.get('state'), str, 'pull request state')
    merged = core.require(pr.get('merged'), bool, 'pull request merged flag')
    [entry] = core.index_prs([pr])
    exact = ((source.casefold(), issue_number) in entry['references'] or
             (repository.casefold() == source.casefold() and issue_number in entry['local']))
    return {'repository': repository, 'repository_id': repo_id, 'number': number, 'url': entry['url'],
            'state': state, 'draft': pr.get('draft') is True, 'merged': merged,
            'merged_at': pr.get('merged_at') if isinstance(pr.get('merged_at'), str) else None,
            'closed_at': pr.get('closed_at') if isinstance(pr.get('closed_at'), str) else None,
            'exact_reference': exact}


def ownership_signals(source, number, client, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    errors = []
    timeline = core.paginate(client, f'repos/{source}/issues/{number}/timeline', key=_event_key)
    comments = core.paginate(client, f'repos/{source}/issues/{number}/comments')
    errors += timeline['errors'] + comments['errors']
    referenced, assignments, connections, commits = {}, [], [], []
    for event in timeline['items']:
        kind = event.get('event')
        try:
            if kind == 'cross-referenced':
                origin = core.require(core.require(event.get('source'), dict, 'cross-reference source').get('issue'),
                                      dict, 'cross-referenced issue')
                if 'pull_request' not in origin:
                    continue
                repo = core.require(origin.get('repository'), dict, 'cross-referenced repository')
                name = core.parse_repository(core.require(repo.get('full_name'), str, 'cross-referenced repository name'))
                pr_number = core.require(origin.get('number'), int, 'cross-referenced PR number')
                referenced[(name.casefold(), pr_number)] = (name, pr_number)
            elif kind in ('assigned', 'unassigned'):
                assignments.append({'event': kind, 'assignee': _login(event.get('assignee')),
                                    'actor': _login(event.get('actor')),
                                    'created_at': core.safe_text(str(event.get('created_at', '')), 40)})
            elif kind in ('connected', 'disconnected'):
                connections.append({'event': kind, 'actor': _login(event.get('actor')),
                                    'created_at': core.safe_text(str(event.get('created_at', '')), 40)})
            elif kind == 'referenced' and isinstance(event.get('commit_id'), str):
                commits.append({'commit_id': core.safe_text(event['commit_id'], 40),
                                'url': core.safe_text(str(event.get('commit_url') or ''), 500)})
        except core.ProtocolError as exc:
            errors.append('Malformed timeline event: ' + str(exc))
    pulls = []
    targets = sorted(referenced.values(), key=lambda item: (item[0].casefold(), item[1]))
    if len(targets) > MAX_PR_DETAILS:
        errors.append(f'More than {MAX_PR_DETAILS} cross-referenced PRs; details are incomplete')
    for name, pr_number in targets[:MAX_PR_DETAILS]:
        try:
            pulls.append(_pull_detail(name, pr_number, source, number, client))
        except (core.ProtocolError, ValueError) as exc:
            errors.append(f'Could not read cross-referenced PR {name}#{pr_number}: {exc}')
    claims = []
    for comment in comments['items']:
        body = comment.get('body') if isinstance(comment.get('body'), str) else ''
        for label, pattern in CLAIMS:
            match = pattern.search(body[:SCAN_LIMIT])
            if match:
                start = max(0, match.start() - 80)
                age = _days(comment.get('created_at'), now)
                association = comment.get('author_association')
                claims.append({'pattern': label, 'author': _login(comment.get('user')),
                               'author_association': association if isinstance(association, str) else 'UNKNOWN',
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
