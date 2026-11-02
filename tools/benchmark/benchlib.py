"""Offline task-selection benchmark (#28). Not part of the installed package.

Snapshots describe a repository's open issues as of a cutoff T, with an outcome label observed
in (T, T + horizon]. The scorer replays the real discover ranking against a snapshot through a
fake client that serves only snapshot data, with the clock fixed at T, and measures how many
later-positive issues land in the top k."""
from __future__ import annotations

import base64
import datetime as dt
import random
from unittest.mock import patch

from agent_contribute import core

FORMAT = 'agent-contrib-benchmark/1'
MAINTAINERS = {'OWNER', 'MEMBER', 'COLLABORATOR'}
MERGE_CLOSE_TOLERANCE = dt.timedelta(hours=24)


def when(value):
    return dt.datetime.fromisoformat(value.replace('Z', '+00:00'))


def _ordered(events):
    return sorted((item for item in events if isinstance(item, dict) and isinstance(item.get('created_at'), str)),
                  key=lambda item: when(item['created_at']))


def classify(events, cutoff, horizon_days, repository):
    """Outcome of an issue after the cutoff, from its timeline events.

    positive: closed (completed) inside the window, by a merged PR from the same repository whose
      author is not OWNER/MEMBER/COLLABORATOR and not a bot, merged inside the window and within 24
      hours of the close. This is the work an outside contributor demonstrably landed.
    negative: still open at the horizon, or closed as not planned or duplicate.
    excluded: closed as completed without such a PR (a maintainer fix, a direct commit or an
      unlinked close). It is ambiguous whether an outside contributor could have landed it, so it
      counts as neither."""
    start = when(cutoff)
    end = start + dt.timedelta(days=horizon_days)
    events = _ordered(events)
    state_at_cutoff, state, closing = 'open', 'open', None
    for item in events:
        moment = when(item['created_at'])
        if item['event'] not in ('closed', 'reopened'):
            continue
        new = 'closed' if item['event'] == 'closed' else 'open'
        if moment <= start:
            state_at_cutoff = new
        elif moment <= end:
            state, closing = new, (item if new == 'closed' else None)
    result = {'open_at_cutoff': state_at_cutoff == 'open', 'evidence': {}}
    if state == 'open':
        return dict(result, outcome='negative', reason='open at the horizon')
    reason = closing.get('state_reason') or 'completed'
    result['evidence'] = {'closed_at': closing['created_at'], 'state_reason': reason}
    if reason != 'completed':
        return dict(result, outcome='negative', reason='closed as ' + reason)
    closed_at = when(closing['created_at'])
    for item in events:
        source = item.get('source') if item['event'] == 'cross-referenced' else None
        issue = source.get('issue') if isinstance(source, dict) else None
        pull = issue.get('pull_request') if isinstance(issue, dict) else None
        if not isinstance(pull, dict) or not isinstance(pull.get('merged_at'), str):
            continue
        merged = when(pull['merged_at'])
        repo = (issue.get('repository') or {}).get('full_name')
        user = issue.get('user') or {}
        if (repo == repository and start < merged <= end and abs(closed_at - merged) <= MERGE_CLOSE_TOLERANCE and
                issue.get('author_association') not in MAINTAINERS and user.get('type') != 'Bot'):
            result['evidence'].update(pr=issue.get('number'), merged_at=pull['merged_at'],
                                      pr_author_association=issue.get('author_association'))
            return dict(result, outcome='positive', reason='closed by an external merged PR')
    return dict(result, outcome='excluded', reason='closed as completed without an external merged PR')


def reconstruct(item, events, cutoff):
    """Title, labels, comment count and last activity as of the cutoff, from current values and the
    timeline. Bodies are never stored: their edit history is not available through REST."""
    start = when(cutoff)
    events = _ordered(events)
    title = item['title']
    labels = {label['name'] for label in item.get('labels', []) if isinstance(label, dict) and 'name' in label}
    for event in reversed(events):
        if when(event['created_at']) <= start:
            break
        kind = event['event']
        if kind == 'renamed' and isinstance(event.get('rename'), dict):
            title = event['rename'].get('from', title)
        elif kind in ('labeled', 'unlabeled') and isinstance(event.get('label'), dict):
            name = event['label'].get('name')
            (labels.discard if kind == 'labeled' else labels.add)(name)
    before = [event for event in events if when(event['created_at']) <= start]
    updated = max([item['created_at']] + [event['created_at'] for event in before], key=when)
    return {'number': item['number'], 'title': title, 'labels': sorted(labels),
            'created_at': item['created_at'], 'updated_at': updated,
            'comments': sum(event['event'] == 'commented' for event in before),
            'author_association': item.get('author_association'), 'html_url': item['html_url']}


