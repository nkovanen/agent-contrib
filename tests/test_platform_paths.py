"""Scope and containment decisions use literal POSIX repository paths on every OS (#25)."""
import ntpath
import tempfile
import unittest
from unittest.mock import patch

from agent_contribute import core
from tests.test_protocol import evidence_checkout

SCOPE = {'allowed_paths': ['src/**'], 'prohibited_paths': ['src/secret/**']}
CASES = {'src/thumb.rs': None, 'src\\evil.py': 'not in allowed_paths', 'C:/src/x.rs': 'not in allowed_paths',
         'C:src/x.rs': 'not in allowed_paths', 'SRC/thumb.rs': 'not in allowed_paths',
         '\\\\server\\src\\x': 'not in allowed_paths', 'src/secret/k': 'prohibited_paths: src/secret/**',
         'src/SECRET/k': None, 'src/secret\\k': None}


def decisions():
    return {v['path']: v['rule'] for v in core.scope_violations(SCOPE, list(CASES))}


class PlatformPathTests(unittest.TestCase):
    def test_backslash_drive_and_case_variants_are_never_normalized(self):
        # A backslash is a literal POSIX filename byte; normalizing it would let 'src\\evil' match src/**.
        expected = {path: rule for path, rule in CASES.items() if rule}
        self.assertEqual(decisions(), expected)

    def test_decisions_do_not_depend_on_host_path_semantics(self):
        with patch('fnmatch.os.path', ntpath), patch('os.path', ntpath):
            windows_like = decisions()
        self.assertEqual(windows_like, decisions())

    def test_windows_shaped_artifact_paths_never_validate(self):
        with tempfile.TemporaryDirectory() as tmp:
            task, client, evidence, _ = evidence_checkout(tmp)
            for path in ['C:foo', 'C:\\Windows\\win.ini', '..\\..\\outside', '\\\\server\\share\\x', '/etc/hosts',
                         'src/../../outside']:
                with self.subTest(path=path):
                    evidence['artifacts'] = [{'path': path, 'sha256': '0' * 64}]
                    errors = core.check_evidence(task, evidence, tmp, core.canonical_hash(task),
                                                 current_commit=task['source']['commit'], client=client)
                    self.assertTrue(any('artifact' in error.lower() for error in errors), errors)


if __name__ == '__main__':
    unittest.main()
