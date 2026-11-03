"""Offline task-selection benchmark (#28). Not part of the installed package.

A snapshot holds a repository's issues open at a cutoff T, rolled back to T where the timeline
allows, plus raw outcome evidence (close/reopen events and timestamped PR references). Labels are
derived from that evidence at scoring time. The scorer replays the real discover ranking through a
fake client that serves only snapshot data, with the clock fixed at T, and refuses any incomplete
replay or changed issue set."""
from __future__ import annotations

import base64
import datetime as dt
import random
from unittest.mock import patch

from agent_contribute import core

FORMAT = 'agent-contrib-benchmark/2'
EXTERNAL = {'CONTRIBUTOR', 'FIRST_TIME_CONTRIBUTOR', 'FIRST_TIMER', 'NONE'}  # explicit, never "not a maintainer"
MERGE_CLOSE_TOLERANCE = dt.timedelta(hours=24)
NEGATIVE_REASONS = {'not_planned', 'duplicate'}
# registered: the 2026-11-03 amended pre-registration, the primary analysis. The others are named
# sensitivity analyses: weak-reason lets a qualifying PR make a positive despite an unknown close
# reason (the definition scored first, in 5e77096), and raw also keeps fixes already in flight at T.
LABEL_SCHEMES = {'registered': {'claimed_excluded': True, 'unknown_reason_positive': False},
                 'weak-reason': {'claimed_excluded': True, 'unknown_reason_positive': True},
                 'raw': {'claimed_excluded': False, 'unknown_reason_positive': True}}


class BenchmarkError(Exception):
    """A snapshot or replay that cannot be scored honestly."""


def when(value):
    if not isinstance(value, str) or not (value.endswith('Z') or value[-6] in '+-'):
        raise BenchmarkError(f'Expected a timezone-aware timestamp, got {value!r}')
    return dt.datetime.fromisoformat(value.replace('Z', '+00:00'))


def _ordered(events):
    return sorted((item for item in events if isinstance(item, dict) and isinstance(item.get('created_at'), str)),
                  key=lambda item: when(item['created_at']))


def evidence(events, current):
    """The outcome evidence kept from an issue timeline: metadata only, no text or logins."""
    closes, references = [], []
    for item in _ordered(events):
        if item.get('event') in ('closed', 'reopened'):
            closes.append({'at': item['created_at'], 'kind': item['event'], 'reason': item.get('state_reason')})
        source = item.get('source') if item.get('event') == 'cross-referenced' else None
        issue = source.get('issue') if isinstance(source, dict) else None
        pull = issue.get('pull_request') if isinstance(issue, dict) else None
        if isinstance(pull, dict):
            user = issue.get('user') if isinstance(issue.get('user'), dict) else {}
            references.append({'at': item['created_at'], 'pr': issue.get('number'),
                               'repository': (issue.get('repository') or {}).get('full_name'),
                               'merged_at': pull.get('merged_at'), 'author_association': issue.get('author_association'),
                               'user_type': user.get('type')})
    return {'closes': closes, 'references': references,
            'current': {key: current.get(key) for key in ('state', 'closed_at', 'state_reason')}}


def classify(record, cutoff, horizon_days, repository, *, open_prs=frozenset(), claimed_excluded=True,
             unknown_reason_positive=False):
    """Outcome in (T, T + horizon] from stored evidence.

    positive: the issue is closed at the horizon by a same-repository PR that was merged inside the
      window within 24 hours of the close, referenced by the horizon, written by an explicitly
      external (CONTRIBUTOR, FIRST_TIME_CONTRIBUTOR, FIRST_TIMER or NONE) human user, and not
      already linked or open at the cutoff. The close reason must be completed (or, only with
      unknown_reason_positive, unknown).
    negative: still open at the horizon, or closed with an explicit not_planned/duplicate reason.
    excluded: everything else that closed: maintainer or bot fixes, unknown authorship, unlinked
      closes, unknown reasons, and fixes already in flight at the cutoff."""
    start = when(cutoff)
    end = start + dt.timedelta(days=horizon_days)
    state_at_cutoff, state, closing = 'open', 'open', None
    for item in record['closes']:
        moment = when(item['at'])
        new = 'closed' if item['kind'] == 'closed' else 'open'
        if moment <= start:
            state_at_cutoff = new
        elif moment <= end:
            state, closing = new, (item if new == 'closed' else None)
    result = {'open_at_cutoff': state_at_cutoff == 'open', 'evidence': {}, 'reason_known': True}
    if state == 'open':
        return dict(result, outcome='negative', reason='open at the horizon')
    reason = closing.get('reason')
    current = record.get('current') or {}
    if reason is None and current.get('state') == 'closed' and current.get('closed_at') == closing['at']:
        reason = current.get('state_reason')  # the current close is this close: its reason applies
    result.update(evidence={'closed_at': closing['at'], 'state_reason': reason}, reason_known=reason is not None)
    if reason in NEGATIVE_REASONS:
        return dict(result, outcome='negative', reason='closed as ' + reason)
    closed_at = when(closing['at'])
    for ref in record['references']:
        if not isinstance(ref.get('merged_at'), str) or not isinstance(ref.get('at'), str):
            continue
        merged = when(ref['merged_at'])
        if (ref.get('repository') == repository and when(ref['at']) <= end and start < merged <= end and
                abs(closed_at - merged) <= MERGE_CLOSE_TOLERANCE and ref.get('author_association') in EXTERNAL and
                ref.get('user_type') == 'User'):
            result['evidence'].update(pr=ref['pr'], merged_at=ref['merged_at'], referenced_at=ref['at'])
            if claimed_excluded and (when(ref['at']) <= start or ref['pr'] in open_prs):
                return dict(result, outcome='excluded', reason='fixed by a PR already linked or open at the cutoff')
            if reason is None and not unknown_reason_positive:
                return dict(result, outcome='excluded', reason='closed by a qualifying PR with an unknown close reason')
            return dict(result, outcome='positive', reason='closed by a new external merged PR')
    if reason is None:
        return dict(result, outcome='excluded', reason='closed with an unknown reason and no qualifying PR')
    return dict(result, outcome='excluded', reason='closed as completed without a qualifying external PR')


