"""Evidence skeleton: observed Git facts only, never results, never valid as written."""
import contextlib
import io
import json
import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from agent_contribute import cli, core, workspace
from tests.test_authorization import candidate_task
from tests.test_protocol import evidence_checkout


class EvidenceInitTests(unittest.TestCase):
    def test_skeleton_copies_observed_facts_and_contract_ids_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            task, _, evidence, git = evidence_checkout(tmp)
            with patch.object(core, 'GitHub', side_effect=AssertionError('no GitHub')), \
                    patch.object(core.subprocess, 'run', wraps=core.subprocess.run) as run:
                skeleton = workspace.evidence_skeleton(task, tmp, evidence['base_commit'])
            self.assertTrue(all(call.args[0][0] == 'git' for call in run.call_args_list), 'Only Git may run')
            for key in ('contract_sha256', 'git_head', 'git_tree', 'base_commit'):
                self.assertEqual(skeleton[key], evidence[key])
            self.assertIs(skeleton['worktree_clean'], True)
            self.assertEqual(skeleton['implementer'], '')
            [check] = skeleton['validations']
            self.assertEqual((check['id'], check['argv']), ('unit', ['python3', '-m', 'unittest']))
            self.assertEqual({check[k] for k in ('status', 'exit_code', 'skipped', 'tests_run')}, {None})
            self.assertEqual(check['git_head'], '')
            self.assertEqual(skeleton['criteria'], [{'id': 'bounds', 'status': 'pending', 'evidence': ''}])
            self.assertEqual(skeleton['independent_review']['status'], 'pending')
            self.assertEqual(skeleton['human_signoff']['status'], 'pending')
            self.assertNotIn('passed', json.dumps(skeleton))

    def test_unfilled_skeleton_fails_evidence_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            task, client, evidence, _ = evidence_checkout(tmp)
            skeleton = workspace.evidence_skeleton(task, tmp, evidence['base_commit'])
            self.assertTrue(core.schema_errors(skeleton, core.bundled_schema('evidence')))
            result = core.verify(task, skeleton, tmp, client)
            self.assertFalse(result['evidence_valid'])
            self.assertFalse(result['upstream_submission_ready'])

    def test_schema_02_skeleton_has_no_human_signoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            task, _, evidence, _ = evidence_checkout(tmp)
            legacy_commit = task['source']['commit']
            task, client = candidate_task()
            task['source']['commit'] = client.commit = legacy_commit
            self.assertEqual(core.validate_contract(task), [])
            skeleton = workspace.evidence_skeleton(task, tmp, evidence['base_commit'])
            self.assertEqual(skeleton['contract_sha256'], core.canonical_hash(task))
            self.assertEqual(skeleton['schema_version'], '0.2')
            self.assertNotIn('human_signoff', skeleton)
            self.assertEqual(skeleton['independent_review']['reviewed_at'], '')
            self.assertTrue(core.schema_errors(skeleton, core.bundled_schema('evidence', '0.2')))

    def test_dirty_worktree_is_recorded_as_observed(self):
        with tempfile.TemporaryDirectory() as tmp:
            task, _, evidence, _ = evidence_checkout(tmp)
            pathlib.Path(tmp, 'src/thumb.rs').write_text('uncommitted')
            self.assertIs(workspace.evidence_skeleton(task, tmp, evidence['base_commit'])['worktree_clean'], False)

    def test_base_ancestry_gitlinks_and_invalid_inputs_refuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            task, _, evidence, git = evidence_checkout(tmp)
            head = git('rev-parse', 'HEAD')
            git('checkout', '-q', '--orphan', 'other')
            git('commit', '-q', '-m', 'unrelated root')
            unrelated = git('rev-parse', 'HEAD')
            git('checkout', '-q', '-f', head)
            for base in [unrelated, 'HEAD', '--output=x', 'f' * 40]:
                with self.subTest(base=base), self.assertRaises(core.ProtocolError):
                    workspace.evidence_skeleton(task, tmp, base)
            # The pinned source commit must be an ancestor of the chosen base.
            later = dict(task, source=dict(task['source'], commit=head))
            with self.assertRaises(core.ProtocolError):
                workspace.evidence_skeleton(later, tmp, evidence['base_commit'])
            with self.assertRaises(core.ProtocolError):
                workspace.evidence_skeleton({'schema_version': '0.1'}, tmp, evidence['base_commit'])
            git('update-index', '--add', '--cacheinfo', '160000,' + evidence['base_commit'] + ',src/evil')
            with self.assertRaises(core.ProtocolError):
                workspace.evidence_skeleton(task, tmp, evidence['base_commit'])

    def invoke(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = cli.main(list(args))
        return code, json.loads(output.getvalue())

    def test_cli_exclusive_output_outside_checkout(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as out:
            task, _, evidence, _ = evidence_checkout(tmp)
            contract = pathlib.Path(out, 'task.json')
            contract.write_text(json.dumps(task))
            target = pathlib.Path(out, 'evidence.json')
            args = ['evidence', 'init', str(contract), '--repo-dir', tmp, '--base', evidence['base_commit']]
            code, result = self.invoke(*args, '--output', str(target))
            self.assertEqual(code, 0, result)
            self.assertFalse(result['evidence_valid'])
            self.assertEqual(json.loads(target.read_text())['git_head'], evidence['git_head'])
            target.write_text('hand-filled evidence')
            code, result = self.invoke(*args, '--output', str(target))
            self.assertEqual((code, result['error']['code']), (1, 'file_error'))
            self.assertEqual(target.read_text(), 'hand-filled evidence')
            for inside in [pathlib.Path(tmp, 'evidence.json'), pathlib.Path(tmp, 'src', 'e.json')]:
                with self.subTest(inside=inside):
                    code, result = self.invoke(*args, '--output', str(inside))
                    self.assertEqual((code, result['error']['code']), (1, 'output_in_checkout'))
                    self.assertFalse(inside.exists())
            if os.name == 'nt':
                return  # Unprivileged Windows runners cannot create symlinks.
            nested = pathlib.Path(out, 'link-to-src')
            nested.symlink_to(pathlib.Path(tmp, 'src'), target_is_directory=True)
            code, result = self.invoke(*args, '--output', str(nested / 'e.json'))
            self.assertEqual((code, result['error']['code']), (1, 'output_in_checkout'))
            link = pathlib.Path(out, 'link')
            link.symlink_to(tmp, target_is_directory=True)
            code, result = self.invoke(*args, '--output', str(link / 'e.json'))
            self.assertEqual((code, result['error']['code']), (1, 'output_in_checkout'))
            self.assertFalse(pathlib.Path(tmp, 'e.json').exists())

    @unittest.skipIf(os.name == 'nt', 'Windows forbids trailing whitespace in directory names')
    def test_checkout_root_with_trailing_whitespace_still_contains_output(self):
        # Git output is stripped by git_read; the containment root must not be.
        for suffix in [' ', '\t', '\n', ' \n ']:
            with self.subTest(suffix=repr(suffix)), tempfile.TemporaryDirectory() as parent:
                repo = pathlib.Path(parent, 'repo' + suffix)
                repo.mkdir()
                task, _, evidence, _ = evidence_checkout(str(repo))
                contract = pathlib.Path(parent, 'task.json')
                contract.write_text(json.dumps(task))
                with self.assertRaises(core.ProtocolError):
                    workspace.require_outside_checkout(str(repo), str(repo / 'evidence.json'))
                code, result = self.invoke('evidence', 'init', str(contract), '--repo-dir', str(repo),
                                           '--base', evidence['base_commit'], '--output', str(repo / 'evidence.json'))
                self.assertEqual((code, result['error']['code']), (1, 'output_in_checkout'))
                self.assertFalse((repo / 'evidence.json').exists())
                sibling = pathlib.Path(parent, 'repo')
                if not sibling.exists():
                    sibling.mkdir()
                    workspace.require_outside_checkout(str(repo), str(sibling / 'evidence.json'))


if __name__ == '__main__':
    unittest.main()
