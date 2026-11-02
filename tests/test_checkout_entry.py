"""The shared checkout entry (core.open_checkout) and dirty check keep their order and the captured HEAD (SE-01)."""
import contextlib
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from agent_contribute import core, workspace
from tests.test_protocol import evidence_checkout

ENTRY = ['require_worktree_root', 'require_safe_config', 'require_plain_index', 'current_head']
ROOT_FAULT = '--repo-dir must be the Git worktree top level'


class EntryOrderTests(unittest.TestCase):
    def test_guards_run_in_order_and_the_first_failure_stops_the_rest(self):
        for failing in [None] + ENTRY:
            seen = []
            with self.subTest(failing=failing), contextlib.ExitStack() as stack:
                for name in ENTRY:
                    def guard(directory, name=name):
                        seen.append(name)
                        if name == failing:
                            raise core.ProtocolError('synthetic', name)
                        return 'a' * 40 if name == 'current_head' else None
                    stack.enter_context(patch.object(core, name, side_effect=guard))
                if failing is None:
                    self.assertEqual(core.open_checkout('/synthetic'), 'a' * 40)
                else:
                    with self.assertRaises(core.ProtocolError):
                        core.open_checkout('/synthetic')
                self.assertEqual(seen, ENTRY if failing is None else ENTRY[:ENTRY.index(failing) + 1])

    def test_a_subdirectory_with_unsafe_config_reports_the_root_fault_first_in_every_reader(self):
        # No config is read from a directory that is not the worktree root.
        with tempfile.TemporaryDirectory() as tmp:
            task, client, evidence, git = evidence_checkout(tmp)
            git('config', 'filter.evil.clean', 'cat')
            subdirectory = str(pathlib.Path(tmp, 'src'))
            with self.assertRaises(core.ProtocolError) as raised:
                core.open_checkout(subdirectory)
            self.assertEqual(raised.exception.code, 'not_worktree_root')
            with self.assertRaises(core.ProtocolError) as raised:
                core.open_checkout(tmp)
            self.assertEqual(raised.exception.code, 'unsafe_git_config')
            self.assertTrue(any(ROOT_FAULT in error for error in workspace.scope_check(task, subdirectory)['errors']))
            with self.assertRaises(core.ProtocolError) as raised:
                workspace.evidence_skeleton(task, subdirectory, evidence['base_commit'])
            self.assertEqual(raised.exception.code, 'not_worktree_root')
            errors = core.check_evidence(task, evidence, subdirectory, core.canonical_hash(task),
                                         current_commit=task['source']['commit'], client=client)
            self.assertTrue(any(ROOT_FAULT in error for error in errors), errors)
            self.assertFalse(any('filter.evil.clean' in error for error in errors), errors)


class CapturedHeadTests(unittest.TestCase):
    def test_head_moving_after_capture_is_rejected(self):
        """The dirty check compares content against the captured object ID, never a re-resolved HEAD."""
        with tempfile.TemporaryDirectory() as tmp:
            task, client, evidence, git = evidence_checkout(tmp)
            captured = evidence['git_head']
            pathlib.Path(tmp, 'AGENTS.md').write_text('different instructions in another revision')
            git('add', '.')
            git('commit', '-q', '-m', 'other revision')
            other = git('rev-parse', 'HEAD')
            git('checkout', '-q', '--detach', captured)
            real, moved = core.git_read, []

            def read(directory, *args, **kwargs):
                if args[:2] == ('status', '--porcelain') and not moved:  # after HEAD and tree were captured
                    subprocess.run(['git', '-C', tmp, 'checkout', '-q', '--detach', other], check=True)
                    moved.append(other)
                return real(directory, *args, **kwargs)
            with patch.object(core, 'git_read', side_effect=read):
                errors = core.check_evidence(task, evidence, tmp, core.canonical_hash(task),
                                             current_commit=task['source']['commit'], client=client)
            self.assertEqual(moved, [other])
            self.assertIn('Current checkout is dirty or differs from evidence HEAD/tree', errors)


if __name__ == '__main__':
    unittest.main()