def pr_at_cutoff(item, events, cutoff):
    """Whether a PR was open at T, and its title then, from its issue events."""
    start = when(cutoff)
    open_now, title = True, item['title']
    for event in _ordered(events):
        moment = when(event['created_at'])
        if event['event'] in ('closed', 'reopened') and moment <= start:
            open_now = event['event'] == 'reopened'
    for event in reversed(_ordered(events)):
        if when(event['created_at']) <= start:
            break
        if event['event'] == 'renamed' and isinstance(event.get('rename'), dict):
            title = event['rename'].get('from', title)
    return {'open': open_now, 'title': title}


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


def scheme_title(scheme):
    if scheme == 'registered':
        return 'Labels: registered (the pre-registered primary analysis)'
    return f'Labels: {scheme} (sensitivity analysis, not the registered result)'


def validate(snapshot):
    """Refuse anything the scorer cannot score honestly."""
    if snapshot.get('format') != FORMAT:
        raise BenchmarkError(f'Unsupported snapshot format {snapshot.get("format")!r}')
    cutoff = when(snapshot['cutoff'])
    horizon = snapshot['horizon_days']
    if type(horizon) is not int or horizon <= 0:
        raise BenchmarkError('Horizon must be a positive number of days')
    if when(snapshot['collected_at']) < cutoff + dt.timedelta(days=horizon):
        raise BenchmarkError('Collected before the horizon ended: outcomes are not mature')
    numbers = [issue['number'] for issue in snapshot['issues']]
    if len(numbers) != len(set(numbers)):
        raise BenchmarkError('Duplicate issue numbers')
    for issue in snapshot['issues']:
        if 'body' in issue or set(issue['evidence']) != {'closes', 'references', 'current'}:
            raise BenchmarkError(f'Issue #{issue["number"]} has a body or malformed evidence')
    return snapshot


def labels(snapshot, *, scheme='registered'):
    """Scoring label per issue under one of LABEL_SCHEMES; registered is the primary analysis."""
    if scheme not in LABEL_SCHEMES:
        raise BenchmarkError(f'Unknown label scheme {scheme!r}')
    open_prs = {pr['number'] for pr in snapshot['open_prs_at_cutoff']}
    return {issue['number']: classify(issue['evidence'], snapshot['cutoff'], snapshot['horizon_days'],
                                      snapshot['repository'], open_prs=open_prs, **LABEL_SCHEMES[scheme])['outcome']
            for issue in snapshot['issues']}


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
            return {'sha': commit, 'truncated': snap['tree_truncated'], 'tree': [
                {'path': name, 'type': 'blob', 'sha': commit, 'mode': '100644'} for name in snap['tree_paths'] if name != '.agent-contrib.json']}
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


