"""Checkout stat, mode and case settings cannot hide a change from the checkout gates (G-02/G-04, G-06, G-07)."""
import os
import pathlib
import tempfile
import time
import unittest

from agent_contribute import core, workspace
from tests.test_protocol import evidence_checkout, refresh_checkout_evidence

DIRTY = 'Current checkout is dirty or differs from evidence HEAD/tree'


class StatConfigTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = self.directory.name
        self.task, self.client, self.evidence, self.git = evidence_checkout(self.root)
        self.agents = pathlib.Path(self.root, 'AGENTS.md')

    def assert_change_seen(self):
        result = core.verify(self.task, self.evidence, self.root, self.client)
        self.assertIn(DIRTY, result['evidence_errors'])
        self.assertFalse(result['upstream_submission_ready'])
        scope = workspace.scope_check(self.task, self.root)
        self.assertIn('AGENTS.md', [v['path'] for v in scope['violations']])
        self.assertIs(workspace.evidence_skeleton(self.task, self.root, self.evidence['base_commit'])['worktree_clean'],
                      False)

    def test_relaxed_stat_settings_cannot_hide_a_same_size_edit(self):
        self.git('config', 'core.checkStat', 'minimal')
        self.git('config', 'core.trustctime', 'false')
        old = 978307200  # an mtime well before the index write, so the entry is not racily clean
        os.utime(self.agents, (old, old))
        self.git('update-index', '--refresh')
        time.sleep(1.1)  # Git compares ctime in whole seconds; the edit must land in a later second
        original = self.agents.read_text()
        self.agents.write_text(original.upper()[:len(original)])  # same size
        os.utime(self.agents, (old, old))
        self.assertEqual(self.git('-c', 'core.checkStat=minimal', '-c', 'core.trustctime=false',
                                  'status', '--porcelain'), '', 'precondition: Git hides it with these settings')
        self.assert_change_seen()

    def test_file_mode_false_cannot_hide_an_executable_bit(self):
        self.git('config', 'core.fileMode', 'false')
        self.agents.chmod(0o755)
        self.assertEqual(self.git('status', '--porcelain'), '', 'precondition: Git hides it with fileMode=false')
        self.assert_change_seen()

    def test_ignore_case_on_a_case_sensitive_filesystem_is_refused(self):
        self.assertFalse(pathlib.Path(self.root, '.GIT').exists(), 'this test needs a case-sensitive filesystem')
        self.git('config', 'core.ignoreCase', 'true')
        pathlib.Path(self.root, 'agents.md').write_text('case twin Git would hide')
        refusal = ('Checkout Git config sets core.ignorecase, which a read could run as a program or use to hide '
                   'changes; remove it or use a fresh clone')
        self.assertIn(refusal, core.verify(self.task, self.evidence, self.root, self.client)['evidence_errors'])
        self.assertEqual(workspace.scope_check(self.task, self.root)['errors'], [refusal])
        self.git('config', 'core.ignoreCase', 'false')
        self.assertIn('agents.md', workspace.scope_check(self.task, self.root)['changed_paths'])


    def test_symlinks_false_cannot_hide_a_symlink_replaced_by_a_file(self):
        # G-15: a tracked symlink replaced by a regular file holding the same target text.
        link = pathlib.Path(self.root, 'src', 'link')
        link.symlink_to('thumb.rs')
        self.git('add', 'src/link')
        self.git('commit', '-q', '-m', 'add symlink')
        refresh_checkout_evidence(self.evidence, self.git)
        self.assertTrue(core.verify(self.task, self.evidence, self.root, self.client)['evidence_valid'])
        self.git('config', 'core.symlinks', 'false')
        link.unlink()
        link.write_text('thumb.rs')
        self.assertEqual(self.git('status', '--porcelain'), '', 'precondition: Git hides the type change')
        self.assertIn(DIRTY, core.verify(self.task, self.evidence, self.root, self.client)['evidence_errors'])
        self.assertIn('src/link', workspace.scope_check(self.task, self.root)['changed_paths'])
        self.assertIs(workspace.evidence_skeleton(self.task, self.root, self.evidence['base_commit'])['worktree_clean'],
                      False)

    REFUSAL = ('Checkout Git config sets core.ignorecase, which a read could run as a program or use to hide '
               'changes; remove it or use a fresh clone')

    def test_symlinked_dot_git_cannot_fake_a_case_insensitive_filesystem(self):
        # G-13 / R1-17: .GIT -> .git made samefile() report a case-insensitive filesystem.
        pathlib.Path(self.root, '.GIT').symlink_to('.git')
        self.git('config', 'core.ignoreCase', 'true')
        pathlib.Path(self.root, 'agents.md').write_text('case twin Git would hide')
        self.assertIn(self.REFUSAL, core.verify(self.task, self.evidence, self.root, self.client)['evidence_errors'])
        self.assertEqual(workspace.scope_check(self.task, self.root)['errors'], [self.REFUSAL])
        with self.assertRaises(core.ProtocolError) as caught:
            workspace.evidence_skeleton(self.task, self.root, self.evidence['base_commit'])
        self.assertEqual(caught.exception.code, 'unsafe_git_config')

    def test_ignore_case_uses_gits_effective_boolean(self):
        # R1-18: an empty value and a true later overridden by false are both false to Git.
        config = pathlib.Path(self.root, '.git', 'config')
        for extra in ('[core]\n\tignoreCase =\n', '[core]\n\tignoreCase = true\n[core]\n\tignoreCase = off\n'):
            with self.subTest(extra=extra):
                original = config.read_text()
                config.write_text(original + extra)
                self.assertEqual(self.git('config', '--type=bool', '--get', 'core.ignorecase'), 'false')
                self.assertTrue(workspace.scope_check(self.task, self.root)['within_scope'])
                self.assertTrue(core.verify(self.task, self.evidence, self.root, self.client)['evidence_valid'])
                config.write_text(original)
        config.write_text(config.read_text() + '[core]\n\tignoreCase = yes\n')
        self.assertEqual(workspace.scope_check(self.task, self.root)['errors'], [self.REFUSAL])

if __name__ == '__main__':
    unittest.main()
