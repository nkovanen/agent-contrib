"""A gitlink only in the implementation base still blocks every checkout gate (R1-04)."""
import tempfile
import unittest

from agent_contribute import core, workspace
from tests.test_protocol import evidence_checkout, refresh_checkout_evidence

GITLINK = 'Submodule/gitlink evidence is unsupported; no submodule commands were run'


class BaseOnlyGitlinkTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = self.directory.name
        task, client, evidence, git = evidence_checkout(self.root)
        git('update-index', '--add', '--cacheinfo', '160000,' + evidence['base_commit'] + ',vendor')
        git('commit', '-q', '-m', 'base with gitlink')
        base = git('rev-parse', 'HEAD')
        git('update-index', '--force-remove', 'vendor')
        git('commit', '-q', '-m', 'remove gitlink')
        self.assertNotIn('160000 ', git('ls-tree', '-r', 'HEAD') + git('ls-files', '--stage'))
        # Removing vendor is in scope, so only the gitlink rule can reject this checkout.
        task['source']['commit'] = evidence['base_commit'] = client.commit = base
        task['scope']['allowed_paths'].append('vendor')
        refresh_checkout_evidence(evidence, git)
        digest = core.canonical_hash(task)
        for record in (evidence, evidence['independent_review'], evidence['human_signoff']):
            record['contract_sha256'] = digest
        self.task, self.client, self.evidence, self.base = task, client, evidence, base

    def test_verify_rejects_gitlink_present_only_in_base(self):
        result = core.verify(self.task, self.evidence, self.root, self.client)
        self.assertEqual(result['evidence_errors'], [GITLINK])
        self.assertFalse(result['evidence_valid'])
        self.assertFalse(result['upstream_submission_ready'])

    def test_scope_check_rejects_gitlink_present_only_in_base(self):
        result = workspace.scope_check(self.task, self.root)
        self.assertEqual(result['errors'], [GITLINK])
        self.assertEqual(result['violations'], [])
        self.assertFalse(result['within_scope'])

    def test_evidence_init_rejects_gitlink_present_only_in_base(self):
        with self.assertRaises(core.ProtocolError) as caught:
            workspace.evidence_skeleton(self.task, self.root, self.base)
        self.assertEqual((caught.exception.code, str(caught.exception)), ('gitlink', GITLINK))


if __name__ == '__main__':
    unittest.main()
