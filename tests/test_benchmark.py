"""Offline task-selection benchmark (#28): evidence, labels, reconstruction, strict replay and metrics."""
import importlib.util
import json
import pathlib
import tempfile
import unittest

from agent_contribute import core

PATH = pathlib.Path(__file__).resolve().parents[1] / 'tools' / 'benchmark' / 'benchlib.py'
SPEC = importlib.util.spec_from_file_location('benchlib', PATH)
bench = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bench)

T = '2026-05-01T00:00:00Z'
REPO = 'acme/photos'


def load_tool(name):
    spec = importlib.util.spec_from_file_location('bench_' + name, PATH.parent / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def event(kind, when, **fields):
    return {'event': kind, 'created_at': when, **fields}


def pr_ref(number, merged_at, at='2026-05-02T00:00:00Z', association='CONTRIBUTOR', user_type='User',
           repository=REPO):
    return event('cross-referenced', at, source={'type': 'issue', 'issue': {
        'number': number, 'pull_request': {'merged_at': merged_at}, 'repository': {'full_name': repository},
        'user': {'login': 'someone', 'type': user_type}, 'author_association': association}})


def evidence_of(events, current=None):
    return bench.evidence(events, current or {})


def label(events, current=None, open_prs=(), horizon=90):
    return bench.classify(evidence_of(events, current), T, horizon, REPO, open_prs=set(open_prs))


CLOSE = event('closed', '2026-05-10T10:00:05Z', state_reason='completed')


class EvidenceAndLabelTests(unittest.TestCase):
    def test_external_merged_pr_closing_within_the_window_is_positive(self):
        result = label([pr_ref(7, '2026-05-10T10:00:00Z'), CLOSE])
        self.assertEqual((result['outcome'], result['evidence']['pr'], result['reason_known']), ('positive', 7, True))

    def test_maintainers_bots_and_unknown_authorship_are_never_positive(self):
        for name, ref in (('member', pr_ref(7, '2026-05-10T10:00:00Z', association='MEMBER')),
                          ('owner', pr_ref(7, '2026-05-10T10:00:00Z', association='OWNER')),
                          ('collaborator', pr_ref(7, '2026-05-10T10:00:00Z', association='COLLABORATOR')),
                          ('bot', pr_ref(7, '2026-05-10T10:00:00Z', user_type='Bot')),
                          ('unknown association', pr_ref(7, '2026-05-10T10:00:00Z', association=None)),
                          ('unknown user type', pr_ref(7, '2026-05-10T10:00:00Z', user_type=None)),
                          ('unmerged', pr_ref(7, None)),
                          ('other repository', pr_ref(7, '2026-05-10T10:00:00Z', repository='fork/photos')),
                          ('merge far from close', pr_ref(7, '2026-05-05T00:00:00Z'))):
            with self.subTest(case=name):
                self.assertEqual(label([ref, CLOSE])['outcome'], 'excluded')

    def test_references_made_after_the_horizon_do_not_count(self):
        late = pr_ref(7, '2026-05-10T10:00:00Z', at='2026-09-01T00:00:00Z')
        self.assertEqual(label([late, CLOSE])['outcome'], 'excluded')

    def test_a_missing_close_reason_is_unknown_not_completed(self):
        bare = event('closed', '2026-05-10T10:00:05Z')
        self.assertEqual(label([bare])['reason'], 'closed with an unknown reason and no qualifying PR')
        self.assertEqual(label([bare])['outcome'], 'excluded')
        # Registered labels (the 2026-11-03 amendment): an unknown close reason never makes a positive.
        unknown = label([pr_ref(7, '2026-05-10T10:00:00Z'), bare])
        self.assertEqual((unknown['outcome'], unknown['reason_known']), ('excluded', False))
        self.assertEqual(unknown['reason'], 'closed by a qualifying PR with an unknown close reason')
        weak = bench.classify(evidence_of([pr_ref(7, '2026-05-10T10:00:00Z'), bare]), T, 90, REPO,
                              unknown_reason_positive=True)
        self.assertEqual((weak['outcome'], weak['reason_known']), ('positive', False))
        # The issue's current reason describes the same close only if that close is the current one.
        current = {'state': 'closed', 'closed_at': '2026-05-10T10:00:05Z', 'state_reason': 'not_planned'}
        self.assertEqual(label([pr_ref(7, '2026-05-10T10:00:00Z'), bare], current)['outcome'], 'negative')
        stale = {'state': 'closed', 'closed_at': '2026-08-01T00:00:00Z', 'state_reason': 'not_planned'}
        self.assertEqual(label([bare], stale)['outcome'], 'excluded')

    def test_not_planned_duplicate_and_still_open_are_negative(self):
        for reason in ('not_planned', 'duplicate'):
            self.assertEqual(label([event('closed', '2026-05-10T00:00:00Z', state_reason=reason)])['outcome'], 'negative')
        self.assertEqual(label([])['outcome'], 'negative')
        reopened = [pr_ref(7, '2026-05-10T10:00:00Z'), CLOSE, event('reopened', '2026-05-12T00:00:00Z')]
        self.assertEqual(label(reopened)['outcome'], 'negative')
        late = [pr_ref(7, '2026-09-10T00:00:00Z', at='2026-09-10T00:00:00Z'),
                event('closed', '2026-09-10T00:00:01Z', state_reason='completed')]
        self.assertEqual(label(late)['outcome'], 'negative')

    def test_a_fix_already_in_flight_at_the_cutoff_was_not_an_available_task(self):
        linked_before = [pr_ref(7, '2026-05-10T10:00:00Z', at='2026-04-01T00:00:00Z'), CLOSE]
        self.assertEqual(label(linked_before)['reason'], 'fixed by a PR already linked or open at the cutoff')
        self.assertEqual(label(linked_before)['outcome'], 'excluded')
        self.assertEqual(label([pr_ref(7, '2026-05-10T10:00:00Z'), CLOSE], open_prs={7})['outcome'], 'excluded')

    def test_issue_closed_at_the_cutoff_is_not_open_at_t(self):
        self.assertFalse(label([event('closed', '2026-04-20T00:00:00Z', state_reason='completed')])['open_at_cutoff'])
        reopened = label([event('closed', '2026-04-20T00:00:00Z'), event('reopened', '2026-04-25T00:00:00Z')])
        self.assertTrue(reopened['open_at_cutoff'])

    def test_evidence_keeps_only_bounded_metadata(self):
        stored = evidence_of([pr_ref(7, '2026-05-10T10:00:00Z'), CLOSE, event('commented', '2026-05-03T00:00:00Z')])
        self.assertEqual(set(stored), {'closes', 'references', 'current'})
        self.assertEqual(stored['references'][0], {'at': '2026-05-02T00:00:00Z', 'pr': 7, 'repository': REPO,
                                                   'merged_at': '2026-05-10T10:00:00Z',
                                                   'author_association': 'CONTRIBUTOR', 'user_type': 'User'})
        self.assertNotIn('login', json.dumps(stored))


class LabelSchemeTests(unittest.TestCase):
    def test_registered_labels_are_primary_and_sensitivity_schemes_are_named(self):
        bare = event('closed', '2026-05-10T10:00:05Z')
        snap = {'repository': REPO, 'cutoff': T, 'horizon_days': 90, 'open_prs_at_cutoff': [{'number': 8}],
                'issues': [{'number': 1, 'evidence': evidence_of([pr_ref(7, '2026-05-10T10:00:00Z'), CLOSE])},
                           {'number': 2, 'evidence': evidence_of([pr_ref(7, '2026-05-10T10:00:00Z'), bare])},
                           {'number': 3, 'evidence': evidence_of([pr_ref(8, '2026-05-10T10:00:00Z'), CLOSE])}]}
        expected = {'registered': {1: 'positive', 2: 'excluded', 3: 'excluded'},
                    'weak-reason': {1: 'positive', 2: 'positive', 3: 'excluded'},
                    'raw': {1: 'positive', 2: 'positive', 3: 'positive'}}
        self.assertEqual(bench.labels(snap), expected['registered'])
        for scheme, outcomes in expected.items():
            with self.subTest(scheme=scheme):
                self.assertEqual(bench.labels(snap, scheme=scheme), outcomes)
        self.assertEqual(list(bench.LABEL_SCHEMES), ['registered', 'weak-reason', 'raw'])
        with self.assertRaises(bench.BenchmarkError):
            bench.labels(snap, scheme='lenient')


class PullRequestMembershipTests(unittest.TestCase):
    def test_pr_closed_at_the_cutoff_is_not_open_and_renames_are_reversed(self):
        events = [event('closed', '2026-04-01T00:00:00Z'), event('reopened', '2026-06-01T00:00:00Z'),
                  event('renamed', '2026-06-02T00:00:00Z', rename={'from': 'Old title', 'to': 'New title'})]
        self.assertEqual(bench.pr_at_cutoff({'title': 'New title'}, events, T), {'open': False, 'title': 'Old title'})
        self.assertEqual(bench.pr_at_cutoff({'title': 'Same'}, [], T), {'open': True, 'title': 'Same'})


class ReconstructionTests(unittest.TestCase):
    def test_labels_title_and_comments_are_rolled_back_to_the_cutoff(self):
        item = {'number': 3, 'title': 'Renamed later', 'labels': [{'name': 'bug'}, {'name': 'wontfix'}],
                'created_at': '2026-01-01T00:00:00Z', 'comments': 9, 'author_association': 'NONE',
                'html_url': 'https://github.com/acme/photos/issues/3'}
        events = [event('labeled', '2026-02-01T00:00:00Z', label={'name': 'bug'}),
                  event('labeled', '2026-03-01T00:00:00Z', label={'name': 'help wanted'}),
                  event('commented', '2026-03-02T00:00:00Z'),
                  event('unlabeled', '2026-06-01T00:00:00Z', label={'name': 'help wanted'}),
                  event('labeled', '2026-06-02T00:00:00Z', label={'name': 'wontfix'}),
                  event('renamed', '2026-06-03T00:00:00Z', rename={'from': 'Original title', 'to': 'Renamed later'}),
                  event('commented', '2026-06-04T00:00:00Z')]
        issue = bench.reconstruct(item, events, T)
        self.assertEqual(issue['title'], 'Original title')
        self.assertEqual(sorted(issue['labels']), ['bug', 'help wanted'])
        self.assertEqual(issue['comments'], 1)
        self.assertEqual(issue['updated_at'], '2026-03-02T00:00:00Z')
        self.assertNotIn('body', issue)


def snapshot(issues, prs=(), paths=('src/thumb.rs', 'README.md')):
    """outcome shortcuts become evidence: positive = external PR merged and closed in the window."""
    def evidence_for(outcome):
        if outcome == 'positive':
            return evidence_of([pr_ref(77, '2026-05-10T10:00:00Z'), CLOSE])
        if outcome == 'excluded':
            return evidence_of([CLOSE])
        return evidence_of([])
    return {'format': bench.FORMAT, 'repository': REPO, 'default_branch': 'main', 'cutoff': T,
            'horizon_days': 90, 'collected_at': '2026-11-01T00:00:00+00:00',
            'commit_at_cutoff': 'a' * 40, 'tree_paths': list(paths), 'tree_truncated': False,
            'open_prs_at_cutoff': [dict({'membership_verified': True}, **pr,
                                        html_url=f'https://github.com/{REPO}/pull/{pr["number"]}') for pr in prs],
            'issues': [dict({'labels': [], 'comments': 0, 'author_association': 'NONE',
                             'created_at': '2026-01-01T00:00:00Z', 'updated_at': '2026-02-01T00:00:00Z',
                             'html_url': f'https://github.com/{REPO}/issues/{item["number"]}',
                             'evidence': evidence_for(item.pop('outcome', 'negative'))}, **item)
                       for item in [dict(issue) for issue in issues]]}


class ValidationTests(unittest.TestCase):
    def test_snapshots_are_validated_before_scoring(self):
        good = snapshot([{'number': 1, 'title': 'A'}])
        bench.validate(good)
        for name, change in (('format', lambda s: s.update(format='agent-contrib-benchmark/1')),
                             ('duplicate issue', lambda s: s['issues'].append(dict(s['issues'][0]))),
                             ('immature window', lambda s: s.update(collected_at='2026-06-01T00:00:00+00:00')),
                             ('naive cutoff', lambda s: s.update(cutoff='2026-05-01T00:00:00')),
                             ('body', lambda s: s['issues'][0].update(body='text'))):
            with self.subTest(case=name):
                broken = json.loads(json.dumps(good))
                change(broken)
                with self.assertRaises(bench.BenchmarkError):
                    bench.validate(broken)


class ReplayTests(unittest.TestCase):
    def test_replay_runs_real_discover_offline_with_cutoff_clock(self):
        snap = snapshot([{'number': 1, 'title': 'Crash in src/thumb.rs bounds'},
                         {'number': 2, 'title': 'Wontfix thing', 'labels': ['wontfix']},
                         {'number': 3, 'title': 'Thumbnail bounds overflow'},
                         {'number': 4, 'title': 'Maintainer note', 'author_association': 'OWNER'}],
                        prs=[{'number': 9, 'title': 'Thumbnail bounds fix'}])
        default = bench.replay(snap)
        self.assertEqual(default[-1], 2)
        self.assertLess(default.index(1), default.index(3))
        signals = bench.replay(snap, signals=True)
        self.assertEqual(signals[:2], [1, 4])

    def test_incomplete_or_shrunken_replay_fails_loudly(self):
        snap = snapshot([{'number': 1, 'title': 'A'}, {'number': 2, 'title': 'B'}])
        client = bench.SnapshotClient(snap)
        with self.assertRaises(core.ProtocolError):
            client.request('repos/acme/photos/issues/1/timeline')
        broken = json.loads(json.dumps(snap))
        broken['tree_truncated'] = True  # discover reports an incomplete snapshot
        with self.assertRaises(bench.BenchmarkError):
            bench.replay(broken)
        original = bench.SnapshotClient.request

        def drop_issue_two(self, endpoint):
            value = original(self, endpoint)
            if endpoint.startswith('repos/acme/photos/issues?state=open'):
                value = [item for item in value if item['number'] != 2]
            return value
        bench.SnapshotClient.request = drop_issue_two
        try:
            with self.assertRaises(bench.BenchmarkError):
                bench.replay(snap)
        finally:
            bench.SnapshotClient.request = original

    def test_bodies_are_optional_and_merged_from_a_local_file(self):
        snap = snapshot([{'number': 1, 'title': 'A'}, {'number': 2, 'title': 'B'}])
        long_body = '- [ ] step one\n- [ ] step two\nExpected: x\nActual: y\n```\ncode\n```\n' * 3
        self.assertEqual(bench.replay(snap, signals=True, bodies={'2': long_body})[0], 2)


class VariantTests(unittest.TestCase):
    def test_recent_activity_tie_break_and_help_wanted_promotion(self):
        snap = snapshot([{'number': 1, 'title': 'Alpha', 'updated_at': '2026-01-01T00:00:00Z'},
                         {'number': 2, 'title': 'Beta', 'updated_at': '2026-04-01T00:00:00Z'},
                         {'number': 3, 'title': 'Gamma', 'updated_at': '2026-03-01T00:00:00Z',
                          'labels': ['help wanted']},
                         {'number': 4, 'title': 'Delta', 'labels': ['wontfix'], 'updated_at': '2026-04-30T00:00:00Z'}])
        self.assertEqual(bench.rank(snap, 'default'), [1, 2, 3, 4])
        self.assertEqual(bench.rank(snap, 'recent'), [2, 3, 1, 4])
        self.assertEqual(bench.rank(snap, 'help-wanted'), [3, 1, 2, 4])
        with self.assertRaises(ValueError):
            bench.rank(snap, 'unknown')


class MetricTests(unittest.TestCase):
    def test_top_k_counts_unjudged_slots_as_bounds_and_coverage(self):
        labels = {1: 'excluded', 2: 'positive', 3: 'negative', 4: 'positive', 5: 'negative'}
        result = bench.at_k([1, 2, 3, 4, 5], labels, 2)
        self.assertEqual((result['precision_lower'], result['precision_upper'], result['coverage']), (0.5, 1.0, 0.5))
        self.assertEqual(result['condensed_precision'], 0.5)  # first two judged: 2 and 3
        self.assertEqual(result['recall'], 0.5)
        self.assertEqual(result['positives'], 2)
        self.assertIsNone(bench.at_k([3], {3: 'negative'}, 1)['recall'])

    def test_recall_truth_comes_from_the_snapshot_not_the_ranking(self):
        with self.assertRaises(bench.BenchmarkError):
            bench.at_k([1], {1: 'negative', 2: 'positive'}, 1)

    def test_pooled_values_keep_a_fixed_population(self):
        a = ([1, 2], {1: 'positive', 2: 'negative'})
        b = ([3, 4], {3: 'negative', 4: 'negative'})
        self.assertEqual(bench.pooled([a, b], 1, 'precision_lower'), 0.5)  # all snapshots, zeros included
        self.assertEqual(bench.pooled([a, b], 1, 'condensed_precision'), 1.0)  # positive snapshots only
        self.assertEqual(bench.pooled([a, b], 1, 'recall'), 1.0)

    def test_bootstrap_keeps_support_fixed_and_is_seeded(self):
        labels = {n: ('positive' if n == 4 else 'negative') for n in range(1, 5)}
        runs = [([1, 2, 3, 4], labels)]
        first = bench.bootstrap(runs, 1, 'condensed_precision', reps=500, seed=7)
        self.assertEqual(first, bench.bootstrap(runs, 1, 'condensed_precision', reps=500, seed=7))
        self.assertEqual(first['reps'], 500)  # replicates that lose the positive count as 0, never dropped

    def test_permutation_null_is_seeded_and_uses_the_full_universe(self):
        labels = {n: ('positive' if n % 4 == 0 else 'excluded' if n % 7 == 0 else 'negative') for n in range(1, 41)}
        runs = [(list(range(1, 41)), labels)]
        null = bench.permutation_null(runs, 5, 'precision_lower', reps=400, seed=3)
        self.assertEqual(null, bench.permutation_null(runs, 5, 'precision_lower', reps=400, seed=3))
        self.assertLessEqual(null['low'], null['median'])
        self.assertLessEqual(null['median'], null['high'])
        self.assertEqual(null['reps'], 400)


class ToolTests(unittest.TestCase):
    def write(self, tmp, snap, name='acme__photos__2026-05-01.json'):
        path = pathlib.Path(tmp, name)
        path.write_text(json.dumps(snap), 'utf-8')
        return str(path)

    def test_score_reports_population_bounds_and_null(self):
        scorer = load_tool('score')
        snap = snapshot([{'number': 1, 'title': 'Crash in src/thumb.rs bounds', 'outcome': 'positive'},
                         {'number': 2, 'title': 'Old question?', 'outcome': 'negative'},
                         {'number': 3, 'title': 'Something', 'outcome': 'excluded'}])
        with tempfile.TemporaryDirectory() as tmp:
            report = scorer.score([self.write(tmp, snap)], [1], reps=50)
        self.assertEqual(report['snapshots'][0]['issues'], 3)
        self.assertEqual(report['snapshots'][0]['positive'], 1)
        default = report['variants']['default']['@1']
        self.assertEqual((default['precision_lower'], default['coverage']), (1.0, 1.0))
        self.assertIn('null', default)
        self.assertIn('| default | 1 |', scorer.table(report))
        self.assertEqual(report['labels'], 'registered')
        self.assertIn('Labels: registered (the pre-registered primary analysis)', scorer.table(report))
        # Issue 3 becomes an unknown-reason close by a qualifying PR: excluded only under registered labels.
        snap['issues'][2]['evidence'] = evidence_of([pr_ref(78, '2026-05-10T10:00:00Z'),
                                                     event('closed', '2026-05-10T10:00:05Z')])
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write(tmp, snap)
            registered, raw = (scorer.score([path], [1], reps=50, scheme=scheme) for scheme in ('registered', 'raw'))
        self.assertEqual((registered['snapshots'][0]['positive'], raw['snapshots'][0]['positive']), (1, 2))
        self.assertIn('Labels: raw (sensitivity analysis, not the registered result)', scorer.table(raw))

    def test_experiment_qualifies_only_above_the_permutation_null(self):
        experiment = load_tool('experiment')
        issues = [{'number': n, 'title': f'Issue {n}', 'outcome': 'positive' if n > 30 else 'negative',
                   'updated_at': f'2026-04-{n % 28 + 1:02d}T00:00:00Z' if n > 30 else '2026-01-01T00:00:00Z'}
                  for n in range(1, 41)]
        rows = experiment.evaluate({'held-out': [snapshot(issues)]}, ['default', 'recent'], [4], reps=200)
        by_variant = {row['variant']: row for row in rows}
        self.assertFalse(by_variant['default']['qualifies'])
        self.assertTrue(by_variant['recent']['qualifies'])
        self.assertEqual(by_variant['recent']['population'], {'snapshots': 1, 'issues': 40, 'judged': 40,
                                                              'positives': 10})
        self.assertIn('| held-out | recent | 4 |', experiment.table(rows))
        self.assertEqual({row['labels'] for row in rows}, {'registered'})
        self.assertIn('Labels: registered (the pre-registered primary analysis)', experiment.table(rows))
        unknown = snapshot(issues)
        unknown['issues'][0]['evidence'] = evidence_of([pr_ref(78, '2026-05-10T10:00:00Z'),
                                                        event('closed', '2026-05-10T10:00:05Z')])
        registered, weak = (experiment.evaluate({'held-out': [unknown]}, ['default'], [4], reps=20, scheme=scheme)
                            for scheme in ('registered', 'weak-reason'))
        self.assertEqual((registered[0]['population']['positives'], weak[0]['population']['positives']), (10, 11))
        self.assertIn('Labels: weak-reason (sensitivity analysis, not the registered result)', experiment.table(weak))


class CollectorTests(unittest.TestCase):
    def fake(self):
        cutoff_issue = {'number': 5, 'title': 'Thumbnail bounds crash', 'labels': [], 'state': 'open',
                        'created_at': '2026-01-01T00:00:00Z', 'comments': 0, 'author_association': 'NONE',
                        'html_url': f'https://github.com/{REPO}/issues/5', 'closed_at': None, 'state_reason': None}
        prs = {8: {'number': 8, 'title': 'Thumbnail bounds rewrite', 'created_at': '2026-01-02T00:00:00Z',
                   'pull_request': {}},
               9: {'number': 9, 'title': 'Thumbnail bounds cleanup', 'created_at': '2026-01-03T00:00:00Z',
                   'pull_request': {}},
               10: {'number': 10, 'title': 'Unrelated docs', 'created_at': '2026-01-04T00:00:00Z',
                    'pull_request': {}}}
        calls = []

        class Client:
            def request(self, endpoint):
                calls.append(endpoint)
                if endpoint == f'repos/{REPO}':
                    return {'full_name': REPO, 'default_branch': 'main', 'fork': False, 'has_issues': True}
                if endpoint.startswith(f'repos/{REPO}/commits?'):
                    return [{'sha': 'a' * 40}]
                if endpoint.startswith(f'repos/{REPO}/git/trees/'):
                    return {'truncated': False, 'tree': [{'path': 'src/thumb.rs', 'type': 'blob'}]}
                if endpoint.startswith('search/issues'):
                    is_pr = 'is%3Apr' in endpoint
                    items = list(prs.values()) if is_pr and 'is%3Aopen' in endpoint else (
                        [] if is_pr else [cutoff_issue] if 'is%3Aopen' in endpoint else [])
                    return {'incomplete_results': False, 'items': items}
                if endpoint.startswith(f'repos/{REPO}/issues/5/timeline'):
                    return [event('labeled', '2026-02-01T00:00:00Z', label={'name': 'bug'})]
                if endpoint.startswith(f'repos/{REPO}/issues/8/events'):
                    return [event('closed', '2026-04-01T00:00:00Z'), event('reopened', '2026-06-01T00:00:00Z')]
                if endpoint.startswith(f'repos/{REPO}/issues/9/events'):
                    return [event('renamed', '2026-06-02T00:00:00Z',
                                  rename={'from': 'Thumbnail bounds draft', 'to': 'Thumbnail bounds cleanup'})]
                raise AssertionError(endpoint)
        return Client(), calls

    def test_collect_verifies_overlapping_pr_membership_and_stores_evidence_only(self):
        collect = load_tool('collect')
        client, calls = self.fake()
        snap, bodies = collect.collect(REPO, T, 90, client, max_issues=10, max_search_pages=1)
        bench.validate(dict(snap, collected_at='2026-11-01T00:00:00+00:00'))
        prs = {pr['number']: pr for pr in snap['open_prs_at_cutoff']}
        self.assertNotIn(8, prs)  # closed at the cutoff, reopened later
        self.assertEqual(prs[9], dict(prs[9], title='Thumbnail bounds draft', membership_verified=True))
        self.assertFalse(prs[10]['membership_verified'])  # cannot create an overlap, so not read
        self.assertFalse([call for call in calls if '/issues/10/events' in call])
        issue = snap['issues'][0]
        self.assertEqual(set(issue['evidence']), {'closes', 'references', 'current'})
        self.assertNotIn('outcome', issue)
        self.assertEqual(bodies, {'5': ''})

    def test_collect_refuses_an_immature_window(self):
        collect = load_tool('collect')
        with self.assertRaises(SystemExit):
            collect.collect(REPO, '2999-01-01T00:00:00Z', 90, self.fake()[0], max_issues=1, max_search_pages=1)


class DataTests(unittest.TestCase):
    def test_committed_snapshots_are_small_bodyless_and_valid(self):
        files = sorted((PATH.parent / 'data').glob('*.json'))
        self.assertLessEqual(sum(path.stat().st_size for path in files), 2 * 1024 * 1024)
        for path in files:
            with self.subTest(snapshot=path.name):
                bench.validate(core.strict_json(path.read_text('utf-8')))


if __name__ == '__main__':
    unittest.main()
