"""JSON result delivery must fail quietly when a pipe consumer disappears."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from agent_contribute import cli
from agent_contribute.cli import main
from tests import output_contract


class BrokenWrite(io.StringIO):
    def write(self, value):
        raise BrokenPipeError('consumer closed')


class BrokenFlush(io.StringIO):
    def flush(self):
        raise BrokenPipeError('consumer closed')


class WriteOnly:
    def __init__(self):
        self.parts = []

    def write(self, value):
        self.parts.append(value)
        return len(value)


class BrokenWriteOnly:
    def write(self, value):
        raise BrokenPipeError('consumer closed')


class OutputTests(unittest.TestCase):
    def test_failed_stderr_descriptor_never_changes_the_process_exit(self):
        """The --ai-policy notice is the CLI's only stderr write. A closed fd 2 or a pipe without a reader must
        not leave a failed buffered write for interpreter shutdown to retry, which would exit 120."""
        child = ('import os, sys\n'
                 'from unittest.mock import patch\n'
                 'from agent_contribute import cli, core\n'
                 'from tests.test_policy import FrozenClock, HostileGitHub\n'
                 'mode = sys.argv[1]\n'
                 'if mode == "closed":\n'
                 '    os.close(2)\n'
                 'elif mode in ("readerless", "block-buffered"):\n'
                 '    read, write = os.pipe(); os.close(read); os.dup2(write, 2); os.close(write)\n'
                 'if mode == "block-buffered":  # a host-installed stream that defers writes to its flush\n'
                 '    import io; sys.stderr = io.TextIOWrapper(io.BufferedWriter(io.FileIO(2, "w", closefd=False)))\n'
                 'with patch.object(core, "GitHub", return_value=HostileGitHub()), '
                 'patch.object(core.dt, "datetime", FrozenClock):\n'
                 '    code = cli.main(sys.argv[2:])\n'
                 'raise SystemExit(code)\n')
        root = Path(__file__).resolve().parents[1]

        def run(mode, *flags):
            return subprocess.run([sys.executable, '-c', child, mode, 'inspect', 'acme/photos#12', *flags],
                                  cwd=root, capture_output=True, timeout=30)
        reference = run('working')
        self.assertEqual((reference.returncode, reference.stderr), (0, b''), reference.stderr)
        self.assertTrue(json.loads(reference.stdout)['complete'])
        working = run('working', '--ai-policy')
        self.assertEqual(working.returncode, 0, working.stderr)
        self.assertEqual(working.stderr.decode(), cli.AI_POLICY_NOTICE + '\n')
        for mode in ('closed', 'readerless', 'block-buffered'):
            for flags in ((), ('--ai-policy',)):
                with self.subTest(mode=mode, flags=flags):
                    result = run(mode, *flags)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(json.loads(result.stdout), json.loads(reference.stdout))

    @output_contract.unchecked()
    def test_stderr_cleanup_failure_is_contained(self):
        class Unusable:
            closed = 0

            def write(self, value):
                raise OSError('stderr is gone')

            def close(self):
                self.closed += 1
                raise ValueError('I/O operation on closed file')
        for stream in (Unusable(), BrokenFlush(), object()):
            with self.subTest(stream=type(stream).__name__), patch('sys.stderr', stream), \
                    patch('agent_contribute.core.inspect_issue', return_value={'complete': False}):
                output = io.StringIO()
                with patch('sys.stdout', output):
                    self.assertEqual(main(['inspect', 'acme/photos#12', '--ai-policy']), 1)
                self.assertEqual(json.loads(output.getvalue()), {'complete': False})
                if isinstance(stream, Unusable):
                    self.assertEqual(stream.closed, 1)
                if isinstance(stream, BrokenFlush):
                    self.assertTrue(stream.closed, 'a stream whose flush failed is closed')

    def test_closed_stdout_descriptor_at_startup_is_quiet(self):
        bootstrap = ('import os, sys; os.close(1); '
                     'os.execv(sys.executable, '
                     '[sys.executable, "-m", "agent_contribute", *sys.argv[1:]])')
        for args in (['instructions'], ['unknown-command']):
            with self.subTest(args=args):
                result = subprocess.run([sys.executable, '-c', bootstrap, *args],
                                        capture_output=True, timeout=15)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(result.stdout, b'')
                self.assertEqual(result.stderr, b'')

    @output_contract.unchecked()
    def test_write_only_stdout_preserves_json_bytes_and_statuses(self):
        for complete, code, literal in ((True, 0, 'true'), (False, 1, 'false')):
            with self.subTest(complete=complete):
                output = WriteOnly()
                with patch('agent_contribute.core.discover', return_value={
                        'complete': complete, 'message': '\u00e9'}), patch('sys.stdout', output):
                    self.assertEqual(main(['discover', 'acme/project']), code)
                self.assertEqual(''.join(output.parts), '{\n  "complete": ' + literal +
                                 ',\n  "message": "\\u00e9"\n}\n')
        output = WriteOnly()
        with patch('sys.stdout', output):
            self.assertEqual(main(['unknown-command']), 2)
        self.assertEqual(json.loads(''.join(output.parts))['error']['code'], 'usage')

    def test_broken_write_only_stdout_without_close_returns_one(self):
        with patch('sys.stdout', BrokenWriteOnly()):
            self.assertEqual(main(['instructions']), 1)

    def test_immediate_write_failure_with_replaced_stdout_returns_one(self):
        with patch('sys.stdout', BrokenWrite()):
            try:
                code = main(['instructions'])
            except BrokenPipeError:
                self.fail('JSON write failure escaped main')
        self.assertEqual(code, 1)

    def test_flush_failure_with_replaced_stdout_returns_one(self):
        with patch('sys.stdout', BrokenFlush()):
            self.assertEqual(main(['instructions']), 1)

    def test_closed_pipe_is_quiet_for_large_and_buffered_module_results(self):
        for args in (['instructions'], ['unknown-command']):
            with self.subTest(args=args):
                reader, writer = os.pipe()
                os.close(reader)
                try:
                    result = subprocess.run(
                        [sys.executable, '-m', 'agent_contribute', *args],
                        stdout=writer, stderr=subprocess.PIPE, timeout=15)
                finally:
                    os.close(writer)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(result.stderr, b'')

    def test_buffered_pipe_flush_and_close_failure_do_not_escape_main(self):
        reader, writer = os.pipe()
        os.close(reader)
        stream = os.fdopen(writer, 'w')
        try:
            with patch('sys.stdout', stream):
                try:
                    code = main(['unknown-command'])
                except BrokenPipeError:
                    self.fail('JSON flush or cleanup failure escaped main')
            self.assertEqual(code, 1)
        finally:
            try:
                stream.close()
            except BrokenPipeError:
                pass

    @output_contract.unchecked()
    def test_writable_stringio_retains_json_bytes_and_read_statuses(self):
        for complete, code, literal in ((True, 0, 'true'), (False, 1, 'false')):
            with self.subTest(complete=complete):
                output = io.StringIO()
                with patch('agent_contribute.core.discover', return_value={
                        'complete': complete, 'message': '\u00e9'}), patch('sys.stdout', output):
                    self.assertEqual(main(['discover', 'acme/project']), code)
                self.assertEqual(output.getvalue(), '{\n  "complete": ' + literal +
                                 ',\n  "message": "\\u00e9"\n}\n')

    def test_writable_usage_error_retains_status_two(self):
        output = io.StringIO()
        with patch('sys.stdout', output):
            self.assertEqual(main(['unknown-command']), 2)
        self.assertEqual(json.loads(output.getvalue())['error']['code'], 'usage')

    def test_normal_redirected_file_retains_result_bytes(self):
        argv = [sys.executable, '-m', 'agent_contribute', 'instructions']
        expected = subprocess.run(argv, capture_output=True, timeout=15)
        self.assertEqual(expected.returncode, 0, expected.stderr)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, 'instructions.json')
            with path.open('wb') as output:
                result = subprocess.run(argv, stdout=output, stderr=subprocess.PIPE, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, b'')
            self.assertEqual(path.read_bytes(), expected.stdout)

    def test_unrelated_output_errors_still_propagate(self):
        with patch('sys.stdout', io.StringIO()) as output:
            with patch.object(output, 'write', side_effect=OSError('disk full')):
                with self.assertRaisesRegex(OSError, 'disk full'):
                    main(['instructions'])
