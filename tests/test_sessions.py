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

from agent_contribute import cli, core, multi, outputs, sessions
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

    def test_incomplete_local_work_producer_blocks_with_or_without_signals(self):
        for with_signals in (False, True):
            with tempfile.TemporaryDirectory() as directory:
                source = core.discover('acme/photos', FakeGitHub(), signals=with_signals,
                                       repo_dir=str(pathlib.Path(directory) / 'missing'))
            self.assertFalse(source['local_work']['complete'])
            result = self.plan(source)
            self.assertEqual(result['tasks'], [])
            self.assertIn('local_work_incomplete', result['candidates'][0]['reasons'])

    def test_unknown_local_work_signal_blocks_despite_complete_repository(self):
        source = core.discover('acme/photos', FakeGitHub(), signals=True)
        source['issues'][0]['signals']['local_work'] = {
            'value': 'unknown', 'commits': [], 'explanation': 'Checkout was not fully read'}
        self.assertEqual(core.schema_errors(source, outputs.output_schema('discover')), [])
        result = self.plan(source)
        self.assertEqual(result['tasks'], [])
        self.assertIn('local_work_unknown', result['candidates'][0]['reasons'])

    def test_completed_top_checks_exclude_known_assignees_and_merged_fixes(self):
        from tests.test_check_top import CheckGitHub
        source = core.discover('acme/photos', CheckGitHub(), signals=True, check_top=5)
        result = self.plan(source, max_tasks=20)
        decisions = {c['reference']: c for c in result['candidates']}
        self.assertIn('ownership_existing_work', decisions['acme/photos#1']['reasons'])
        self.assertIn('current_assignee', decisions['acme/photos#3']['reasons'])
        self.assertTrue(decisions['acme/photos#2']['selected'])  # report-only claims still require manual review
        # Assignees on issues below the checked range remain known signals.
        source = core.discover('acme/photos', CheckGitHub(), signals=True, check_top=1)
        result = self.plan(source, max_tasks=20)
        assigned = next(c for c in result['candidates'] if c['reference'] == 'acme/photos#3')
        self.assertIn('current_assignee', assigned['reasons'])

    def test_local_reference_producer_blocks_with_or_without_signals(self):
        from tests.test_local_work import checkout, commit
        for with_signals in (False, True):
            with tempfile.TemporaryDirectory() as directory:
                git, base = checkout(directory)
                commit(git, 'Fix #12')
                client = FakeGitHub()
                client.commit = base
                source = core.discover('acme/photos', client, signals=with_signals, repo_dir=directory)
            self.assertTrue(source['local_work']['complete'])
            result = self.plan(source)
            self.assertEqual(result['tasks'], [])
            self.assertIn('local_work_referenced', result['candidates'][0]['reasons'])

    def test_target_and_metadata_contradictions_fail_closed(self):
        from tests.test_resolution import RepositoryGitHub
        plain = report()
        fork = core.discover('person/photos', RepositoryGitHub())
        mutations = [
            (plain, lambda r: r.update(proposed_target_repository='evil/other')),
            (plain, lambda r: r['resolution_provenance']['metadata_reads'][0]['observed'].update(full_name='evil/other')),
            (plain, lambda r: r['resolution_provenance']['metadata_reads'][0].update(endpoint='repos/evil/other')),
            (plain, lambda r: r['resolution_provenance']['metadata_reads'].clear()),
            (fork, lambda r: r['resolution_provenance']['metadata_reads'][0]['observed']['parent'].update(full_name='evil/other')),
            (fork, lambda r: r['resolution_provenance']['metadata_reads'][0]['observed'].update(fork=False)),
            (fork, lambda r: r['resolution_provenance']['metadata_reads'][1]['observed'].update(has_issues=False)),
            (fork, lambda r: r['resolution_provenance'].update(execution_authority='granted')),
        ]
        for index, (original, mutate) in enumerate(mutations):
            source = copy.deepcopy(original)
            mutate(source)
            with self.subTest(mutation=index), self.assertRaises(core.ProtocolError):
                self.plan(source)

    def test_unassessed_legacy_and_fork_still_require_manual_review(self):
        from tests.test_resolution import RepositoryGitHub
        for source in (report(), core.discover('person/photos', RepositoryGitHub())):
            result = self.plan(source)
            self.assertEqual(len(result['tasks']), 1)
            self.assertIn('Refresh inspect --ownership', result['tasks'][0]['required_follow_up'][1])
            self.assertIs(result['actions_authorized'], False)


