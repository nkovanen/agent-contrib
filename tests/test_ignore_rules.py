"""Only ignore rules a commit can carry hide untracked files (G-03); committed .gitignore still applies (G-11)."""
import pathlib
import subprocess
import tempfile
import unittest

from agent_contribute import core, workspace
from tests.test_protocol import evidence_checkout, refresh_checkout_evidence

DIRTY = 'Current checkout is dirty or differs from evidence HEAD/tree'


class IgnoreRuleTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = self.directory.name
        self.task, self.client, self.evidence, self.git = evidence_checkout(self.root)
        pathlib.Path(self.root, '.github').mkdir()
        pathlib.Path(self.root, '.github', 'evil.yml').write_text('untracked, out of scope')

    def assert_seen(self, *paths):
        result = core.verify(self.task, self.evidence, self.root, self.client)
        self.assertIn(DIRTY, result['evidence_errors'])
        scope = workspace.scope_check(self.task, self.root)
        self.assertTrue(set(paths) <= {v['path'] for v in scope['violations']}, scope)
        self.assertIs(workspace.evidence_skeleton(self.task, self.root, self.evidence['base_commit'])['worktree_clean'],
                      False)

    def test_info_exclude_cannot_hide_an_untracked_file(self):
        pathlib.Path(self.root, '.git', 'info').mkdir(exist_ok=True)
        pathlib.Path(self.root, '.git', 'info', 'exclude').write_text('.github/\n')
        self.assertEqual(self.git('status', '--porcelain'), '', 'precondition: status hides it')
        self.assert_seen('.github/evil.yml')

    def test_local_excludes_file_cannot_hide_an_untracked_file(self):
        excludes = pathlib.Path(self.root, '.git', 'local-excludes')
        excludes.write_text('.github/\n')
        self.git('config', 'core.excludesFile', str(excludes))
        self.assertEqual(self.git('status', '--porcelain'), '', 'precondition: status hides it')
        self.assert_seen('.github/evil.yml')

    def test_untracked_self_ignoring_gitignore_cannot_hide_itself(self):
        pathlib.Path(self.root, '.github', '.gitignore').write_text('*\n')
        self.assertEqual(self.git('status', '--porcelain'), '', 'precondition: status hides both')
        self.assert_seen('.github/.gitignore')

    def test_committed_gitignore_still_applies(self):
        pathlib.Path(self.root, '.github', 'evil.yml').unlink()
        pathlib.Path(self.root, '.github').rmdir()
        pathlib.Path(self.root, 'src', '.gitignore').write_text('build/\n')
        self.git('add', 'src/.gitignore')
        self.git('commit', '-q', '-m', 'ignore build output')
        refresh_checkout_evidence(self.evidence, self.git)
        pathlib.Path(self.root, 'src', 'build').mkdir()
        pathlib.Path(self.root, 'src', 'build', 'out.o').write_text('build output')
        self.assertTrue(core.verify(self.task, self.evidence, self.root, self.client)['evidence_valid'])
        scope = workspace.scope_check(self.task, self.root)
        self.assertTrue(scope['within_scope'], scope)
        self.assertNotIn('src/build/out.o', scope['changed_paths'])


if __name__ == '__main__':
    unittest.main()
