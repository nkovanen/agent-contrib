"""Offline task-selection benchmark (#28): outcome labels, reconstruction at the cutoff, replay and metrics."""
import importlib.util
import pathlib
import unittest

from agent_contribute import core

PATH = pathlib.Path(__file__).resolve().parents[1] / 'tools' / 'benchmark' / 'benchlib.py'
SPEC = importlib.util.spec_from_file_location('benchlib', PATH)
bench = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bench)

T = '2026-05-01T00:00:00Z'
REPO = 'acme/photos'


def event(kind, when, **fields):
    return {'event': kind, 'created_at': when, **fields}


def pr_ref(number, merged_at, association='CONTRIBUTOR', user_type='User', repository=REPO):
    return event('cross-referenced', merged_at or '2026-05-02T00:00:00Z', source={'type': 'issue', 'issue': {
        'number': number, 'pull_request': {'merged_at': merged_at}, 'repository': {'full_name': repository},
        'user': {'login': 'someone', 'type': user_type}, 'author_association': association}})


def outcome(events, horizon=90):
    return bench.classify(events, T, horizon, REPO)


class OutcomeTests(unittest.TestCase):
    def test_external_merged_pr_closing_within_the_window_is_positive(self):
        result = outcome([pr_ref(7, '2026-05-10T10:00:00Z'), event('closed', '2026-05-10T10:00:05Z', state_reason='completed')])
        self.assertEqual(result['outcome'], 'positive')
        self.assertEqual(result['evidence']['pr'], 7)

    def test_maintainer_or_bot_pr_or_unlinked_close_is_excluded(self):
        for name, ref in (('member', pr_ref(7, '2026-05-10T10:00:00Z', association='MEMBER')),
                          ('owner', pr_ref(7, '2026-05-10T10:00:00Z', association='OWNER')),
                          ('collaborator', pr_ref(7, '2026-05-10T10:00:00Z', association='COLLABORATOR')),
                          ('bot', pr_ref(7, '2026-05-10T10:00:00Z', user_type='Bot')),
                          ('unmerged', pr_ref(7, None)),
                          ('other repository', pr_ref(7, '2026-05-10T10:00:00Z', repository='fork/photos')),
                          ('merge far from close', pr_ref(7, '2026-05-05T00:00:00Z'))):
            with self.subTest(case=name):
                result = outcome([ref, event('closed', '2026-05-10T10:00:05Z', state_reason='completed')])
                self.assertEqual(result['outcome'], 'excluded')
        self.assertEqual(outcome([event('closed', '2026-05-10T00:00:00Z', state_reason='completed')])['outcome'],
                         'excluded')

    def test_not_planned_duplicate_and_still_open_are_negative(self):
        self.assertEqual(outcome([event('closed', '2026-05-10T00:00:00Z', state_reason='not_planned')])['outcome'],
                         'negative')
        self.assertEqual(outcome([event('closed', '2026-05-10T00:00:00Z', state_reason='duplicate')])['outcome'],
                         'negative')
        self.assertEqual(outcome([])['outcome'], 'negative')

    def test_only_the_window_counts(self):
        late = [pr_ref(7, '2026-09-10T00:00:00Z'), event('closed', '2026-09-10T00:00:01Z', state_reason='completed')]
        self.assertEqual(outcome(late)['outcome'], 'negative')  # still open at the horizon
        reopened = [pr_ref(7, '2026-05-10T10:00:00Z'), event('closed', '2026-05-10T10:00:05Z', state_reason='completed'),
                    event('reopened', '2026-05-12T00:00:00Z')]
        self.assertEqual(outcome(reopened)['outcome'], 'negative')
        early_merge = [pr_ref(7, '2026-04-20T00:00:00Z'), event('closed', '2026-05-10T00:00:00Z', state_reason='completed')]
        self.assertEqual(outcome(early_merge)['outcome'], 'excluded')

    def test_issue_closed_at_the_cutoff_is_not_open_at_t(self):
        result = outcome([event('closed', '2026-04-20T00:00:00Z', state_reason='completed')])
        self.assertFalse(result['open_at_cutoff'])
        reopened = outcome([event('closed', '2026-04-20T00:00:00Z'), event('reopened', '2026-04-25T00:00:00Z')])
        self.assertTrue(reopened['open_at_cutoff'])


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
    return {'format': bench.FORMAT, 'repository': REPO, 'default_branch': 'main', 'cutoff': T,
            'horizon_days': 90, 'commit_at_cutoff': 'a' * 40, 'tree_paths': list(paths), 'tree_truncated': False,
            'open_prs_at_cutoff': [dict(pr, html_url=f'https://github.com/{REPO}/pull/{pr["number"]}') for pr in prs],
            'issues': [dict({'labels': [], 'comments': 0, 'author_association': 'NONE',
                             'created_at': '2026-01-01T00:00:00Z', 'updated_at': '2026-02-01T00:00:00Z',
                             'html_url': f'https://github.com/{REPO}/issues/{item["number"]}', 'outcome': 'negative'},
                            **item) for item in issues]}


