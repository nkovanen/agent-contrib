"""Real pipe regressions for bounded input; no project commands come from input."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from agent_contribute import core


READ = '''
import json
from agent_contribute import cli, core
cli.HOST_INPUT_TIMEOUT = 1.0
try:
    value = cli.read_host_context_stdin()
except core.ProtocolError as exc:
    print(json.dumps({'error': exc.code}))
    raise SystemExit(1)
print(json.dumps({'value': value}, ensure_ascii=True))
'''


class HostInputTransportTests(unittest.TestCase):
    def read(self, data, prefix=''):
        result = subprocess.run([sys.executable, '-c', prefix + READ], input=data,
                                capture_output=True, timeout=10)
        self.assertEqual(result.stderr, b'')
        return result.returncode, json.loads(result.stdout)

    def test_valid_utf8_pipe(self):
        self.assertEqual(self.read('{"note":"雪 café"}'.encode()),
                         (0, {'value': {'note': '雪 café'}}))

    @unittest.skipIf(os.name == 'nt', 'POSIX descriptor limit regression')
    def test_valid_pipe_with_descriptor_above_select_limit(self):
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        if hard != resource.RLIM_INFINITY and hard < 1101:
            self.skipTest('descriptor hard limit below select limit')
        prefix = ('import os,sys,resource; '
                  f'resource.setrlimit(resource.RLIMIT_NOFILE, ({max(soft, 1101)}, {hard})); '
                  'os.dup2(0, 1100); sys.stdin = os.fdopen(1100)\n')
        self.assertEqual(self.read(b'{"ok":true}', prefix),
                         (0, {'value': {'ok': True}}))

    def test_strict_input_rejects_empty_invalid_utf8_and_malformed_json(self):
        for data in (b'', b'\xff', b'{', b'{} trailing', b'{"x":1,"x":2}', b'NaN'):
            with self.subTest(data=data):
                code, result = self.read(data)
                self.assertEqual(code, 1)
                self.assertIn(result['error'], ('host_context_input', 'invalid_json'))

    def test_exact_bound_is_accepted_and_next_byte_is_rejected(self):
        accepted = b'"' + b'x' * (core.MAX_BYTES - 2) + b'"'
        code, result = self.read(accepted)
        self.assertEqual(code, 0)
        self.assertEqual(len(result['value']), core.MAX_BYTES - 2)
        self.assertEqual(self.read(accepted + b' '),
                         (1, {'error': 'host_context_input'}))

    def test_no_eof_times_out_for_empty_partial_and_complete_json(self):
        for data in (b'', b'{"pending":', b'{}'):
            with self.subTest(data=data):
                with subprocess.Popen([sys.executable, '-c', READ], stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
                    try:
                        proc.stdin.write(data)
                        proc.stdin.flush()
                        proc.wait(timeout=5)
                        self.assertEqual(proc.returncode, 1)
                        self.assertEqual(json.loads(proc.stdout.read()),
                                         {'error': 'host_context_input'})
                        self.assertEqual(proc.stderr.read(), b'')
                    finally:
                        if proc.poll() is None:
                            proc.kill()

    def test_closed_stdin_is_refused(self):
        for prefix in ('import sys; sys.stdin.close()\n', 'import sys; sys.stdin = None\n'):
            with self.subTest(prefix=prefix):
                self.assertEqual(self.read(b'', prefix),
                                 (1, {'error': 'host_context_input'}))

    def test_redirected_file_is_accepted(self):
        with tempfile.TemporaryFile() as stream:
            stream.write(b'{"file":true}')
            stream.seek(0)
            result = subprocess.run([sys.executable, '-c', READ], stdin=stream,
                                    capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout), {'value': {'file': True}})
        self.assertEqual(result.stderr, b'')

    @unittest.skipIf(os.name == 'nt', 'PTY regression requires POSIX')
    def test_real_terminal_is_refused(self):
        import pty
        master, slave = pty.openpty()
        try:
            result = subprocess.run([sys.executable, '-c', READ], stdin=slave,
                                    capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout), {'error': 'host_context_input'})
            self.assertEqual(result.stderr, b'')
        finally:
            os.close(master)
            os.close(slave)

    def test_repeated_timeouts_leave_no_reader_to_steal_later_input(self):
        code = '''
import os, sys
from pathlib import Path
from agent_contribute import cli, core
cli.HOST_INPUT_TIMEOUT = 0.1
for _ in range(3):
    try:
        cli.read_host_context_stdin()
    except core.ProtocolError as exc:
        assert exc.code == 'host_context_input'
    else:
        raise AssertionError('input accepted without EOF')
    if os.name != 'nt':
        try:
            os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            pass
        else:
            raise AssertionError('reader child was not reaped')
cli.HOST_INPUT_TIMEOUT = 3
Path(sys.argv[1]).touch()
assert cli.read_host_context_stdin() == {'later': True}
'''
        with tempfile.TemporaryDirectory() as tmp:
            ready = Path(tmp) / 'ready'
            with subprocess.Popen([sys.executable, '-c', code, str(ready)],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE) as proc:
                try:
                    deadline = time.monotonic() + 5
                    while not ready.exists() and proc.poll() is None and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertTrue(ready.exists(), 'timeout calls did not finish')
                    output, error = proc.communicate(b'{"later":true}', timeout=5)
                    self.assertEqual((proc.returncode, output, error), (0, b'', b''))
                finally:
                    if proc.poll() is None:
                        proc.kill()

    def test_input_is_data_and_does_not_execute(self):
        self.assertEqual(self.read(b'raise SystemExit(99)'),
                         (1, {'error': 'invalid_json'}))

    def test_reader_ignores_checkout_startup_hooks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sentinel = root / 'executed'
            (root / 'sitecustomize.py').write_text(
                f'from pathlib import Path; Path({str(sentinel)!r}).touch()', encoding='utf-8')
            # Change cwd/env only after the trusted parent has imported the CLI.
            prefix = ('import os; from agent_contribute import cli; '
                      f'os.chdir({tmp!r}); os.environ["PYTHONPATH"] = {tmp!r}\n')
            self.assertEqual(self.read(b'{}', prefix), (0, {'value': {}}))
            self.assertFalse(sentinel.exists())
