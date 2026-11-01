"""Display limits must never shorten discovery or hide incomplete scans."""
import io
import json
import unittest
from unittest.mock import patch

from agent_contribute import core
from agent_contribute.cli import main
from tests.test_protocol import FakeGitHub
from tests.test_resolution import RepositoryGitHub, pr


def issue(client, number, **changes):
    value = client.request('repos/acme/photos/issues/12')
    value.update(number=number, html_url=f'https://github.com/acme/photos/issues/{number}', **changes)
    return value


class DiscoveryLimitTests(unittest.TestCase):
    def client(self):
        client = RepositoryGitHub()
        client.overrides['repos/acme/photos/issues?state=open&per_page=100&page=1'] = [
            issue(client, 3, labels=[{'name': 'in progress'}]),
            issue(client, 2), issue(client, 1)]
        return client

    def test_limit_is_applied_after_ranking_and_preserves_other_fields(self):
        for repo in ('acme/photos', 'person/photos'):
            with self.subTest(repo=repo):
                client = self.client()
                full = core.discover(repo, client)
                limited = core.discover(repo, client, limit=1)
                display = limited.pop('display')
                self.assertEqual(display, {'requested_limit': 1, 'total_issues_considered': 3,
                                           'returned': 1, 'truncated': True})
                self.assertEqual(limited['issues'], full['issues'][:1])
                self.assertEqual(limited['issues'][0]['number'], 1)
                self.assertEqual(limited['issues'][0]['reference'], repo + '#1')
                limited['issues'] = full['issues']
                limited.pop('fetched_at'); full.pop('fetched_at')
                # Metadata-read times are observations, not behavior changes.
                limited.pop('resolution_provenance'); full.pop('resolution_provenance')
                self.assertEqual(limited, full)

    def test_full_issue_and_pr_pagination_with_late_overlap(self):
        client = self.client()
        client.overrides['repos/acme/photos/issues?state=open&per_page=100&page=1'] = [
            issue(client, n) for n in range(1, 101)]
        client.overrides['repos/acme/photos/issues?state=open&per_page=100&page=2'] = [issue(client, 101)]
        client.overrides['repos/person/photos/pulls?state=open&per_page=100&page=1'] = [
            pr('person/photos', n, '', title='Unrelated') for n in range(1, 101)]
        client.overrides['repos/person/photos/pulls?state=open&per_page=100&page=2'] = [
            pr('person/photos', 101, 'Fixes acme/photos#1')]
        result = core.discover('person/photos', client, limit=1)
        self.assertTrue(result['complete'], result['errors'])
        self.assertEqual(result['display']['total_issues_considered'], 101)
        self.assertEqual(result['issues'][0]['number'], 2)  # #1 has overlap on a late PR page.
        self.assertIn('repos/acme/photos/issues?state=open&per_page=100&page=2', client.calls)
        self.assertIn('repos/person/photos/pulls?state=open&per_page=100&page=2', client.calls)

    def test_incomplete_issue_and_pr_scans_remain_incomplete(self):
        for resource in ('issues', 'pulls'):
            with self.subTest(resource=resource):
                client = self.client()
                repo = 'acme/photos' if resource == 'issues' else 'person/photos'
                endpoint = f'repos/{repo}/{resource}?state=open&per_page=100&page='
                client.overrides[endpoint + '1'] = ([issue(client, n) for n in range(1, 101)]
                    if resource == 'issues' else [pr(repo, n, '') for n in range(1, 101)])
                client.failed.add(endpoint + '2')
                result = core.discover('person/photos', client, limit=1)
                self.assertFalse(result['complete'])
                self.assertTrue(result['errors'])
                self.assertIn(endpoint + '2', client.calls)
                self.assertLessEqual(result['display']['returned'], 1)

    def test_exact_limit_larger_limit_and_empty_result(self):
        for count, limit in ((3, 3), (3, 1000), (0, 1)):
            client = self.client()
            endpoint = 'repos/acme/photos/issues?state=open&per_page=100&page=1'
            client.overrides[endpoint] = [issue(client, n) for n in range(1, count + 1)]
            result = core.discover('acme/photos', client, limit=limit)
            self.assertEqual(result['display'], {'requested_limit': limit,
                'total_issues_considered': count, 'returned': count, 'truncated': False})

    def test_resolution_failure_still_has_display_metadata(self):
        client = self.client()
        client.failed.add('repos/person/photos')
        result = core.discover('person/photos', client, limit=1)
        self.assertFalse(result['complete'])
        self.assertEqual(result['display'], {'requested_limit': 1,
            'total_issues_considered': 0, 'returned': 0, 'truncated': False})

    def test_invalid_library_limits_fail_before_network(self):
        for value in (0, -1, 1001, True, 1.5, 'abc', '1.0', '١', '9' * 5000):
            with self.subTest(value=str(value)[:20]):
                client = FakeGitHub()
                with self.assertRaises(core.ProtocolError):
                    core.discover('acme/photos', client, limit=value)
                self.assertEqual(client.calls, [])

    def invoke(self, argv):
        output = io.StringIO()
        with patch('sys.stdout', output):
            status = main(argv)
        return status, json.loads(output.getvalue())

    def test_cli_limit_and_omission(self):
        for args, expected in (([], None), (['--limit', '1'], 1)):
            client = self.client()
            with patch.object(core, 'GitHub', return_value=client):
                status, result = self.invoke(['discover', 'acme/photos', *args])
            self.assertEqual(status, 0)
            if expected is None:
                self.assertNotIn('display', result)
                self.assertEqual(len(result['issues']), 3)
            else:
                self.assertEqual(result['display']['requested_limit'], expected)
                self.assertEqual(len(result['issues']), 1)

    def test_leading_zero_decimal_limits_have_the_same_value(self):
        for value in ('0001', '00001', '0' * 5000 + '1'):
            with self.subTest(digits=len(value)):
                result = core.discover('acme/photos', self.client(), limit=value)
                self.assertEqual(result['display']['requested_limit'], 1)
                with patch.object(core, 'GitHub', return_value=self.client()):
                    status, result = self.invoke(['discover', 'acme/photos', '--limit', value])
                self.assertEqual(status, 0)
                self.assertEqual(result['display']['requested_limit'], 1)

    def test_cli_invalid_limits_are_structured_errors_without_network(self):
        for value in ('0', '-1', '1001', 'abc', '1.0', '١', '9' * 5000):
            with self.subTest(value=value[:20]), patch.object(core, 'GitHub') as github:
                status, result = self.invoke(['discover', 'acme/photos', '--limit', value])
                self.assertNotEqual(status, 0)
                self.assertIn('code', result['error'])
                github.assert_not_called()