class ReplayTests(unittest.TestCase):
    def test_replay_runs_real_discover_offline_with_cutoff_clock(self):
        snap = snapshot([{'number': 1, 'title': 'Crash in src/thumb.rs bounds'},
                         {'number': 2, 'title': 'Wontfix thing', 'labels': ['wontfix']},
                         {'number': 3, 'title': 'Thumbnail bounds overflow'},
                         {'number': 4, 'title': 'Maintainer note', 'author_association': 'OWNER'}],
                        prs=[{'number': 9, 'title': 'Thumbnail bounds fix'}])
        default = bench.replay(snap)
        self.assertEqual(default[-1], 2)  # exclusions sort last
        self.assertLess(default.index(1), default.index(3))  # issue 3 overlaps PR 9
        signals = bench.replay(snap, signals=True)
        self.assertEqual(signals[:2], [1, 4])  # code location and maintainer score points
        self.assertEqual(sorted(signals), [1, 2, 3, 4])

    def test_replay_makes_no_unexpected_reads(self):
        client = bench.SnapshotClient(snapshot([{'number': 1, 'title': 'x'}]))
        with self.assertRaises(core.ProtocolError):
            client.request('repos/acme/photos/issues/1/timeline')
        with self.assertRaises(core.ProtocolError):
            client.request('search/issues?q=x')

    def test_bodies_are_optional_and_merged_from_a_local_file(self):
        snap = snapshot([{'number': 1, 'title': 'A'}, {'number': 2, 'title': 'B'}])
        long_body = '- [ ] step one\n- [ ] step two\nExpected: x\nActual: y\n```\ncode\n```\n' * 3
        ranked = bench.replay(snap, signals=True, bodies={'2': long_body})
        self.assertEqual(ranked[0], 2)


class LabelTests(unittest.TestCase):
    def test_a_fix_whose_pr_was_already_open_at_the_cutoff_was_not_an_available_task(self):
        snap = snapshot([{'number': 1, 'title': 'A', 'outcome': 'positive', 'evidence': {'pr': 9}},
                         {'number': 2, 'title': 'B', 'outcome': 'positive', 'evidence': {'pr': 12}},
                         {'number': 3, 'title': 'C', 'outcome': 'negative'}],
                        prs=[{'number': 9, 'title': 'Unrelated title'}])
        self.assertEqual(bench.labels(snap), {1: 'excluded', 2: 'positive', 3: 'negative'})
        self.assertEqual(bench.labels(snap, claimed_at_cutoff=True), {1: 'positive', 2: 'positive', 3: 'negative'})


class VariantTests(unittest.TestCase):
    def test_recent_activity_tie_break_and_help_wanted_promotion(self):
        snap = snapshot([{'number': 1, 'title': 'Alpha', 'updated_at': '2026-01-01T00:00:00Z'},
                         {'number': 2, 'title': 'Beta', 'updated_at': '2026-04-01T00:00:00Z'},
                         {'number': 3, 'title': 'Gamma', 'updated_at': '2026-03-01T00:00:00Z',
                          'labels': ['help wanted']},
                         {'number': 4, 'title': 'Delta', 'labels': ['wontfix'], 'updated_at': '2026-04-30T00:00:00Z'}])
        self.assertEqual(bench.rank(snap, 'default'), [1, 2, 3, 4])
        self.assertEqual(bench.rank(snap, 'recent'), [2, 3, 1, 4])  # exclusions still last
        self.assertEqual(bench.rank(snap, 'help-wanted'), [3, 1, 2, 4])
        self.assertEqual(bench.rank(snap, 'signals'), bench.replay(snap, signals=True))
        with self.assertRaises(ValueError):
            bench.rank(snap, 'unknown')

    def test_help_wanted_labels_match_case_insensitively(self):
        snap = snapshot([{'number': 1, 'title': 'Alpha'}, {'number': 2, 'title': 'Beta', 'labels': ['Good First Issue']}])
        self.assertEqual(bench.rank(snap, 'help-wanted'), [2, 1])


