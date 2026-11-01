"""Opt-in API budget reporting: no default change, fail-early threshold, malformed limits unknown."""
import contextlib
import io
import json
import unittest
from unittest.mock import patch

from agent_contribute import budget, cli, core
from tests.test_protocol import FakeGitHub


class BudgetGitHub(FakeGitHub):
    def __init__(self, remaining=4000, malformed=False):
        super().__init__()
        self.used = 5000 - remaining
        self.malformed = malformed

    def request(self, endpoint):
        if endpoint == 'rate_limit':
            self.calls.append(endpoint)
            core_limit = {'limit': 5000, 'remaining': 5000 - self.used, 'used': self.used, 'reset': 1900000000}
            if self.malformed:
                core_limit['remaining'] = '4000'
            return {'resources': {'core': core_limit}}
        self.used += 1
        return super().request(endpoint)


def run(client, *argv):
    output = io.StringIO()
    with patch.object(core, 'GitHub', return_value=client), contextlib.redirect_stdout(output):
        code = cli.main(list(argv))
    return code, json.loads(output.getvalue())


class BudgetTests(unittest.TestCase):
    def test_default_output_is_unchanged_and_makes_no_rate_limit_read(self):
        client = BudgetGitHub()
        code, result = run(client, 'discover', 'acme/photos')
        self.assertEqual(code, 0)
        self.assertNotIn('api_budget', result)
        self.assertNotIn('rate_limit', client.calls)

    def test_report_counts_reads_between_snapshots(self):
        client = BudgetGitHub()
        code, result = run(client, '--report-budget', 'discover', 'acme/photos')
        self.assertEqual(code, 0)
        reads = len([c for c in client.calls if c != 'rate_limit'])
        self.assertEqual(result['api_budget']['used_during_command'], reads)
        self.assertEqual(client.calls[0], 'rate_limit')
        self.assertEqual(client.calls[-1], 'rate_limit')

    def test_min_remaining_fails_before_any_command_read(self):
        client = BudgetGitHub(remaining=10)
        code, result = run(client, '--report-budget', '--min-remaining', '100', 'discover', 'acme/photos')
        self.assertEqual((code, result['error']['code']), (1, 'rate_limit_budget'))
        self.assertEqual(client.calls, ['rate_limit'])
        client = BudgetGitHub(malformed=True)
        code, result = run(client, '--report-budget', '--min-remaining', '1', 'discover', 'acme/photos')
        self.assertEqual(result['error']['code'], 'rate_limit_budget')

    def test_inconsistent_counters_are_unknown_and_deltas_never_negative(self):
        class Limits:
            def __init__(self, limit, remaining, used, reset=1900000000):
                self.values = dict(limit=limit, remaining=remaining, used=used, reset=reset)
            def request(self, endpoint):
                return {'resources': {'core': self.values}}
        for limit, remaining, used in [(10, 9999, 0), (5000, 4000, 2000), (5000, 6000, 0), (100, 50, 200)]:
            with self.subTest(limit=limit, remaining=remaining, used=used):
                snap = budget.snapshot(Limits(limit, remaining, used))
                self.assertTrue(snap['error'])
                self.assertIsNone(snap['remaining'])
                with self.assertRaises(core.ProtocolError):
                    budget.require_remaining(snap, 1)
        before = budget.snapshot(Limits(5000, 4000, 1000))
        for after, reason in [(Limits(5000, 4100, 900), 'decreased'), (Limits(5000, 5000, 0, reset=1900003600), 'reset'),
                              (Limits(15000, 13900, 1100), 'limit')]:
            with self.subTest(reason=reason):
                report = budget.report(before, after)
                self.assertIsNone(report['used_during_command'])
                self.assertIn(reason, report['delta_unknown_reason'])
        report = budget.report(before, Limits(5000, 3990, 1010))
        self.assertEqual((report['used_during_command'], report['delta_unknown_reason']), (10, None))

    def test_malformed_budget_is_unknown_not_zero(self):
        snap = budget.snapshot(BudgetGitHub(malformed=True))
        self.assertIsNone(snap['remaining'])
        self.assertTrue(snap['error'])
        code, result = run(BudgetGitHub(malformed=True), '--report-budget', 'discover', 'acme/photos')
        self.assertEqual(code, 0)
        self.assertIsNone(result['api_budget']['used_during_command'])

    def test_invalid_inputs_are_rejected_before_the_budget_read(self):
        too_many = ['o/r%d' % i for i in range(21)]
        for argv, code in [(['discover'], 2), (['discover', 'acme/photos', 'ACME/photos'], 2),
                           (['discover', 'invalid'], 1), (['discover', 'a/b', 'invalid'], 1), (['discover', *too_many], 2),
                           (['discover', '--repositories-file', '/nonexistent/repos.txt'], 1),
                           (['inspect', 'acme/photos#0'], 1), (['ownership', 'nope'], 1), (['audit', 'x'], 1),
                           (['feedback', 'acme/photos#30', '--expected-head', 'HEAD'], 1),
                           (['verify', '/nonexistent/task.json'], 1), (['drift', '/nonexistent/task.json'], 1),
                           (['pr-body', '/nonexistent/task.json', '--output', '/nonexistent/x.md'], 1)]:
            with self.subTest(argv=argv):
                client = BudgetGitHub()
                result_code, result = run(client, '--report-budget', *argv)
                self.assertEqual(result_code, code, result)
                self.assertIn('error', result)
                self.assertEqual(client.calls, [], 'no read, including rate_limit, before input validation')
                plain_code, plain = run(BudgetGitHub(), *argv)
                self.assertEqual((plain_code, plain['error']['code']), (result_code, result['error']['code']))

    def test_usage_errors(self):
        for argv in [('--min-remaining', '5', 'discover', 'acme/photos'),
                     ('--report-budget', '--min-remaining', '-1', 'discover', 'acme/photos'),
                     ('--report-budget', 'instructions')]:
            client = BudgetGitHub()
            code, result = run(client, *argv)
            self.assertEqual((code, result['error']['code']), (2, 'usage'))
            self.assertEqual(client.calls, [])


if __name__ == '__main__':
    unittest.main()