def discover_at_cutoff(snapshot, *, signals=False, bodies=None):
    """discover's issue results at T. An incomplete run or a changed issue set is an error, never a score."""
    cutoff = when(snapshot['cutoff'])

    class Clock(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return cutoff.astimezone(tz)

    with patch.object(core.dt, 'datetime', Clock):
        result = core.discover(snapshot['repository'], SnapshotClient(snapshot, bodies), signals=signals)
    if result.get('complete') is not True or result.get('errors'):
        raise BenchmarkError(f'Incomplete replay for {snapshot["repository"]}: {result.get("errors")}')
    returned = [issue['number'] for issue in result['issues']]
    if sorted(returned) != sorted(issue['number'] for issue in snapshot['issues']):
        raise BenchmarkError(f'Replay for {snapshot["repository"]} did not return exactly the snapshot issues')
    return result['issues']


def replay(snapshot, *, signals=False, bodies=None):
    """Issue numbers in the order discover ranks them at the cutoff."""
    return [issue['number'] for issue in discover_at_cutoff(snapshot, signals=signals, bodies=bodies)]


# Labels a project uses to say outside help is wanted (GitHub's defaults). A ranking prior, never approval.
HELP_WANTED = {'help wanted', 'good first issue'}


def rank(snapshot, variant, bodies=None):
    """Candidate orderings measured against the same snapshot. 'default' and 'signals' are discover
    itself; 'recent' and 'help-wanted' keep discover's exclusion, overlap and likelihood keys and change
    only what follows them (most recent activity at T first, or help-wanted labels first)."""
    if variant in ('default', 'signals'):
        return replay(snapshot, signals=variant == 'signals', bodies=bodies)
    if variant not in ('recent', 'help-wanted'):
        raise ValueError('Unknown ranking variant: ' + variant)
    facts = {issue['number']: issue for issue in snapshot['issues']}

    def key(issue):
        base = (bool(issue['exclusions']), bool(issue['duplicates']),
                issue['ranking']['success_likelihood']['value'] == 'low')
        fact = facts[issue['number']]
        if variant == 'recent':
            return base + (-when(fact['updated_at']).timestamp(), issue['number'])
        wanted = any(label.lower() in HELP_WANTED for label in fact['labels'])
        return base + (not wanted, issue['number'])
    return [issue['number'] for issue in sorted(discover_at_cutoff(snapshot, bodies=bodies), key=key)]


def at_k(ranking, labels, k):
    """Metrics over the first k actual recommendations. Unjudged (excluded) slots bound precision:
    lower counts them as misses, upper as hits; coverage is the judged share. condensed_precision is
    the older conditional metric over the first k judged issues and uses outcomes to pick the slots."""
    if len(ranking) != len(set(ranking)) or set(ranking) != set(labels):
        raise BenchmarkError('Ranking is not a permutation of the labelled issues')
    top = ranking[:k]
    hits = sum(labels[number] == 'positive' for number in top)
    unjudged = sum(labels[number] == 'excluded' for number in top)
    judged = [number for number in ranking if labels[number] != 'excluded']
    condensed = judged[:k]
    positives = sum(value == 'positive' for value in labels.values())
    return {'precision_lower': hits / len(top) if top else None,
            'precision_upper': (hits + unjudged) / len(top) if top else None,
            'coverage': (len(top) - unjudged) / len(top) if top else None,
            'condensed_precision': (sum(labels[n] == 'positive' for n in condensed) / len(condensed)
                                    if condensed else None),
            'recall': hits / positives if positives else None,
            'hits': hits, 'issues': len(ranking), 'judged': len(judged), 'positives': positives}


POSITIVE_ONLY = {'condensed_precision', 'recall'}


def support(runs):
    """Which snapshots a metric averages over, fixed from the original labels."""
    return [any(value == 'positive' for value in labels.values()) for _, labels in runs]


def pooled(runs, k, metric, fixed=None):
    """Macro mean over snapshots. Top-k bounds and coverage use every snapshot; condensed precision and
    recall use the snapshots with positives (fixed from the original data), counting 0 when a
    resample leaves a supported snapshot without a value."""
    fixed = support(runs) if fixed is None else fixed
    values = []
    for (ranking, labels), supported in zip(runs, fixed):
        if metric in POSITIVE_ONLY and not supported:
            continue
        value = at_k(ranking, labels, k)[metric]
        values.append(0.0 if value is None else value)
    return sum(values) / len(values) if values else None


def _interval(values):
    values = sorted(value for value in values if value is not None)
    if not values:
        return {'low': None, 'median': None, 'high': None, 'reps': 0}
    pick = lambda q: values[int(q * (len(values) - 1))]
    return {'low': pick(0.025), 'median': pick(0.5), 'high': pick(0.975), 'reps': len(values)}


def bootstrap(runs, k, metric, *, reps=2000, seed=0):
    """Conditional issue-population bootstrap: resample each snapshot's issues with replacement,
    keeping their rank positions and labels, with the snapshot support fixed. It measures sensitivity
    to which issues happened to be open, not label noise or repository-to-repository variation."""
    rng, fixed = random.Random(seed), support(runs)
    values = []
    for _ in range(reps):
        sample_runs = []
        for ranking, labels in runs:
            picks = sorted(rng.randrange(len(ranking)) for _ in ranking) if ranking else []
            keys = [(ranking[position], index) for index, position in enumerate(picks)]
            sample_runs.append((keys, {key: labels[key[0]] for key in keys}))
        values.append(pooled(sample_runs, k, metric, fixed))
    return _interval(values)


def permutation_null(runs, k, metric, *, reps=2000, seed=0):
    """The same pooled metric for uniformly random orderings of each snapshot's full issue set."""
    rng, fixed = random.Random(seed), support(runs)
    values = []
    for _ in range(reps):
        shuffled = []
        for ranking, labels in runs:
            order = list(ranking)
            rng.shuffle(order)
            shuffled.append((order, labels))
        values.append(pooled(shuffled, k, metric, fixed))
    return _interval(values)