class SnapshotClient:
    """Serves exactly the GETs discover makes, from a snapshot. Anything else is refused: no network."""

    def __init__(self, snapshot, bodies=None):
        self.snapshot, self.bodies, self.calls = snapshot, bodies or {}, []

    def _page(self, items, query):
        page = int(dict(part.split('=', 1) for part in query.split('&') if '=' in part).get('page', 1))
        return items[(page - 1) * 100:page * 100]

    def request(self, endpoint):
        self.calls.append(endpoint)
        snap = self.snapshot
        repo, branch, commit = snap['repository'], snap['default_branch'], snap['commit_at_cutoff']
        path, _, query = endpoint.partition('?')
        if path == f'repos/{repo}':
            return {'full_name': repo, 'default_branch': branch, 'fork': False, 'has_issues': True}
        if path == f'repos/{repo}/commits/{branch}':
            return {'sha': commit}
        if path == f'repos/{repo}/labels':
            return []
        if path == f'repos/{repo}/pulls' and query.startswith('state=open'):
            return self._page([{'number': pr['number'], 'title': pr['title'], 'html_url': pr['html_url'],
                                'body': None, 'head': None} for pr in snap['open_prs_at_cutoff']], query)
        if path == f'repos/{repo}/git/trees/{commit}':
            # The policy file is left out: approval never affects the ranking order.
            return {'truncated': snap['tree_truncated'], 'tree': [
                {'path': name, 'type': 'blob'} for name in snap['tree_paths'] if name != '.agent-contrib.json']}
        if path.startswith(f'repos/{repo}/contents/'):
            return {'encoding': 'base64', 'content': base64.b64encode(b'').decode()}
        if path == f'repos/{repo}/issues' and query.startswith('state=open'):
            return self._page([{'number': issue['number'], 'title': issue['title'],
                                'body': self.bodies.get(str(issue['number']), ''), 'state': 'open',
                                'html_url': issue['html_url'], 'created_at': issue['created_at'],
                                'updated_at': issue['updated_at'], 'comments': issue['comments'],
                                'author_association': issue['author_association'], 'assignees': [],
                                'labels': [{'name': name} for name in issue['labels']]}
                               for issue in snap['issues']], query)
        raise core.ProtocolError('api_error', 'Benchmark replay has no data for ' + endpoint)


def replay(snapshot, *, signals=False, bodies=None):
    """Issue numbers in the order discover ranks them at the cutoff."""
    cutoff = when(snapshot['cutoff'])

    class Clock(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return cutoff.astimezone(tz)

    client = SnapshotClient(snapshot, bodies)
    with patch.object(core.dt, 'datetime', Clock):
        result = core.discover(snapshot['repository'], client, signals=signals)
    return [issue['number'] for issue in result['issues']]


def at_k(ranking, labels, k):
    decided = [number for number in ranking if labels.get(number) in ('positive', 'negative')]
    positives = sum(labels[number] == 'positive' for number in decided)
    top = decided[:k]
    hits = sum(labels[number] == 'positive' for number in top)
    return {'precision': hits / len(top) if top else None, 'recall': hits / positives if positives else None,
            'hits': hits, 'decidable': len(decided), 'positives': positives}


def pooled(runs, k, metric):
    """Mean over repositories of the per-repository metric. Repositories without positives are left
    out: no ordering can score there, so they would only add a constant zero."""
    results = [at_k(ranking, labels, k) for ranking, labels in runs]
    values = [result[metric] for result in results if result['positives'] and result[metric] is not None]
    return sum(values) / len(values) if values else None


def base_rate(runs):
    """Mean per-repository share of positives among decidable issues: the expected precision of a random order."""
    rates = []
    for ranking, labels in runs:
        result = at_k(ranking, labels, len(ranking))
        if result['positives']:
            rates.append(result['positives'] / result['decidable'])
    return sum(rates) / len(rates) if rates else None


def bootstrap(runs, k, metric, *, reps=2000, seed=0):
    """Percentile 95% interval of the pooled metric, resampling decidable issues within each repository
    (with replacement) while keeping each issue's original rank position."""
    rng = random.Random(seed)
    prepared = []
    for ranking, labels in runs:
        decided = [(position, number) for position, number in enumerate(ranking)
                   if labels.get(number) in ('positive', 'negative')]
        prepared.append((decided, labels))
    values = []
    for _ in range(reps):
        sample_runs = []
        for decided, labels in prepared:
            sample = sorted(rng.choice(decided) for _ in decided) if decided else []
            # Duplicated issues need distinct identities so each copy keeps its label.
            ranking = [(number, index) for index, (_, number) in enumerate(sample)]
            sample_runs.append(([key for key in ranking], {key: labels[key[0]] for key in ranking}))
        value = pooled(sample_runs, k, metric)
        if value is not None:
            values.append(value)
    if not values:
        return {'low': None, 'high': None, 'reps': 0}
    values.sort()
    return {'low': values[int(0.025 * (len(values) - 1))], 'high': values[int(0.975 * (len(values) - 1))],
            'reps': len(values)}
