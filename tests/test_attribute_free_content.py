"""Worktree content is compared byte for byte: attribute conversions (ident, eol, working-tree-encoding) cannot
make different bytes equal to the commit (R1-19)."""
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from agent_contribute import core, workspace
from tests import test_lifecycle
from tests.test_protocol import evidence_checkout, refresh_checkout_evidence

DIRTY = 'Current checkout is dirty or differs from evidence HEAD/tree'
INJECTED = 'VALUE = "$Id: "; UNREVIEWED = True; #$"\n'  # ident collapses this back to VALUE = "$Id$"
VARIANTS = {'ident': ('settings.py ident\n', 'VALUE = "$Id$"\n', INJECTED),
            'eol': ('settings.py text eol=crlf\n', 'VALUE = 1\n', 'VALUE = 1\r\n'),
            # The worktree holds UTF-16 bytes; Git stores UTF-8, so the bytes never equal the blob.
            'encoding': ('settings.py working-tree-encoding=UTF-16LE\n', 'VALUE = 1\n'.encode('utf-16-le'),
                         'VALUE = 1\n'.encode('utf-16-le'))}


def commit_attributes(root, git, attributes, committed):
    pathlib.Path(root, '.gitattributes').write_text(attributes)
    path = pathlib.Path(root, 'settings.py')
    path.write_bytes(committed if isinstance(committed, bytes) else committed.encode())
    git('add', '.gitattributes', 'settings.py')
    git('commit', '-q', '-m', 'attributes')


def convert(root, git, worktree):
    path = pathlib.Path(root, 'settings.py')
    path.write_bytes(worktree if isinstance(worktree, bytes) else worktree.encode())
    git('add', 'settings.py')  # the clean conversion maps the new bytes back to the committed blob
    assert git('status', '--porcelain') == '', 'precondition: Git attributes make the change invisible'


class LegacyAttributeTests(unittest.TestCase):
    def test_converted_worktree_bytes_are_a_change_in_every_gate(self):
        for name, (attributes, committed, worktree) in VARIANTS.items():
            with self.subTest(variant=name), tempfile.TemporaryDirectory() as root:
                task, client, evidence, git = evidence_checkout(root)
                commit_attributes(root, git, attributes, committed)
                refresh_checkout_evidence(evidence, git)
                task['scope']['allowed_paths'] += ['.gitattributes', 'settings.py']
                digest = core.canonical_hash(task)
                for record in (evidence, evidence['independent_review'], evidence['human_signoff']):
                    record['contract_sha256'] = digest
                if name == 'ident':  # control: the committed state itself verifies
                    self.assertTrue(core.verify(task, evidence, root, client)['evidence_valid'])
                convert(root, git, worktree)
                self.assertIn(DIRTY, core.verify(task, evidence, root, client)['evidence_errors'])
                self.assertIn('settings.py', workspace.scope_check(task, root, 'HEAD')['changed_paths'])
                self.assertIs(workspace.evidence_skeleton(task, root, evidence['base_commit'])['worktree_clean'], False)

    def test_local_autocrlf_and_attributes_file_cannot_define_equality(self):
        for name in ('core.autocrlf', 'core.attributesFile'):
            with self.subTest(setting=name), tempfile.TemporaryDirectory() as root:
                task, client, evidence, git = evidence_checkout(root)
                agents = pathlib.Path(root, 'AGENTS.md')
                committed = 'line one\nline two\n' if name == 'core.autocrlf' else 'VALUE = "$Id$"\n'
                agents.write_text(committed)
                git('commit', '-qam', 'new committed content')
                refresh_checkout_evidence(evidence, git)
                task['scope']['allowed_paths'].append('AGENTS.md')
                digest = core.canonical_hash(task)
                for record in (evidence, evidence['independent_review'], evidence['human_signoff']):
                    record['contract_sha256'] = digest
                if name == 'core.autocrlf':
                    git('config', 'core.autocrlf', 'true')
                    agents.write_bytes(committed.replace('\n', '\r\n').encode())
                else:
                    local = pathlib.Path(root, '.git', 'local-attributes')
                    local.write_text('AGENTS.md ident\n')
                    git('config', 'core.attributesFile', str(local))
                    agents.write_text(INJECTED)
                git('add', 'AGENTS.md')
                self.assertEqual(git('status', '--porcelain'), '', 'precondition: the conversion hides it')
                self.assertIn(DIRTY, core.verify(task, evidence, root, client)['evidence_errors'])
                self.assertIs(workspace.evidence_skeleton(task, root, evidence['base_commit'])['worktree_clean'], False)

    def test_local_info_attributes_are_refused(self):
        refusal = ('Checkout sets local Git attributes in info/attributes, which could change how files are '
                   'compared; remove them or use a fresh clone')
        with tempfile.TemporaryDirectory() as root:
            task, client, evidence, git = evidence_checkout(root)
            info = pathlib.Path(root, '.git', 'info')
            info.mkdir(exist_ok=True)
            (info / 'attributes').write_text('# comments and blank lines are fine\n\n')
            self.assertTrue(core.verify(task, evidence, root, client)['evidence_valid'])
            (info / 'attributes').write_text('AGENTS.md ident\n')
            self.assertIn(refusal, core.verify(task, evidence, root, client)['evidence_errors'])
            self.assertEqual(workspace.scope_check(task, root)['errors'], [refusal])
            with self.assertRaises(core.ProtocolError) as caught:
                workspace.evidence_skeleton(task, root, evidence['base_commit'])
            self.assertEqual(caught.exception.code, 'unsafe_git_attributes')

    def test_git_older_than_2_40_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            task, client, evidence, git = evidence_checkout(root)
            original = core.git_read

            def old_git(directory, *args, **options):
                return 'git version 2.39.3 (Apple Git-145)' if args == ('--version',) else original(directory, *args, **options)
            with patch.object(core, 'git_read', side_effect=old_git):
                with self.assertRaises(core.ProtocolError) as caught:
                    core.worktree_changes(root, evidence['git_head'])
            self.assertEqual(caught.exception.code, 'git_too_old')


class CandidateAttributeTests(unittest.TestCase):
    setUp = test_lifecycle.LifecycleTests.setUp
    verify = test_lifecycle.LifecycleTests.verify

    def test_schema_02_ident_conversion_blocks_draft(self):
        commit_attributes(self.directory.name, self.git, *VARIANTS['ident'][:2])
        head = self.git('rev-parse', 'HEAD')
        self.task['scope']['allowed_paths'] += ['.gitattributes', 'settings.py']
        digest = core.canonical_hash(self.task)
        self.context = test_lifecycle.host_context(self.task)
        self.evidence.update(git_head=head, git_tree=self.git('rev-parse', 'HEAD^{tree}'), contract_sha256=digest)
        self.evidence['independent_review'].update(git_head=head, contract_sha256=digest)
        for validation in self.evidence['validations']:
            validation['git_head'] = head
        self.assertTrue(self.verify()['draft_create_ready'])
        convert(self.directory.name, self.git, INJECTED)
        result = self.verify()
        self.assertIn(DIRTY, result['evidence_errors'])
        self.assertFalse(result['draft_create_ready'])


if __name__ == '__main__':
    unittest.main()
