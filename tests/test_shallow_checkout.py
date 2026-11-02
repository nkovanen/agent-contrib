"""A shallow clone that lacks the base fails closed with a message that says why (G-10)."""
import subprocess
import tempfile
import unittest

from agent_contribute import core, workspace
from tests.test_protocol import evidence_checkout

SHALLOW = ('Checkout is shallow and lacks the history needed to check the base; fetch more history '
           '(git fetch --unshallow or --deepen) and retry')


class ShallowCheckoutTests(unittest.TestCase):
    def clone(self, depth):
        source = tempfile.TemporaryDirectory()
        self.addCleanup(source.cleanup)
        task, client, evidence, _ = evidence_checkout(source.name)
        target = tempfile.TemporaryDirectory()
        self.addCleanup(target.cleanup)
        subprocess.run(['git', 'clone', '-q', '--depth', str(depth), 'file://' + source.name, target.name + '/c'],
                       check=True, capture_output=True)
        return task, client, evidence, target.name + '/c'

    def test_missing_base_in_a_shallow_clone_names_the_cause(self):
        task, client, evidence, root = self.clone(1)
        self.assertIn(SHALLOW, core.verify(task, evidence, root, client)['evidence_errors'])
        self.assertEqual(workspace.scope_check(task, root)['errors'], [SHALLOW])
        self.assertEqual(workspace.scope_check(task, root, evidence['base_commit'])['errors'], [SHALLOW])
        with self.assertRaises(core.ProtocolError) as caught:
            workspace.evidence_skeleton(task, root, evidence['base_commit'])
        self.assertEqual((caught.exception.code, str(caught.exception)), ('shallow_checkout', SHALLOW))

    def test_grammar_errors_and_deep_enough_clones_are_unchanged(self):
        task, client, evidence, root = self.clone(1)
        self.assertTrue(workspace.scope_check(task, root, 'abc123')['errors'][0].startswith('Base must be'))
        task, client, evidence, root = self.clone(2)
        self.assertNotIn(SHALLOW, core.verify(task, evidence, root, client)['evidence_errors'])
        self.assertEqual(workspace.scope_check(task, root)['errors'], [])


if __name__ == '__main__':
    unittest.main()
