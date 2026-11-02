"""HEAD is captured once by exact lookup; a refs/tags/HEAD shadow can never stand in for it (R4-05)."""
import pathlib
import tempfile
import unittest

from agent_contribute import core, workspace
from tests import test_lifecycle
from tests.test_protocol import evidence_checkout

UNBORN = 'Checkout HEAD is unborn or not a commit; commit on a branch first'


def shadow_unborn_head(git):
    """Delete the current branch and leave a tag named HEAD at the tested commit."""
    head, branch = git('rev-parse', 'HEAD'), git('symbolic-ref', 'HEAD')
    git('update-ref', 'refs/tags/HEAD', head)
    git('update-ref', '-d', branch)
    return head


class LegacyHeadCaptureTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = self.directory.name
        self.task, self.client, self.evidence, self.git = evidence_checkout(self.root)

    def test_verify_rejects_unborn_head_shadowed_by_a_tag(self):
        self.assertTrue(core.verify(self.task, self.evidence, self.root, self.client)['evidence_valid'])
        shadow_unborn_head(self.git)
        result = core.verify(self.task, self.evidence, self.root, self.client)
        self.assertFalse(result['upstream_submission_ready'])
        self.assertFalse(result['evidence_valid'])
        self.assertIn(UNBORN, result['evidence_errors'])

    def test_scope_check_rejects_unborn_head_shadowed_by_a_tag(self):
        shadow_unborn_head(self.git)
        result = workspace.scope_check(self.task, self.root)
        self.assertFalse(result['within_scope'])
        self.assertEqual(result['errors'], [UNBORN])

    def test_evidence_init_rejects_unborn_head_shadowed_by_a_tag(self):
        shadow_unborn_head(self.git)
        with self.assertRaises(core.ProtocolError) as caught:
            workspace.evidence_skeleton(self.task, self.root, self.evidence['base_commit'])
        self.assertEqual((caught.exception.code, str(caught.exception)), ('unborn_head', UNBORN))

    def test_detached_head_naming_a_tag_object_is_refused(self):
        # show-ref accepts any object in .git/HEAD; evidence must name the commit itself.
        self.git('tag', '-a', '-m', 'annotated', 'v-head')
        pathlib.Path(self.root, '.git', 'HEAD').write_text(self.git('rev-parse', 'v-head') + '\n')
        with self.assertRaises(core.ProtocolError) as caught:
            workspace.evidence_skeleton(self.task, self.root, self.evidence['base_commit'])
        self.assertEqual(caught.exception.code, 'unborn_head')
        self.assertIn(UNBORN, core.verify(self.task, self.evidence, self.root, self.client)['evidence_errors'])

    def test_a_tag_named_head_never_replaces_a_real_branch_head(self):
        # Control: with a real branch, a HEAD tag at another commit is ignored everywhere.
        self.git('update-ref', 'refs/tags/HEAD', self.evidence['base_commit'])
        self.assertEqual(core.current_head(self.root), self.evidence['git_head'])
        self.assertTrue(core.verify(self.task, self.evidence, self.root, self.client)['evidence_valid'])
        self.assertTrue(workspace.scope_check(self.task, self.root)['within_scope'])
        skeleton = workspace.evidence_skeleton(self.task, self.root, self.evidence['base_commit'])
        self.assertEqual((skeleton['git_head'], skeleton['git_tree']), (self.evidence['git_head'], self.evidence['git_tree']))


class CandidateHeadCaptureTests(unittest.TestCase):
    setUp = test_lifecycle.LifecycleTests.setUp
    verify = test_lifecycle.LifecycleTests.verify

    def test_schema_02_rejects_unborn_head_shadowed_by_a_tag(self):
        self.assertTrue(self.verify()['draft_create_ready'])
        shadow_unborn_head(self.git)
        result = self.verify()
        self.assertFalse(result['draft_create_ready'])
        self.assertFalse(result['technical_evidence_valid'])
        self.assertIn(UNBORN, result['evidence_errors'])


if __name__ == '__main__':
    unittest.main()
