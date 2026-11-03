"""Offline ranking evaluation on a frozen dogfood-2 snapshot; no network. See the fixture's description."""
import datetime as dt
import json
import pathlib
import unittest

from agent_contribute import signals

FIXTURE = json.loads((pathlib.Path(__file__).parent / 'fixtures' / 'ranking' / 'dogfood2.json').read_text('utf-8'))
NOW = dt.datetime(2026, 11, 2, tzinfo=dt.timezone.utc)
PATHS = ['src/fixture.rs']
BODIES = {'high': 'See src/fixture.rs\n- [ ] works\n## Expected\nok', 'medium': 'See src/fixture.rs\n- [ ] works',
          'low': 'See src/fixture.rs'}
# Evaluator's precision@5 before the change (evaluation.md) and the result after it on the same snapshot.
PRECISION_AT_5 = {'pallets/click': (1, 1), 'BurntSushi/ripgrep': (1, 1), 'honojs/hono': (0, 0)}


def synthetic(item):
    body = BODIES[item['clarity']] if item['location'] else BODIES[item['clarity']].replace('See src/fixture.rs', '')
    return {'number': item['number'], 'title': item['title'], 'body': body, 'labels': [{'name': n} for n in item['labels']],
            'author_association': 'MEMBER' if item['maintainer'] else 'NONE', 'comments': 0,
            'created_at': NOW.isoformat(), 'updated_at': NOW.isoformat()}


def ranked(issues, score):
    return [item for _, item in sorted(((score(item), item) for item in issues),
                                       key=lambda pair: (-pair[0], pair[1]['number']))]


def precision(order):
    return sum(item['counts_for_precision'] for item in order[:5])


class RankingEvaluationTests(unittest.TestCase):
    def test_fixture_reproduces_the_evaluated_before_ranking(self):
        for repository, data in FIXTURE['repositories'].items():
            with self.subTest(repository=repository):
                for item in data['issues']:
                    base = item['location'] + {'high': 2, 'medium': 1, 'low': 0}[item['clarity']] + item['maintainer']
                    self.assertEqual(base, item['before_score'], item['number'])
                before = ranked(data['issues'], lambda item: item['before_score'])
                self.assertEqual([item['number'] for item in before[:8]], data['evaluated_top8_before'])

    def test_precision_at_5_before_and_after_the_demotion_rules(self):
        for repository, data in FIXTURE['repositories'].items():
            with self.subTest(repository=repository):
                before = ranked(data['issues'], lambda item: item['before_score'])
                after = ranked(data['issues'], lambda item: signals.issue_signals(synthetic(item), PATHS, NOW)['score'])
                self.assertEqual((precision(before), precision(after)), PRECISION_AT_5[repository])
                self.assertGreaterEqual(precision(after), precision(before))
                demoted = [item['number'] for item in after
                           if signals.issue_signals(synthetic(item), PATHS, NOW)['demotion']['value'] == 'demoted']
                self.assertFalse(set(demoted) & {item['number'] for item in after[:5]}, demoted)

    def test_known_bad_labelled_and_meta_issues_leave_the_top_ranks(self):
        expectations = {'BurntSushi/ripgrep': ({278}, 5), 'honojs/hono': ({2343, 5106}, 8),
                        'pallets/click': ({2823, 2834, 3097}, 12)}
        for repository, (numbers, rank) in expectations.items():
            with self.subTest(repository=repository):
                issues = FIXTURE['repositories'][repository]['issues']
                before = ranked(issues, lambda item: item['before_score'])
                after = ranked(issues, lambda item: signals.issue_signals(synthetic(item), PATHS, NOW)['score'])
                self.assertTrue(numbers & {item['number'] for item in before[:rank]})
                self.assertFalse(numbers & {item['number'] for item in after[:rank]})
                self.assertTrue(all(item['verdict'] == 'bad' for item in issues if item['number'] in numbers))


if __name__ == '__main__':
    unittest.main()
