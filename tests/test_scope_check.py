"""Offline scope-check: same rules as verify, no GitHub, never evidence."""
import contextlib
import copy
import io
import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from agent_contribute import cli, core, workspace
from tests.test_protocol import evidence_checkout, refresh_checkout_evidence


class NoNetwork:
    def request(self, endpoint):
        raise AssertionError('scope-check must not call GitHub: ' + endpoint)


class ScopeCheckTests(unittest.TestCase):
    def checkout(self, tmp):
        task, client, evidence, git = evidence_checkout(tmp)
        return task, client, evidence, git

    def test_committed_in_scope_change_passes_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            task, _, _, _ = self.checkout(tmp)
            with patch.object(core, 'GitHub', NoNetwork):
                result = workspace.scope_check(task, tmp)
            self.assertTrue(result['within_scope'], result)
            self.assertEqual(result['changed_paths'], ['src/thumb.rs'])
            self.assertEqual(result['violations'], [])
            self.assertIn('not evidence', result['evidence'])

    def test_staged_unstaged_untracked_and_renamed_paths_are_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            task, _, _, git = self.checkout(tmp)
            pathlib.Path(tmp, '.github').mkdir()
            pathlib.Path(tmp, '.github/ci.yml').write_text('staged')
            git('add', '.github/ci.yml')
            pathlib.Path(tmp, 'AGENTS.md').write_text('unstaged edit')
            pathlib.Path(tmp, 'notes.txt').write_text('untracked')
            git('mv', 'src/thumb.rs', 'src/renamed.rs')
            result = workspace.scope_check(task, tmp)
            self.assertFalse(result['within_scope'])
            self.assertEqual({v['path']: v['rule'] for v in result['violations']}, {
                '.github/ci.yml': 'prohibited_paths: .github/**',
                'AGENTS.md': 'not in allowed_paths',
                'notes.txt': 'not in allowed_paths'})
            self.assertTrue({'src/thumb.rs', 'src/renamed.rs'}.issubset(result['changed_paths']))

    def test_rename_into_scope_reports_deleted_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            task, _, _, git = self.checkout(tmp)
            git('mv', 'AGENTS.md', 'src/agents.txt')
            git('commit', '-q', '-m', 'move base file into scope')
            result = workspace.scope_check(task, tmp)
            self.assertEqual([v['path'] for v in result['violations']], ['AGENTS.md'])
            self.assertIn('src/agents.txt', result['changed_paths'])

    def test_gitlink_and_bad_base_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            task, _, evidence, git = self.checkout(tmp)
            for base in ['HEAD', '--output=/tmp/x', 'f' * 40]:
                with self.subTest(base=base):
                    result = workspace.scope_check(task, tmp, base)
                    self.assertFalse(result['within_scope'])
                    self.assertTrue(result['errors'])
            git('update-index', '--add', '--cacheinfo', '160000,' + evidence['base_commit'] + ',src/evil')
            result = workspace.scope_check(task, tmp)
            self.assertFalse(result['within_scope'])
            self.assertIn('Submodule/gitlink evidence is unsupported; no submodule commands were run', result['errors'])

    def test_invalid_contract_reads_no_checkout(self):
        with patch.object(core, 'git_read') as git_read:
            result = workspace.scope_check({'schema_version': '0.1'}, '.')
        self.assertFalse(result['within_scope'])
        self.assertTrue(result['errors'])
        git_read.assert_not_called()

    def test_parity_with_verify_on_committed_fixtures(self):
        # Every committed fixture must get the same scope decision from both entry points.
        variants = [(['src/**'], ['.github/**'], 'src/thumb.rs'),
                    (['docs/**'], ['.github/**'], 'src/thumb.rs'),
                    (['src/**'], ['src/thumb.rs'], 'src/thumb.rs'),
                    (['src/**'], ['.github/**'], ' src/evil.py'),
                    (['src/**'], ['.github/**'], 'src/[x].rs')]
        for allowed, prohibited, extra in variants:
            with self.subTest(allowed=allowed, prohibited=prohibited, extra=extra), tempfile.TemporaryDirectory() as tmp:
                task, client, evidence, git = self.checkout(tmp)
                path = pathlib.Path(tmp, extra)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('change')
                git('add', '-A')
                git('commit', '-q', '-m', 'variant')
                refresh_checkout_evidence(evidence, git)
                task = copy.deepcopy(task)
                task['scope'] = {'allowed_paths': allowed, 'prohibited_paths': prohibited}
                digest = core.canonical_hash(task)
                evidence['contract_sha256'] = digest
                for name in ('independent_review', 'human_signoff'):
                    evidence[name]['contract_sha256'] = digest
                verify_scope = sorted(e for e in core.verify(task, evidence, tmp, client)['evidence_errors']
                                      if 'outside reviewed scope' in e)
                checked = workspace.scope_check(task, tmp, evidence['base_commit'])
                self.assertEqual(verify_scope, sorted('Implementation changes a path outside reviewed scope: ' + v['path']
                                                      for v in checked['violations']))
                self.assertEqual(checked['within_scope'], not verify_scope)

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as out:
            task, _, _, _ = self.checkout(tmp)
            contract = pathlib.Path(out, 'task.json')
            contract.write_text(json.dumps(task))
            def run(*args):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    code = cli.main(['scope-check', str(contract), '--repo-dir', tmp, *args])
                return code, json.loads(output.getvalue())
            self.assertEqual(run()[0], 0)
            pathlib.Path(tmp, 'outside.txt').write_text('x')
            code, result = run()
            self.assertEqual(code, 1)
            self.assertEqual(result['violations'], [{'path': 'outside.txt', 'rule': 'not in allowed_paths'}])
            self.assertEqual(run('--base', 'nope')[0], 1)


if __name__ == '__main__':
    unittest.main()
