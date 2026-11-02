"""Text is opt-in presentation; JSON bytes and readiness exits remain canonical."""
import copy
import io
import json
import unittest
from unittest.mock import patch
from agent_contribute import cli
from tests.test_cli_output import BrokenFlush
from tests.test_multi_discover import MultiGitHub


class TextCliTests(unittest.TestCase):
    def invoke(self, args):
        output = io.StringIO()
        with patch('sys.stdout', output):
            code = cli.main(args)
        return code, output.getvalue()

    def test_default_and_explicit_json_are_byte_identical(self):
        result = {'complete': True, 'issues': [], 'message': '\u00e9'}
        with patch('agent_contribute.core.discover', return_value=result):
            default = self.invoke(['discover', 'acme/photos'])
            explicit = self.invoke(['--format', 'json', 'discover', 'acme/photos'])
        self.assertEqual(default, explicit)
        self.assertEqual(default, (0, json.dumps(result, indent=2, ensure_ascii=True) + '\n'))

    def test_text_retains_incomplete_exit_and_sanitizes_remote_lines(self):
        result = {'complete': False, 'issues': [], 'errors': ['bad\ncomplete: yes\x1b[2K']}
        with patch('agent_contribute.core.discover', return_value=result):
            code, output = self.invoke(['--format', 'text', 'discover', 'acme/photos'])
        self.assertEqual(code, 1)
        self.assertIn('Complete: no', output)
        self.assertIn('Errors (1):', output)
        self.assertNotIn('\ncomplete: yes', output)
        self.assertNotIn('\x1b', output)

    def test_text_verify_keeps_gates_and_exit(self):
        result = {'schema_valid': True, 'execution_ready': True, 'evidence_valid': False,
                  'upstream_submission_ready': False, 'fork_completion_ready': False,
                  'errors': [], 'evidence_errors': ['No real run']}
        with patch('agent_contribute.core.read_json', return_value={'schema_version': '0.1'}), \
                patch('agent_contribute.core.verify', return_value=result):
            code, output = self.invoke(['--format', 'text', 'verify', 'task.json'])
        self.assertEqual(code, 1)
        self.assertIn('  execution_ready: yes', output)
        self.assertIn('  evidence_valid: no', output)
        self.assertIn('No real run', output)

    def test_text_verify_stage_leads_with_that_stage_and_collapses_others(self):
        result = {'schema_valid': True, 'implementation_ready': False, 'technical_evidence_valid': False,
                  'draft_create_ready': False, 'completion_ready': False,
                  'publication': {'verified': True}, 'next_action': 'none',
                  'stage_blockers': {'implementation': ['Current implement action is not authorized'],
                                     'draft': ['Both implement and create_draft actions must be authorized'],
                                     'completion': ['Final human signoff is pending or invalid', 'Second']},
                  'errors': []}

        def invoke(*args):
            with patch('agent_contribute.core.read_json', return_value={'schema_version': '0.2'}), \
                    patch('agent_contribute.core.verify', return_value=copy.deepcopy(result)):
                return self.invoke(list(args))
        code, output = invoke('--format', 'text', 'verify', 'task.json', '--stage', 'implementation')
        self.assertEqual(code, 1)
        self.assertTrue(output.startswith('Selected stage: implementation (exit gate: no)\n'
                                          'Blockers [implementation] (1):\n'
                                          '  - Current implement action is not authorized\nGates:\n'), output)
        self.assertNotIn('create_draft actions', output)
        self.assertNotIn('Final human signoff', output)
        self.assertNotIn('Blockers [draft]', output)
        self.assertIn('Other stages (not required by --stage implementation; lists in JSON): '
                      'draft 1 blocker(s), completion 2 blocker(s)\n', output)
        code, output = invoke('--format', 'text', 'verify', 'task.json', '--stage', 'draft')
        self.assertEqual(code, 0)
        self.assertTrue(output.startswith('Selected stage: draft (exit gate: yes)\n'
                                          'Blockers [draft] (1):\n'), output)
        self.assertIn('implementation 1 blocker(s), completion 2 blocker(s)', output)
        self.assertEqual(invoke('verify', 'task.json', '--stage', 'implementation'),
                         (1, json.dumps(result, indent=2, ensure_ascii=True) + '\n'))
        code, output = invoke('--format', 'text', 'verify', 'task.json')
        self.assertEqual(code, 1)
        self.assertTrue(output.startswith('Gates:\n'), output)
        self.assertIn('Blockers [draft] (1):', output)
        self.assertNotIn('Selected stage', output)

    def test_text_scope_check_and_drift_keep_exit_status(self):
        scope = {'within_scope': False, 'base_commit': 'a' * 40, 'changed_paths': ['x'], 'errors': [], 'warnings': [],
                 'violations': [{'path': 'x', 'rule': 'not in allowed_paths'}]}
        drift = {'complete': True, 'drifted': True, 'errors': [], 'issue': {'changed': True}}
        # prevalidate always checks the drift contract (A1-11); the stub contract is declared valid here.
        with patch('agent_contribute.core.read_json', return_value={}), \
                patch('agent_contribute.core.validate_contract', return_value=[]), \
                patch('agent_contribute.workspace.scope_check', return_value=scope), \
                patch('agent_contribute.drift.drift', return_value=drift):
            code, output = self.invoke(['--format', 'text', 'scope-check', 'task.json', '--repo-dir', '.'])
            self.assertEqual(code, 1)
            self.assertIn('Violations (1):\n  - x -- not in allowed_paths\n', output)
            code, output = self.invoke(['--format', 'text', 'drift', 'task.json'])
            self.assertEqual(code, 1)
            self.assertIn('Drift reasons (1):\n  - Issue content changed\n', output)

    def test_text_multi_repo_does_not_hide_failed_repository(self):
        result = {'complete': False, 'repositories': [
            {'requested_repository': 'acme/a', 'complete': True, 'issues': [], 'errors': []},
            {'requested_repository': 'acme/b', 'complete': False, 'issues': [], 'errors': ['Denied']}],
            'candidates': [], 'errors': ['acme/b: Denied']}
        with patch('agent_contribute.multi.discover_many', return_value=result):
            code, output = self.invoke(['--format', 'text', 'discover', 'acme/a', 'acme/b'])
        self.assertEqual(code, 1)
        self.assertIn('Repository: acme/a', output)
        self.assertIn('Repository: acme/b', output)
        self.assertIn('Denied', output)

    def test_real_fork_discovery_keeps_requested_source_and_target_distinct(self):
        with patch('agent_contribute.core.GitHub', return_value=MultiGitHub()):
            code, output = self.invoke(['--format', 'text', 'discover', 'acme/photos', 'person/photos'])
        self.assertEqual(code, 0)
        self.assertIn('Repository: person/photos\n', output)
        self.assertIn('Issue source: acme/photos\n', output)
        self.assertIn('Proposed target (not authority): person/photos\n', output)
        self.assertIn('  person/photos#12 [', output)
        self.assertIn('  acme/photos#12 [', output)

    def test_bad_format_is_structured_usage_and_text_bad_command_is_safe(self):
        code, output = self.invoke(['--format', 'xml', 'instructions'])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output)['error']['code'], 'usage')
        code, output = self.invoke(['--format', 'text', 'unknown-command'])
        self.assertEqual(code, 2)
        self.assertIn('usage', output)

    def test_text_broken_flush_and_missing_stdout_are_quiet(self):
        for stream in (BrokenFlush(), None):
            with self.subTest(stream=stream), patch('sys.stdout', stream):
                self.assertEqual(cli.main(['--format', 'text', 'instructions']), 1)
