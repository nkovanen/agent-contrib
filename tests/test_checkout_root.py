"""--repo-dir must be the worktree top level: tree, index and untracked reads are relative to it (R1-01)."""
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from agent_contribute import core, workspace
from tests.test_authorization import host_context
from tests import test_lifecycle
from tests.test_protocol import evidence_checkout, refresh_checkout_evidence

GITLINK = 'Submodule/gitlink evidence is unsupported; no submodule commands were run'
NOT_ROOT = '--repo-dir must be the Git worktree top level, not a subdirectory or Git directory'


def add_root_gitlink(task, evidence, git):
    """A gitlink outside src/, inside the reviewed scope, so only the gitlink rule can reject it."""
    git('update-index', '--add', '--cacheinfo', '160000,' + evidence['base_commit'] + ',vendor')
    git('commit', '-q', '-m', 'add root gitlink')
    task['scope']['allowed_paths'].append('vendor')


class LegacyCheckoutRootTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = self.directory.name
        self.task, self.client, self.evidence, self.git = evidence_checkout(self.root)

    def test_verify_from_subdirectory_cannot_hide_root_gitlink(self):
        add_root_gitlink(self.task, self.evidence, self.git)
        refresh_checkout_evidence(self.evidence, self.git)
        digest = core.canonical_hash(self.task)
        for record in (self.evidence, self.evidence['independent_review'], self.evidence['human_signoff']):
            record['contract_sha256'] = digest
        whole = core.verify(self.task, self.evidence, self.root, self.client)
        self.assertEqual(whole['evidence_errors'], [GITLINK])
        for directory in (pathlib.Path(self.root, 'src'), pathlib.Path(self.root, '.git')):
            with self.subTest(directory=directory.name):
                result = core.verify(self.task, self.evidence, directory, self.client)
                self.assertIn(NOT_ROOT, result['evidence_errors'])
                self.assertFalse(result['evidence_valid'])
                self.assertFalse(result['upstream_submission_ready'])

    def test_scope_check_from_subdirectory_cannot_hide_root_untracked_file(self):
        pathlib.Path(self.root, 'forbidden.txt').write_text('out of scope')
        whole = workspace.scope_check(self.task, self.root)
        self.assertEqual([v['path'] for v in whole['violations']], ['forbidden.txt'])
        for directory in (pathlib.Path(self.root, 'src'), pathlib.Path(self.root, '.git')):
            with self.subTest(directory=directory.name):
                result = workspace.scope_check(self.task, directory)
                self.assertEqual(result['errors'], [NOT_ROOT])
                self.assertFalse(result['within_scope'])

    def test_evidence_init_from_subdirectory_is_refused(self):
        add_root_gitlink(self.task, self.evidence, self.git)
        with self.assertRaises(core.ProtocolError) as caught:
            workspace.evidence_skeleton(self.task, self.root, self.evidence['base_commit'])
        self.assertEqual(caught.exception.code, 'gitlink')
        for directory in (pathlib.Path(self.root, 'src'), pathlib.Path(self.root, '.git')):
            with self.subTest(directory=directory.name):
                with self.assertRaises(core.ProtocolError) as caught:
                    workspace.evidence_skeleton(self.task, directory, self.evidence['base_commit'])
                self.assertEqual((caught.exception.code, str(caught.exception)), ('not_worktree_root', NOT_ROOT))

    def test_symbolic_base_is_not_resolved_from_a_subdirectory(self):
        # F1 resolves --base with rev-parse; the top-level check must still run first.
        subdir = pathlib.Path(self.root, 'src')
        with patch.object(workspace, 'resolve_base', side_effect=AssertionError('resolved before root check')):
            self.assertEqual(workspace.scope_check(self.task, subdir, 'HEAD~1')['errors'], [NOT_ROOT])
            with self.assertRaises(core.ProtocolError) as caught:
                workspace.evidence_skeleton(self.task, subdir, 'HEAD~1')
        self.assertEqual(caught.exception.code, 'not_worktree_root')
        self.assertEqual(workspace.scope_check(self.task, self.root, 'HEAD~1')['base_commit'], self.evidence['base_commit'])


class CandidateCheckoutRootTests(unittest.TestCase):
    setUp = test_lifecycle.IntegratedLifecycleTests.setUp

    def test_schema_02_verify_from_subdirectory_cannot_hide_root_gitlink(self):
        add_root_gitlink(self.task, self.evidence, self.git)
        head = self.git('rev-parse', 'HEAD')
        digest = core.canonical_hash(self.task)
        self.context = host_context(self.task)
        self.evidence.update(git_head=head, git_tree=self.git('rev-parse', 'HEAD^{tree}'), contract_sha256=digest)
        self.evidence['independent_review'].update(git_head=head, contract_sha256=digest)
        for validation in self.evidence['validations']:
            validation['git_head'] = head
        verify = lambda directory: core.verify(self.task, self.evidence, directory, self.client,
                                               host_context=self.context)
        whole = verify(self.directory.name)
        self.assertEqual(whole['evidence_errors'], [GITLINK])
        self.assertFalse(whole['draft_create_ready'])
        result = verify(pathlib.Path(self.directory.name, 'src'))
        self.assertIn(NOT_ROOT, result['evidence_errors'])
        self.assertFalse(result['technical_evidence_valid'])
        self.assertFalse(result['draft_create_ready'])
        self.assertFalse(result['completion_ready'])


if __name__ == '__main__':
    unittest.main()
