"""Offline planning never turns a discovery snapshot into permission."""
import contextlib
import copy
import hashlib
import io
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from agent_contribute import cli, core, multi, sessions
from tests.test_protocol import FakeGitHub


def report():
    return core.discover('acme/photos', FakeGitHub())


class SessionTests(unittest.TestCase):
    def plan(self, source=None, **options):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'discovery.json'
            path.write_text(json.dumps(source if source is not None else report()), encoding='utf-8')
            return sessions.plan(path, max_tasks=options.get('max_tasks', 3), minutes=options.get('minutes', 60))

    def test_order_caps_source_and_no_authority(self):
        source = report()
        first = source['issues'][0]
        second = copy.deepcopy(first)
        second.update(number=99, reference='acme/photos#99', issue_url='https://github.com/acme/photos/issues/99')
        source['issues'] = [second, first]
        result = self.plan(source, minutes=61)
        self.assertEqual([t['reference'] for t in result['tasks']], [second['reference'], first['reference']])
        self.assertEqual([t['stop_after_minutes'] for t in result['tasks']], [31, 30])
        self.assertEqual(result['source_report'], source)
        self.assertEqual(result['status'], 'proposed')
        self.assertIs(result['actions_authorized'], False)
        for task in result['tasks']:
            self.assertEqual(len(task['required_follow_up']), 4)
        self.assertEqual(result['source_file_sha256'], hashlib.sha256(json.dumps(source).encode()).hexdigest())

    def test_incomplete_excluded_overlap_and_budget_remain_visible(self):
        for change, reason in [({'complete': False}, 'issue_incomplete'),
                               ({'exclusions': ['ban']}, 'excluded'),
                               ({'approval': {'status': 'unknown', 'policy_path': '.agent-contrib.json',
                                              'policy_commit': 'a'*40, 'matched_labels': [], 'reason': 'unknown'}},
                                'source_approval_unknown')]:
            source = report()
            source['issues'][0].update(change)
            result = self.plan(source)
            self.assertFalse(result['tasks'])
            self.assertIn(reason, result['candidates'][0]['reasons'])
        source = report()
        source['complete'] = False
        source['errors'] = ['failed read']
        result = self.plan(source)
        self.assertFalse(result['tasks'])
        self.assertIn('repository_incomplete', result['candidates'][0]['reasons'])
        self.assertFalse(result['source_complete'])

    def test_rejects_forged_duplicate_unknown_and_conflicting_input(self):
        for edit in [lambda r: r['issues'][0].update(issue_url='https://evil.test/issues/12'),
                     lambda r: r['issues'].append(copy.deepcopy(r['issues'][0])),
                     lambda r: r.update(schema_version='999'),
                     lambda r: r['issues'][0].update(reference='other/repo#12'),
                     lambda r: r['issues'][0].update(number=True)]:
            source = report()
            edit(source)
            with self.subTest(source=source), self.assertRaises(core.ProtocolError):
                self.plan(source)

    def test_multi_uses_merged_order_and_retains_failed_repository(self):
        client = FakeGitHub()
        original_request = client.request
        def request(endpoint):
            if endpoint.startswith('repos/other/repo'):
                raise core.ProtocolError('api_error', 'unavailable')
            return original_request(endpoint)
        client.request = request
        source = multi.discover_many(['acme/photos', 'other/repo'], client)
        # FakeGitHub is intentionally bound to acme/photos; the second result fails.
        result = self.plan(source)
        self.assertEqual(result['source_report'], source)
        self.assertEqual([t['reference'] for t in result['tasks']],
                         [c['reference'] for c in source['candidates'] if c['complete']])
        forged = copy.deepcopy(source)
        forged['candidates'][0]['overlapping'] = True
        with self.assertRaises(core.ProtocolError):
            self.plan(forged)

    def test_limited_source_keeps_counts_and_stopping_budget_bound(self):
        source = report()
        core.limit_discovery(source, 1)
        result = self.plan(source, max_tasks=20, minutes=1)
        self.assertLessEqual(len(result['tasks']), 1)
        self.assertEqual(result['source_report']['display'], source['display'])
        for tasks, minutes in [(0, 60), (21, 60), (1, 0), (1, 1441), (True, 60)]:
            with self.assertRaises(core.ProtocolError):
                self.plan(max_tasks=tasks, minutes=minutes)

    def test_bounded_regular_strict_json_input(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'input'
            for data in [b'{"x":1,"x":2}', b' ' * (8*1024*1024+1), b'\xff']:
                path.write_bytes(data)
                with self.assertRaises(core.ProtocolError):
                    sessions.plan(path, max_tasks=1, minutes=60)
            with self.assertRaises(core.ProtocolError):
                sessions.plan(directory, max_tasks=1, minutes=60)

    def test_cli_offline_exclusive_and_text_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = [pathlib.Path(directory) / name for name in ('source.json', 'session.json')]
            source.write_text(json.dumps(report()))
            args = ['session', str(source), '--max-tasks', '2', '--minutes', '60', '--output', str(output)]
            with patch.object(core.GitHub, 'request', side_effect=AssertionError('network')), contextlib.redirect_stdout(io.StringIO()) as stdout:
                self.assertEqual(cli.main(['--format', 'text', *args]), 0)
                self.assertIn('not authorized', stdout.getvalue())
                original = output.read_bytes()
                self.assertEqual(cli.main(args), 1)
                self.assertEqual(output.read_bytes(), original)
                self.assertEqual(cli.main(['--report-budget', *args]), 2)

    def test_overlap_stays_visible_and_does_not_receive_time(self):
        source = core.discover('acme/photos', FakeGitHub(prs=[
            {'number': 30, 'title': 'fix', 'body': 'Fixes #12',
             'html_url': 'https://github.com/acme/photos/pull/30', 'head': None}]))
        result = self.plan(source)
        self.assertEqual(result['tasks'], [])
        self.assertEqual(result['allocated_minutes'], 0)
        self.assertIn('overlapping', result['candidates'][0]['reasons'])

    def test_capacity_and_hidden_counts_are_honest(self):
        source = report()
        for number in (13, 14):
            issue = copy.deepcopy(source['issues'][0])
            issue.update(number=number, reference=f'acme/photos#{number}',
                         issue_url=f'https://github.com/acme/photos/issues/{number}')
            source['issues'].append(issue)
        result = self.plan(source, max_tasks=3, minutes=2)
        self.assertEqual([t['stop_after_minutes'] for t in result['tasks']], [1, 1])
        self.assertEqual(result['candidates'][2]['reasons'], ['session_capacity'])
        core.limit_discovery(source, 1)
        result = self.plan(source)
        self.assertEqual(result['source_report']['display']['omitted'], 2)
        source['display']['returned'] = 9
        with self.assertRaises(core.ProtocolError):
            self.plan(source)

    def test_unsupported_issue_number_does_not_become_unusable_task(self):
        source = report()
        number = 10**20
        source['issues'][0].update(number=number, reference=f'acme/photos#{number}',
                                   issue_url=f'https://github.com/acme/photos/issues/{number}')
        with self.assertRaises(core.ProtocolError):
            self.plan(source)

    def test_complete_multi_order_is_preserved_and_missing_entries_rejected(self):
        from tests.test_multi_discover import MultiGitHub
        client = MultiGitHub()
        client.metadata['other/repo'] = dict(full_name='other/repo', default_branch='main', fork=False, has_issues=True)
        client.repos['other/repo'] = FakeGitHub()
        source = multi.discover_many(['acme/photos', 'other/repo'], client)
        # The transport fixture returns acme URLs for every tracker; use consistent independent identities.
        source['repositories'][1]['issues'][0]['issue_url'] = 'https://github.com/other/repo/issues/12'
        source['candidates'].reverse()
        result = self.plan(source)
        self.assertEqual([t['reference'] for t in result['tasks']],
                         [c['reference'] for c in source['candidates']])
        source['candidates'].pop()
        with self.assertRaises(core.ProtocolError):
            self.plan(source)

    def test_duplicate_alias_reports_fail_closed(self):
        from tests.test_multi_discover import MultiGitHub
        source = multi.discover_many(['acme/photos', 'person/photos'], MultiGitHub())
        source['repositories'][1] = copy.deepcopy(source['repositories'][0])
        with self.assertRaises(core.ProtocolError):
            self.plan(source)

    def test_single_fork_retains_requested_reference_and_source_url(self):
        from tests.test_resolution import RepositoryGitHub
        source = core.discover('person/photos', RepositoryGitHub())
        result = self.plan(source)
        self.assertEqual(result['tasks'][0]['reference'], 'person/photos#12')
        self.assertEqual(result['tasks'][0]['issue_url'], 'https://github.com/acme/photos/issues/12')

    def test_incomplete_scan_cannot_be_overridden_by_complete_flag(self):
        source = report()
        source['provenance']['pulls_scan']['complete'] = False
        source['provenance']['pulls_scan']['errors'] = ['cap reached']
        result = self.plan(source)
        self.assertEqual(result['tasks'], [])
        self.assertIn('repository_scans_incomplete', result['candidates'][0]['reasons'])
