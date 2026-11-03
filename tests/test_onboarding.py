"""Offline maintainer setup uses the canonical parser and cannot clobber files."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent_contribute import cli, core, outputs, tipjar


def invoke(*args):
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout), patch.object(core, 'GitHub', side_effect=AssertionError('GitHub read')), \
            patch('subprocess.run', side_effect=AssertionError('subprocess executed')):
        code = cli.main(list(args))
    return code, json.loads(stdout.getvalue())


class OnboardingTests(unittest.TestCase):
    def test_explicit_states_create_valid_editable_templates_and_hash_exact_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            for state in ('welcome', 'closed'):
                path = Path(directory) / (state + '.json')
                code, result = invoke('init', '--status', state, '--output', str(path))
                self.assertEqual(code, 0, result)
                data = path.read_bytes()
                manifest = tipjar.parse_manifest(data)
                self.assertEqual(manifest['status'], state)
                self.assertTrue(manifest['wanted'])
                self.assertTrue(manifest['boundaries'])
                self.assertEqual(result['state'], state)
                self.assertEqual(result['output'], str(path))
                self.assertEqual(result['sha256'], hashlib.sha256(data).hexdigest())
                self.assertTrue(result['next_steps'])
                self.assertFalse(core.schema_errors(result, outputs.output_schema('init')))
                code, checked = invoke('jar-check', str(path))
                self.assertEqual(code, 0, checked)
                self.assertIs(checked['valid'], True)
                self.assertEqual(checked['state'], state)
                self.assertEqual(checked['sha256'], result['sha256'])
                self.assertFalse(core.schema_errors(checked, outputs.output_schema('jar-check')))

    def test_state_and_output_are_required_no_default_adoption(self):
        for args in [('init',), ('init', '--output', 'unused.json'), ('init', '--status', 'welcome'),
                     ('init', '--status', 'unknown', '--output', 'unused.json')]:
            code, result = invoke(*args)
            self.assertEqual(code, 2)
            self.assertEqual(result['error']['code'], 'usage')

    def test_init_never_overwrites_files_or_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'target'
            target.write_bytes(b'preserve')
            link = Path(directory) / 'link'
            link.symlink_to(target)
            dangling = Path(directory) / 'dangling'
            missing = Path(directory) / 'missing'
            dangling.symlink_to(missing)
            for path in (target, link, dangling):
                code, result = invoke('init', '--status', 'closed', '--output', str(path))
                self.assertEqual(code, 1)
                self.assertEqual(result['error']['code'], 'file_error')
            self.assertEqual(target.read_bytes(), b'preserve')
            self.assertFalse(missing.exists())

    def test_offline_commands_refuse_github_flags_before_touching_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'never-created'
            commands = [('init', '--status', 'welcome', '--output', str(path)), ('jar-check', str(path))]
            for command in commands:
                for flags in [('--cache',), ('--report-budget',), ('--min-remaining', '1'),
                              ('--report-budget', '--min-remaining', '1')]:
                    code, result = invoke(*flags, *command)
                    self.assertEqual(code, 2)
                    self.assertEqual(result['error']['code'], 'usage')
            self.assertFalse(path.exists())

    def test_check_rejects_invalid_input_without_echoing_secrets(self):
        secret = 'NEVER_ECHO_PRIVATE_CONTENT'
        cases = [b'\xff' + secret.encode(), ('{"secret":"' + secret + '"}').encode(),
                 b'{"schema_version":"9","status":"welcome"}',
                 b'{"schema_version":"0.1","status":"closed","status":"welcome"}',
                 b' ' * (tipjar.MAX_BYTES + 1)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'input'
            for raw in cases:
                path.write_bytes(raw)
                code, result = invoke('jar-check', str(path))
                self.assertEqual(code, 1)
                self.assertIn('error', result)
                self.assertNotIn(secret, json.dumps(result))
                self.assertFalse(core.schema_errors(result, outputs.output_schema('error')))
            for candidate in (Path(directory), Path(directory) / 'missing'):
                self.assertEqual(invoke('jar-check', str(candidate))[0], 1)
            link = Path(directory) / 'link'
            link.symlink_to(path)
            self.assertEqual(invoke('jar-check', str(link))[0], 1)
            if hasattr(os, 'mkfifo'):
                fifo = Path(directory) / 'fifo'
                os.mkfifo(fifo)
                self.assertEqual(invoke('jar-check', str(fifo))[0], 1)

    def test_check_hashes_original_bytes_and_does_not_echo_manifest_text(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'manifest'
            data = b'{ "schema_version": "0.1", "status":"closed", "boundaries":["PRIVATE"] }\r\n'
            path.write_bytes(data)
            code, result = invoke('jar-check', str(path))
            self.assertEqual(code, 0, result)
            self.assertEqual(result['sha256'], hashlib.sha256(data).hexdigest())
            self.assertNotIn('PRIVATE', json.dumps(result))
            self.assertEqual(path.read_bytes(), data)

    def test_text_output_shows_state_hash_and_next_steps(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'manifest'
            for command in [('init', '--status', 'closed', '--output', str(path)), ('jar-check', str(path))]:
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    code = cli.main(['--format', 'text', *command])
                self.assertEqual(code, 0, stdout.getvalue())
                self.assertIn('closed', stdout.getvalue())
                self.assertIn(hashlib.sha256(path.read_bytes()).hexdigest(), stdout.getvalue())
                self.assertIn('authority', stdout.getvalue())
                if command[0] == 'init':
                    self.assertIn('jar-check', stdout.getvalue())
