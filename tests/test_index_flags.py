"""Index flags that hide tracked changes fail every checkout gate closed (R1-14). The index is never modified."""
import pathlib
import tempfile
import unittest

from agent_contribute import core, workspace
from tests import test_lifecycle
from tests.test_protocol import evidence_checkout

HIDDEN = ('Index hides tracked paths (assume-unchanged, skip-worktree or sparse checkout); '
          'use a full checkout without these flags')
FLAGS = {'assume-unchanged': ('--assume-unchanged',), 'skip-worktree': ('--skip-worktree',),
         'both': ('--assume-unchanged', '--skip-worktree')}


def hide_modified_file(root, git, flags):
    """AGENTS.md is outside src/** scope; mark it, then change it on disk."""
    git('update-index', *flags, 'AGENTS.md')
    pathlib.Path(root, 'AGENTS.md').write_text('changed after the evidence commit')
    assert git('status', '--porcelain') == '', 'precondition: Git status hides the change'
    return git('ls-files', '-v', 'AGENTS.md')


def restore(git):
    git('update-index', '--no-assume-unchanged', 'AGENTS.md')
    git('update-index', '--no-skip-worktree', 'AGENTS.md')


class LegacyIndexFlagTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = self.directory.name
        self.task, self.client, self.evidence, self.git = evidence_checkout(self.root)

    def test_hidden_modified_tracked_file_fails_every_gate_without_touching_the_index(self):
        for name, flags in FLAGS.items():
            with self.subTest(flags=name):
                tagged = hide_modified_file(self.root, self.git, flags)
                result = core.verify(self.task, self.evidence, self.root, self.client)
                self.assertFalse(result['upstream_submission_ready'])
                self.assertFalse(result['evidence_valid'])
                self.assertIn(HIDDEN, result['evidence_errors'])
                scope = workspace.scope_check(self.task, self.root)
                self.assertFalse(scope['within_scope'])
                self.assertEqual(scope['errors'], [HIDDEN])
                with self.assertRaises(core.ProtocolError) as caught:
                    workspace.evidence_skeleton(self.task, self.root, self.evidence['base_commit'])
                self.assertEqual((caught.exception.code, str(caught.exception)), ('index_flags', HIDDEN))
                self.assertEqual(self.git('ls-files', '-v', 'AGENTS.md'), tagged, 'the index must not be modified')
                restore(self.git)
                self.git('checkout', '--', 'AGENTS.md')

    def test_sparse_checkout_is_refused(self):
        self.git('sparse-checkout', 'set', '--no-cone', '/src/')
        self.assertFalse(pathlib.Path(self.root, 'AGENTS.md').exists())
        self.assertIn(HIDDEN, core.verify(self.task, self.evidence, self.root, self.client)['evidence_errors'])
        self.assertEqual(workspace.scope_check(self.task, self.root)['errors'], [HIDDEN])

    def test_plain_index_still_passes(self):
        self.assertTrue(core.verify(self.task, self.evidence, self.root, self.client)['evidence_valid'])
        self.assertTrue(workspace.scope_check(self.task, self.root)['within_scope'])


class CandidateIndexFlagTests(unittest.TestCase):
    setUp = test_lifecycle.LifecycleTests.setUp
    verify = test_lifecycle.LifecycleTests.verify

    def test_schema_02_hidden_modified_tracked_file_blocks_draft(self):
        self.assertTrue(self.verify()['draft_create_ready'])
        for name, flags in FLAGS.items():
            with self.subTest(flags=name):
                hide_modified_file(self.directory.name, self.git, flags)
                result = self.verify()
                self.assertFalse(result['draft_create_ready'])
                self.assertFalse(result['technical_evidence_valid'])
                self.assertIn(HIDDEN, result['evidence_errors'])
                restore(self.git)
                self.git('checkout', '--', 'AGENTS.md')


if __name__ == '__main__':
    unittest.main()
