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

    def test_malformed_budget_is_unknown_not_zero(self):
        snap = budget.snapshot(BudgetGitHub(malformed=True))
        self.assertIsNone(snap['remaining'])
        self.assertTrue(snap['error'])
        code, result = run(BudgetGitHub(malformed=True), '--report-budget', 'discover', 'acme/photos')
        self.assertEqual(code, 0)
        self.assertIsNone(result['api_budget']['used_during_command'])

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
