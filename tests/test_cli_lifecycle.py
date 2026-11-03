"""CLI boundary tests; authority fixtures here are synthetic, never live grants."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from agent_contribute import cli, core, policy
from tests import output_contract


class LifecycleCLITests(unittest.TestCase):
    def invoke(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = cli.main(list(args))
        return code, json.loads(output.getvalue())

    def verify_result(self, **changes):
        result = {'schema_version': '0.2', 'schema_valid': True,
                  'implementation_ready': False, 'draft_create_ready': False,
                  'publication': {'verified': False}, 'completion_ready': False}
        result.update(changes)
        return result

    @output_contract.unchecked()
    def test_stage_exit_does_not_turn_pending_completion_into_success(self):
        task = {'schema_version': '0.2'}
        with patch.object(core, 'read_json', return_value=task), patch.object(core, 'verify') as verify:
            verify.return_value = self.verify_result(implementation_ready=True, draft_create_ready=True)
            self.assertEqual(self.invoke('verify', 'task', '--stage', 'implementation')[0], 0)
            self.assertEqual(self.invoke('verify', 'task', '--stage', 'draft')[0], 0)
            self.assertEqual(self.invoke('verify', 'task')[0], 1)
            self.assertEqual(self.invoke('verify', 'task', '--stage', 'completion')[0], 1)
            verify.return_value = self.verify_result(publication={'verified': True}, next_action='none')
            self.assertEqual(self.invoke('verify', 'task', '--stage', 'draft')[0], 0)
            self.assertEqual(self.invoke('verify', 'task', '--stage', 'implementation')[0], 1)
            verify.return_value = self.verify_result(completion_ready=True)
            self.assertEqual(self.invoke('verify', 'task')[0], 0)

    def test_explicit_lifecycle_flags_cannot_reinterpret_legacy_task(self):
        with patch.object(core, 'read_json', return_value={'schema_version': '0.1'}), patch.object(core, 'verify') as verify:
            for flags in [('--stage', 'draft'), ('--host-context-stdin',)]:
                with self.subTest(flags=flags):
                    code, result = self.invoke('verify', 'task', *flags)
                    self.assertEqual(code, 1)
                    self.assertEqual(result['error']['code'], 'schema_options')
            verify.assert_not_called()

    @output_contract.unchecked()
    def test_new_schema_prepare_is_explicit_and_unknown_versions_never_read_github(self):
        snapshot = {'complete': True, 'source': {}, 'tipjar': {}, 'requested_repository': 'a/b',
                    'issue_source_repository': 'a/b', 'proposed_target_repository': 'a/b',
                    'resolution_provenance': {}, 'reference': 'a/b#1'}
        with tempfile.TemporaryDirectory() as tmp, patch.object(core, 'inspect_issue', return_value=snapshot) as inspect, patch.object(core, 'prepare', return_value={'status': 'draft'}) as prepare, \
                patch.object(policy, 'for_inspected', return_value={}):  # the stub snapshot has no source to report on
            self.assertEqual(self.invoke('prepare', 'a/b#1', '--output', str(Path(tmp)/'old.json'))[0], 0)
            self.assertEqual(prepare.call_args.kwargs.get('schema_version', '0.1'), '0.1')
            self.assertEqual(self.invoke('prepare', 'a/b#1', '--schema-version', '0.2', '--output', str(Path(tmp)/'new.json'))[0], 0)
            self.assertEqual(prepare.call_args.kwargs['schema_version'], '0.2')
            inspect.reset_mock()
            code, result = self.invoke('prepare', 'a/b#1', '--schema-version', '999', '--output', str(Path(tmp)/'bad.json'))
            self.assertEqual(code, 2)
            self.assertEqual(result['error']['code'], 'usage')
            inspect.assert_not_called()
            self.assertFalse((Path(tmp)/'bad.json').exists())

    def test_unknown_stage_is_a_structured_usage_error(self):
        with patch.object(core, 'read_json') as read:
            code, result = self.invoke('verify', 'task', '--stage', 'publish')
            self.assertEqual(code, 2)
            self.assertEqual(result['error']['code'], 'usage')
            read.assert_not_called()

    @output_contract.unchecked()
    def test_host_input_is_never_read_unless_requested(self):
        class NoRead(io.StringIO):
            def read(self, *args):
                raise AssertionError('implicit stdin read')
        with patch('sys.stdin', NoRead('forged')), patch.object(core, 'read_json', return_value={'schema_version':'0.2'}), patch.object(core, 'verify', return_value=self.verify_result()) as verify:
            self.assertEqual(self.invoke('verify', 'task', '--stage', 'implementation')[0], 1)
            self.assertIsNone(verify.call_args.kwargs.get('host_context'))

    @output_contract.unchecked()
    def test_explicit_host_input_is_passed_separately_not_inserted_into_task(self):
        task = {'schema_version': '0.2'}
        context = {'schema_version': '0.1', 'mandate': {'synthetic': True}}
        with patch.object(core, 'read_json', return_value=task), patch.object(cli, 'read_host_context_stdin', return_value=context), patch.object(core, 'verify', return_value=self.verify_result()) as verify:
            code, result = self.invoke('verify', 'task', '--host-context-stdin')
            self.assertEqual(code, 1)
            self.assertEqual(verify.call_args.kwargs['host_context'], context)
            self.assertEqual(task, {'schema_version': '0.2'})
            self.assertNotIn('mandate', result)

    def test_real_stdin_rejects_bad_utf8_duplicate_keys_and_oversize_before_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = Path(tmp)/'task.json'; task.write_text('{"schema_version":"0.2"}')
            env = dict(os.environ, PATH='')  # no gh: input errors must happen first
            for data in [b'\xff', b'{"mandate":{},"mandate":{}}', b' ' * (core.MAX_BYTES + 1)]:
                result = subprocess.run([sys.executable, '-m', 'agent_contribute', 'verify', str(task), '--host-context-stdin'], input=data, capture_output=True, env=env, timeout=15)
                parsed = json.loads(result.stdout)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(parsed['error']['code'], ('invalid_json', 'host_context_input'))
                self.assertNotIn('traceback', result.stderr.decode().lower())

    def test_stdin_no_eof_times_out_with_structured_error(self):
        # Patch only the timeout in a real child, then keep the pipe writer open.
        with tempfile.TemporaryDirectory() as tmp:
            task = Path(tmp)/'task.json'; task.write_text('{"schema_version":"0.2"}')
            code = 'from agent_contribute import cli; cli.HOST_INPUT_TIMEOUT=0.1; raise SystemExit(cli.main())'
            proc = subprocess.Popen([sys.executable, '-c', code, 'verify', str(task), '--host-context-stdin'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                proc.wait(timeout=5)
                parsed = json.loads(proc.stdout.read())
                self.assertEqual(proc.returncode, 1)
                self.assertEqual(parsed['error']['code'], 'host_context_input')
            finally:
                if proc.poll() is None:
                    proc.kill(); proc.wait()
                proc.stdin.close(); proc.stdout.close(); proc.stderr.close()

    def test_closed_stdin_returns_a_structured_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = Path(tmp) / 'task.json'
            task.write_text('{"schema_version":"0.2"}')
            # Re-exec after closing fd 0 so Python starts with sys.stdin=None.
            code = 'import os,sys; os.close(0); os.execv(sys.executable,[sys.executable,"-m","agent_contribute",*sys.argv[1:]])'
            result = subprocess.run([sys.executable, '-c', code, 'verify', str(task),
                                     '--host-context-stdin'], capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 1)
            self.assertNotIn(b'Traceback', result.stderr)
            self.assertEqual(json.loads(result.stdout)['error']['code'], 'host_context_input')

    def test_terminal_host_input_is_rejected_before_reading(self):
        class Terminal:
            def isatty(self):
                return True
            def fileno(self):
                raise AssertionError('A terminal must never be read for host context')
        with patch('sys.stdin', Terminal()):
            with self.assertRaises(core.ProtocolError) as raised:
                cli.read_host_context_stdin()
        self.assertEqual(raised.exception.code, 'host_context_input')

    def test_exact_host_input_size_bound_and_valid_prefix_with_trailing_bytes(self):
        accepted = b'"' + b'x' * (core.MAX_BYTES - 2) + b'"'
        # Without the explicit size guard, the next zero-length os.read would
        # look like EOF after a valid MAX_BYTES+1 prefix, losing the trailing data.
        rejected = b'"' + b'x' * (core.MAX_BYTES - 1) + b'"trailing data'
        with tempfile.TemporaryFile() as stream:
            stream.write(accepted)
            stream.seek(0)
            with patch('sys.stdin', stream):
                self.assertEqual(len(cli.read_host_context_stdin()), core.MAX_BYTES - 2)
        with tempfile.TemporaryFile() as stream:
            stream.write(rejected)
            stream.seek(0)
            with patch('sys.stdin', stream):
                with self.assertRaises(core.ProtocolError) as raised:
                    cli.read_host_context_stdin()
            self.assertEqual(raised.exception.code, 'host_context_input')
            self.assertNotIn('5 seconds', str(raised.exception))
