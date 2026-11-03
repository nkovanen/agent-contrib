"""A display budget must not become an acquisition, ranking or safety budget."""
import contextlib
import io
import json
import tempfile
import unittest
from unittest.mock import patch

from agent_contribute import cli, core, multi, textfmt
from tests.test_check_top import CheckGitHub
from tests.test_discover_golden import scenarios, GOLDEN
from tests.test_protocol import FakeGitHub
from tests.test_resolution import RepositoryGitHub, pr
from tests.test_schema_compatibility import FrozenClock


def issue(client, number, **changes):
    value = client.request('repos/acme/photos/issues/12')
    value.update(number=number, html_url=f'https://github.com/acme/photos/issues/{number}', **changes)
    return value


def client_with_issues():
    client = RepositoryGitHub()
    client.overrides['repos/acme/photos/issues?state=open&per_page=100&page=1'] = [
        issue(client, 3, labels=[{'name': 'in progress'}]), issue(client, 2), issue(client, 1)]
    return client


def invoke(client, *argv):
    output = io.StringIO()
    with patch.object(core, 'GitHub', return_value=client), contextlib.redirect_stdout(output):
        code = cli.main(list(argv))
    return code, json.loads(output.getvalue())


class DiscoveryLimitTests(unittest.TestCase):
    def test_rank_first_and_preserve_context_for_ordinary_and_disabled_fork(self):
        for repo in ('acme/photos', 'person/photos'):
            with self.subTest(repo=repo), patch.object(core.dt, 'datetime', FrozenClock):
                full = core.discover(repo, client_with_issues())
                limited = core.discover(repo, client_with_issues(), limit=1)
                self.assertEqual(limited.pop('display'), {'requested_limit': 1, 'total_issues_considered': 3,
                    'returned': 1, 'omitted': 2, 'truncated': True, 'overlapping': 0, 'excluded': 1})
                self.assertEqual([item['reference'] for item in limited['issues']], [repo + '#1'])
                self.assertEqual(limited['issues'], full['issues'][:1])
                limited['issues'] = full['issues']
                self.assertEqual(limited, full)

    def test_late_pages_and_hidden_overlaps_are_still_scanned(self):
        client = client_with_issues()
        client.overrides['repos/acme/photos/issues?state=open&per_page=100&page=1'] = [
            issue(client, n) for n in range(1, 101)]
        client.overrides['repos/acme/photos/issues?state=open&per_page=100&page=2'] = [issue(client, 101)]
        endpoint = 'repos/person/photos/pulls?state=open&per_page=100&page='
        client.overrides[endpoint + '1'] = [pr('person/photos', n, '') for n in range(1, 101)]
        client.overrides[endpoint + '2'] = [pr('person/photos', 101, 'Fixes acme/photos#1 and acme/photos#101')]
        result = core.discover('person/photos', client, limit=1)
        self.assertTrue(result['complete'], result['errors'])
        self.assertEqual([i['number'] for i in result['issues']], [2])
        self.assertEqual(result['display']['total_issues_considered'], 101)
        self.assertEqual(result['display']['overlapping'], 2)
        self.assertIn(endpoint + '2', client.calls)
        self.assertIn('repos/acme/photos/issues?state=open&per_page=100&page=2', client.calls)
        text = '\n'.join(textfmt._discover(result))
        self.assertIn('shown 1 of 101', text)
        self.assertIn('omitted 100', text)
        self.assertIn('Overlapping issues: 2 of 101', text)

    def test_incomplete_pages_and_hidden_malformed_issues_do_not_disappear(self):
        for resource in ('issues', 'pulls', 'malformed'):
            with self.subTest(resource=resource):
                client = client_with_issues()
                if resource == 'malformed':
                    client.overrides['repos/acme/photos/issues?state=open&per_page=100&page=1'].append(
                        {'number': 500, 'title': 'missing required fields'})
                else:
                    repo = 'acme/photos' if resource == 'issues' else 'person/photos'
                    endpoint = f'repos/{repo}/{resource}?state=open&per_page=100&page='
                    client.overrides[endpoint + '1'] = ([issue(client, n) for n in range(1, 101)]
                        if resource == 'issues' else [pr(repo, n, '') for n in range(1, 101)])
                    client.failed.add(endpoint + '2')
                result = core.discover('person/photos', client, limit=1)
                self.assertFalse(result['complete'])
                self.assertTrue(result['errors'])
                self.assertEqual(result['display']['returned'], 1)

    def test_boundaries_empty_and_unresolved_results(self):
        for count, limit in ((3, 3), (3, 1000), (0, 1)):
            client = client_with_issues()
            client.overrides['repos/acme/photos/issues?state=open&per_page=100&page=1'] = [
                issue(client, n) for n in range(1, count + 1)]
            result = core.discover('acme/photos', client, limit=limit)
            self.assertEqual((result['display']['returned'], result['display']['omitted'],
                              result['display']['truncated']), (count, 0, False))
        client.failed.add('repos/person/photos')
        result = core.discover('person/photos', client, limit=1)
        self.assertFalse(result['complete'])
        self.assertEqual(result['display']['total_issues_considered'], 0)

    def test_invalid_library_limits_fail_before_reads_in_single_and_multi(self):
        for value in (0, -1, 1001, True, 1.5, '', 'abc', '1.0', '١', ' 1', '+1', '9' * 5000):
            for many in (False, True):
                with self.subTest(value=str(value)[:20], many=many):
                    client = FakeGitHub()
                    with self.assertRaises(core.ProtocolError) as caught:
                        if many:
                            multi.discover_many(['acme/photos', 'person/photos'], client, limit=value)
                        else:
                            core.discover('acme/photos', client, limit=value)
                    self.assertEqual(caught.exception.code, 'invalid_limit')
                    self.assertEqual(client.calls, [])

    def test_cli_validation_precedes_budget_and_github_reads(self):
        for value in ('0', '-1', '1001', 'abc', '1.0', '١', '9' * 5000):
            with self.subTest(value=value[:20]):
                client = FakeGitHub()
                code, result = invoke(client, '--report-budget', 'discover', 'acme/photos', '--limit', value)
                self.assertEqual((code, result['error']['code']), (1, 'invalid_limit'))
                self.assertEqual(client.calls, [])
        code, result = invoke(FakeGitHub(), 'discover', 'acme/photos', '--limit')
        self.assertEqual((code, result['error']['code']), (2, 'usage'))
        for value in ('1', '00001', '0' * 5000 + '1'):
            code, result = invoke(client_with_issues(), 'discover', 'acme/photos', '--limit', value)
            self.assertEqual(code, 0)
            self.assertEqual(result['display']['requested_limit'], 1)
            self.assertEqual([i['number'] for i in result['issues']], [1])
            self.assertIn('repository_policy', result)

    def test_multi_global_budget_preserves_empty_and_failed_repository_context(self):
        code, result = invoke(client_with_issues(), 'discover', 'person/photos', 'missing/repo',
                              'acme/photos', '--limit', '2')
        self.assertEqual(code, 1)
        self.assertEqual([c['reference'] for c in result['candidates']], ['acme/photos#1', 'acme/photos#2'])
        self.assertEqual(result['display'], {'requested_limit': 2, 'total_issues_considered': 6,
            'returned': 2, 'omitted': 4, 'truncated': True, 'overlapping': 0, 'excluded': 2})
        by = {r['requested_repository']: r for r in result['repositories']}
        self.assertTrue(by['person/photos']['complete'])
        self.assertEqual(by['person/photos']['issues'], [])
        self.assertEqual(by['person/photos']['display']['omitted'], 3)
        self.assertIn('repository_policy', by['person/photos'])
        self.assertEqual(by['person/photos']['issue_source_repository'], 'acme/photos')
        self.assertFalse(by['missing/repo']['complete'])
        self.assertEqual(by['missing/repo']['display']['returned'], 0)

    def test_ranking_aids_and_their_reads_finish_before_slicing(self):
        with patch.object(core.dt, 'datetime', FrozenClock):
            full_client, limited_client = CheckGitHub(), CheckGitHub()
            options = dict(signals=True, check_top=5, responsiveness=True)
            full = core.discover('acme/photos', full_client, **options)
            limited = core.discover('acme/photos', limited_client, limit=1, **options)
        self.assertEqual([i['number'] for i in limited['issues']], [2])
        self.assertEqual(limited_client.calls, full_client.calls)
        self.assertEqual(limited['top_check'], full['top_check'])
        self.assertEqual(limited['repository_signals'], full['repository_signals'])
        self.assertEqual(limited['display']['overlapping'], 1)
        self.assertEqual(limited['top_check']['checked'], 5)

    def test_local_ranking_and_policy_reads_are_not_shortened_by_display_budget(self):
        from tests.test_local_work import checkout, commit
        with tempfile.TemporaryDirectory() as tmp:
            git, base = checkout(tmp)
            commit(git, 'Fix #1\nFix #4')
            full_client, limited_client = CheckGitHub(), CheckGitHub()
            full_client.commit = limited_client.commit = base
            argv = ['discover', 'acme/photos', '--signals', '--check-top', '2', '--repo-dir', tmp]
            full_code, full = invoke(full_client, *argv)
            code, limited = invoke(limited_client, *argv, '--limit', '1')
        self.assertEqual((full_code, code), (0, 0))
        self.assertEqual([i['number'] for i in limited['issues']], [2])
        self.assertEqual(limited['local_work'], full['local_work'])
        self.assertEqual(limited['top_check']['checked'], 2)
        from tests.test_cache import without_times
        self.assertEqual(without_times(limited['repository_policy']), without_times(full['repository_policy']))
        self.assertEqual(limited_client.calls, full_client.calls)

    def test_hidden_incomplete_top_check_keeps_nonzero_exit_and_text_status(self):
        client = CheckGitHub()
        client.timelines[4] = [{'id': 1000 + i, 'event': 'labeled'} for i in range(100)]
        output = io.StringIO()
        with patch.object(core, 'GitHub', return_value=client), contextlib.redirect_stdout(output):
            code = cli.main(['--format', 'text', 'discover', 'acme/photos', '--signals',
                             '--check-top', '5', '--limit', '1'])
        self.assertEqual(code, 1)
        self.assertIn('Complete: yes\n', output.getvalue())
        self.assertIn('Top check: complete no; checked 5 of 5', output.getvalue())
        self.assertIn('shown 1 of 7', output.getvalue())
        self.assertNotIn('acme/photos#4 [', output.getvalue())

    def test_conflicting_issue_identities_never_complete_or_expand_projection(self):
        # Reject both aliases of one number and one API identity claiming different numbers.
        for ids, numbers in (((101, 102), (1, 1)), ((101, 101), (1, 2)), ((101, 101), (1, 1))):
            for limit in (None, 1):
                with self.subTest(ids=ids, numbers=numbers, limit=limit):
                    client = RepositoryGitHub()
                    client.overrides['repos/acme/photos/issues?state=open&per_page=100&page=1'] = [
                        dict(issue(client, number), id=identity) for identity, number in zip(ids, numbers)]
                    result = multi.discover_many(['acme/photos', 'person/photos'], client, limit=limit)
                    self.assertFalse(result['complete'])
                    self.assertTrue(result['errors'])
                    self.assertTrue(all(not r['complete'] and r['issue_scan']['complete'] is False
                                        for r in result['repositories']))
                    self.assertTrue(all(len(r['issues']) <= 1 for r in result['repositories']))
                    details = [i['reference'] for r in result['repositories'] for i in r['issues']]
                    self.assertEqual(details, [c['reference'] for c in result['candidates']])
                    self.assertTrue(all(not c['complete'] for c in result['candidates']))
                    if limit is not None:
                        self.assertEqual(result['display']['returned'], 1)
                        self.assertEqual(result['display']['returned'], len(details))
                        self.assertEqual(result['display']['total_issues_considered'], 2)

    def test_late_conflicting_number_with_distinct_api_id_marks_scan_incomplete(self):
        client = RepositoryGitHub()
        endpoint = 'repos/acme/photos/issues?state=open&per_page=100&page='
        client.overrides[endpoint + '1'] = [dict(issue(client, n), id=1000 + n) for n in range(1, 101)]
        client.overrides[endpoint + '2'] = [dict(issue(client, 1), id=5001), dict(issue(client, 101), id=1101)]
        result = core.discover('acme/photos', client, limit=1)
        self.assertFalse(result['complete'])
        self.assertFalse(result['issue_scan']['complete'])
        self.assertTrue(result['issue_scan']['errors'])
        self.assertEqual(result['display']['total_issues_considered'], 101)
        self.assertEqual(result['display']['returned'], 1)
        self.assertEqual(result['display']['omitted'], 100)
        self.assertEqual(result['issues'][0]['reference'], 'acme/photos#1')
        self.assertFalse(result['issues'][0]['complete'])
        self.assertIn(endpoint + '2', client.calls)

    def test_explicit_no_limit_preserves_frozen_output_and_reads(self):
        with patch.object(core.dt, 'datetime', FrozenClock):
            for name, (repo, client) in scenarios().items():
                with self.subTest(name=name):
                    result = core.discover(repo, client, limit=None)
                    expected = json.loads((GOLDEN / (name + '.json')).read_text())
                    self.assertEqual({'result': result, 'calls': client.calls}, expected)