class SessionJarSelectionTests(unittest.TestCase):
    plan = SessionTests.plan

    def mixed(self, state, peer_state, *, limit=None, welcomed_only=False):
        from tests.test_tipjar_discovery import SourcesGitHub
        class SourceURLs(SourcesGitHub):
            def request(self, endpoint):
                result = super().request(endpoint)
                if endpoint.startswith('repos/person/photos/issues?'):
                    return [dict(issue, html_url=f'https://github.com/person/photos/issues/{issue["number"]}')
                            for issue in result]
                return result
        states = {name: value for name, value in [('acme/photos', state), ('person/photos', peer_state)]
                  if value is not None}
        return multi.discover_many(['acme/photos', 'person/photos'], SourceURLs(states),
                                   limit=limit, welcomed_only=welcomed_only)

    def test_single_closed_unknown_and_welcome_filter_exclusions_receive_no_time(self):
        from tests.test_tipjar_discovery import SourcesGitHub
        for state, welcomed_only, reason in [('closed', False, 'source_jar_closed'),
                                              ('bad', False, 'source_jar_unknown'),
                                              (None, True, None)]:
            source = core.discover('acme/photos', SourcesGitHub({} if state is None else {'acme/photos': state}),
                                   welcomed_only=welcomed_only)
            self.assertFalse(source['selection']['included'])
            with self.subTest(state=state, welcomed_only=welcomed_only):
                result = self.plan(source)
                self.assertEqual(result['source_report'], source)
                self.assertEqual(result['tasks'], [])
                self.assertEqual(result['allocated_minutes'], 0)
                self.assertFalse(result['actions_authorized'])
                if reason:
                    self.assertIn(reason, result['candidates'][0]['reasons'])
                    self.assertFalse(result['candidates'][0]['selected'])
                else:
                    self.assertEqual(result['candidates'], [])

    def test_selection_rejection_is_honored_independently_of_welcome_state(self):
        from tests.test_tipjar_discovery import SourcesGitHub
        source = core.discover('acme/photos', SourcesGitHub({'acme/photos': 'welcome'}))
        source['selection'].update(included=False, reason='Excluded from this discovery selection')
        result = self.plan(source)
        self.assertEqual(result['tasks'], [])
        self.assertIn('source_selection_excluded', result['candidates'][0]['reasons'])
        self.assertEqual(result['source_report'], source)

    def test_single_explicit_welcome_and_undeclared_still_propose_manual_review(self):
        from tests.test_tipjar_discovery import SourcesGitHub
        for states in ({}, {'acme/photos': 'welcome'}):
            source = core.discover('acme/photos', SourcesGitHub(states))
            result = self.plan(source)
            self.assertEqual([task['reference'] for task in result['tasks']], ['acme/photos#12'])
            self.assertFalse(result['actions_authorized'])
            self.assertEqual(result['source_report'], source)

    def test_mixed_excluded_diagnostics_do_not_block_eligible_peers(self):
        for state, reason in [('closed', 'source_jar_closed'), ('bad', 'source_jar_unknown')]:
            for peer_state in ('welcome', None):
                for limit in (None, 1):
                    source = self.mixed(state, peer_state, limit=limit)
                    with self.subTest(state=state, peer=peer_state, limit=limit):
                        result = self.plan(source)
                        self.assertEqual(result['source_report'], source)
                        self.assertEqual([task['reference'] for task in result['tasks']], ['person/photos#12'])
                        self.assertFalse(result['actions_authorized'])
                        self.assertEqual(core.schema_errors(result, outputs.output_schema('session')), [])
                        for decision in result['candidates']:
                            if decision['reference'] == 'acme/photos#12':
                                self.assertFalse(decision['selected'])
                                self.assertIn(reason, decision['reasons'])
                                self.assertEqual(decision['source_repository_index'], 0)
                                self.assertEqual(decision['source_issue_index'], 0)
                        self.assertEqual(len(result['candidates']), sum(len(r['issues']) for r in source['repositories']))
                        self.assertEqual(result['tasks'][0]['source_repository_index'], 1)

    def test_mixed_welcome_and_nojar_controls_keep_candidate_order_and_filter(self):
        for peer_state in ('welcome', None):
            for welcomed_only in (False, True):
                for limit in (None, 1):
                    source = self.mixed('welcome', peer_state, limit=limit, welcomed_only=welcomed_only)
                    result = self.plan(source)
                    self.assertEqual([task['reference'] for task in result['tasks']],
                                     [candidate['reference'] for candidate in source['candidates']])
                    self.assertEqual(result['source_report'], source)

    def test_excluded_rows_do_not_weaken_candidate_or_detail_validation(self):
        source = self.mixed('closed', 'welcome')
        excluded = dict(source['candidates'][0], repository='acme/photos', reference='acme/photos#12')
        mutations = [lambda r: r['candidates'].clear(),
                     lambda r: r['candidates'].append(excluded),
                     lambda r: r['candidates'].append(copy.deepcopy(r['candidates'][0])),
                     lambda r: r['candidates'][0].update(overlapping=True),
                     lambda r: r['candidates'][0].update(reference='person/photos#99'),
                     lambda r: r['repositories'][0]['issues'][0].update(issue_url='https://evil.test/issues/12')]
        for mutate in mutations:
            forged = copy.deepcopy(source)
            mutate(forged)
            with self.subTest(mutation=mutate), self.assertRaises(core.ProtocolError):
                self.plan(forged)
