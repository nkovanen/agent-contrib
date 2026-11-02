"""Checkout stat, mode and case settings cannot hide a change from the checkout gates (G-02/G-04, G-06, G-07)."""
import os
import pathlib
import tempfile
import time
import unittest

from agent_contribute import core, workspace
from tests.test_protocol import evidence_checkout

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


if __name__ == '__main__':
    unittest.main()