class MetricTests(unittest.TestCase):
    def test_random_reference_has_a_seeded_interval(self):
        labels = {n: ('positive' if n % 4 == 0 else 'negative') for n in range(1, 41)}
        runs = [(list(range(1, 41)), labels)]
        first = bench.bootstrap_base_rate(runs, reps=300, seed=3)
        self.assertEqual(first, bench.bootstrap_base_rate(runs, reps=300, seed=3))
        self.assertLessEqual(first['low'], bench.base_rate(runs))
        self.assertGreaterEqual(first['high'], bench.base_rate(runs))

    def test_precision_and_recall_at_k_ignore_excluded_issues(self):
        labels = {1: 'positive', 2: 'excluded', 3: 'negative', 4: 'positive', 5: 'negative'}
        result = bench.at_k([2, 1, 3, 4, 5], labels, 2)
        self.assertEqual((result['precision'], result['recall'], result['decidable'], result['positives']),
                         (0.5, 0.5, 4, 2))
        self.assertIsNone(bench.at_k([3, 5], {3: 'negative', 5: 'negative'}, 2)['recall'])
        self.assertEqual(bench.at_k([1], {1: 'positive'}, 5)['precision'], 1.0)  # shorter list: hits / len

    def test_bootstrap_is_seeded_and_brackets_the_point_estimate(self):
        labels = {n: ('positive' if n % 3 == 0 else 'negative') for n in range(1, 40)}
        ranking = list(range(1, 40))
        first = bench.bootstrap([(ranking, labels)], 5, 'precision', reps=300, seed=7)
        second = bench.bootstrap([(ranking, labels)], 5, 'precision', reps=300, seed=7)
        self.assertEqual(first, second)
        point = bench.at_k(ranking, labels, 5)['precision']
        self.assertLessEqual(first['low'], point)
        self.assertGreaterEqual(first['high'], point)
        self.assertNotEqual(first, bench.bootstrap([(ranking, labels)], 5, 'precision', reps=300, seed=8))

    def test_pooled_metric_is_the_mean_over_repositories(self):
        a = ([1, 2], {1: 'positive', 2: 'negative'})
        b = ([3, 4], {3: 'negative', 4: 'negative'})
        c = ([5, 6], {5: 'positive', 6: 'positive'})
        self.assertEqual(bench.pooled([a, c], 1, 'precision'), 1.0)
        # A repository without positives cannot be scored by any ordering, so it is left out of the pool.
        self.assertEqual(bench.pooled([a, b], 1, 'precision'), 1.0)
        self.assertEqual(bench.base_rate([a, b]), 0.5)
        self.assertIsNone(bench.pooled([b], 1, 'precision'))


class ScoreTests(unittest.TestCase):
    def test_score_reports_variants_ci_and_random_rate_offline(self):
        import json
        import tempfile
        spec = importlib.util.spec_from_file_location('benchscore', PATH.parent / 'score.py')
        scorer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(scorer)
        snap = snapshot([{'number': 1, 'title': 'Crash in src/thumb.rs bounds', 'outcome': 'positive'},
                         {'number': 2, 'title': 'Old question?', 'outcome': 'negative'},
                         {'number': 3, 'title': 'Something', 'outcome': 'excluded'}])
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp, 'acme__photos__2026-05-01.json')
            path.write_text(json.dumps(snap), 'utf-8')
            report = scorer.score([str(path)], [1], reps=50)
        self.assertEqual(report['snapshots'][0]['positive'], 1)
        self.assertEqual(report['variants']['default']['@1']['precision'], 1.0)
        self.assertEqual(report['variants']['signals']['@1']['precision'], 1.0)
        self.assertEqual(report['random_precision'], 0.5)
        self.assertIn('| default | 1 | 1.00', scorer.table(report))


class ExperimentTests(unittest.TestCase):
    def test_a_variant_qualifies_only_above_the_random_interval(self):
        spec = importlib.util.spec_from_file_location('benchexperiment', PATH.parent / 'experiment.py')
        experiment = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(experiment)
        issues = [{'number': n, 'title': f'Issue {n}', 'outcome': 'positive' if n > 36 else 'negative',
                   'updated_at': f'2026-04-{n % 28 + 1:02d}T00:00:00Z' if n > 36 else '2026-01-01T00:00:00Z'}
                  for n in range(1, 41)]
        snap = snapshot(issues)
        rows = experiment.evaluate({'held-out': [snap]}, ['default', 'recent'], [4], reps=200)
        by_variant = {row['variant']: row for row in rows}
        self.assertFalse(by_variant['default']['beats_random'])  # oldest first: all negatives
        self.assertTrue(by_variant['recent']['beats_random'])
        self.assertEqual(by_variant['recent']['precision'], 1.0)
        self.assertIn('| held-out | recent | 4 | 1.00', experiment.table(rows))


class DataTests(unittest.TestCase):
    def test_committed_snapshots_are_small_bodyless_and_well_formed(self):
        files = sorted((PATH.parent / 'data').glob('*.json'))
        self.assertLessEqual(sum(path.stat().st_size for path in files), 2 * 1024 * 1024)
        for path in files:
            with self.subTest(snapshot=path.name):
                data = core.strict_json(path.read_text('utf-8'))
                self.assertEqual(data['format'], bench.FORMAT)
                self.assertFalse(any('body' in issue for issue in data['issues']))
                self.assertTrue(all(issue['outcome'] in ('positive', 'negative', 'excluded') for issue in data['issues']))
                self.assertTrue(all(issue['html_url'].startswith('https://github.com/' + data['repository'] + '/issues/')
                                    for issue in data['issues']))


if __name__ == '__main__':
    unittest.main()
