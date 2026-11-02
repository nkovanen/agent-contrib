"""Offline scope-check: same rules as verify, no GitHub, never evidence."""
import contextlib
import copy
import io
import json
import os
import pathlib
import subprocess
import sys
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
            for base in ['--output=/tmp/x', '-x', '', 'f' * 40, 'nope', 'HEAD^{tree}', 'HEAD\nHEAD', 'HEAD~1..HEAD']:
                with self.subTest(base=base):
                    result = workspace.scope_check(task, tmp, base)
                    self.assertFalse(result['within_scope'])
                    self.assertTrue(result['errors'])
                    self.assertIsNone(result['base_commit'])
            git('update-index', '--add', '--cacheinfo', '160000,' + evidence['base_commit'] + ',src/evil')
            result = workspace.scope_check(task, tmp)
            self.assertFalse(result['within_scope'])
            self.assertIn('Submodule/gitlink evidence is unsupported; no submodule commands were run', result['errors'])

    def test_base_accepts_full_sha_head_and_exact_refs_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            task, _, evidence, git = self.checkout(tmp)
            base = evidence['base_commit']
            git('branch', 'work-base', base)
            git('tag', '-a', '-m', 'annotated', 'v-base', base)
            for rev in ['refs/heads/work-base', 'refs/tags/v-base', 'refs/heads/work-base~0^0', 'HEAD~1', 'HEAD^', base,
                        git('rev-parse', 'HEAD') + '~1']:
                with self.subTest(rev=rev):
                    result = workspace.scope_check(task, tmp, rev)
                    self.assertTrue(result['within_scope'], result)
                    self.assertEqual(result['base_commit'], base)
                    self.assertEqual(result['changed_paths'], ['src/thumb.rs'])
                    self.assertEqual(result['warnings'], [])
            result = workspace.scope_check(task, tmp, 'HEAD')
            self.assertEqual((result['base_commit'], result['changed_paths']), (evidence['git_head'], []))

    def test_base_errors_hint_at_accepted_forms_and_resolution_ignores_replacements(self):
        with tempfile.TemporaryDirectory() as tmp:
            task, _, evidence, git = self.checkout(tmp)
            self.assertEqual(workspace.scope_check(task, tmp, 'refs/heads/nope')['errors'],
                             ['Base does not name a commit in this checkout; give a full SHA, HEAD or an '
                              'existing refs/... name'])
            self.assertEqual(workspace.scope_check(task, tmp, '--output=x')['errors'],
                             ['Base must be a full SHA, HEAD or refs/... name; it cannot be blank, '
                              'start with "-" or contain spaces or control characters'])
            # A replacement object must not redirect the resolved base.
            git('replace', '-f', evidence['base_commit'], git('rev-parse', 'HEAD^{tree}'))
            result = workspace.scope_check(task, tmp, evidence['base_commit'])
            self.assertEqual(result['base_commit'], evidence['base_commit'])
            self.assertTrue(result['within_scope'], result)
            head, branch = evidence['git_head'], git('symbolic-ref', 'HEAD')
            for rev, lookup in [('HEAD~1', ('rev-parse', '--verify', '--quiet', 'HEAD')),
                                (branch + '~1', ('show-ref', '--verify', '--hash', branch))]:
                with self.subTest(rev=rev), patch.object(core, 'git_read', wraps=core.git_read) as git_read:
                    self.assertEqual(workspace.resolve_base(tmp, rev), evidence['base_commit'])
                # Every lookup goes through the hardened Git reader; the suffix applies to the captured ID.
                self.assertEqual([call.args for call in git_read.call_args_list],
                                 [(tmp,) + lookup, (tmp, 'rev-parse', '--verify', '--quiet', head + '~1^{commit}')])

    def test_unsupported_revision_forms_are_refused_with_a_conversion_hint(self):
        grammar = ('Base must be a full 40-character SHA, HEAD or a full ref name such as refs/heads/NAME or '
                   'refs/tags/NAME, optionally followed by ~N or ^N; convert an abbreviated SHA with '
                   'git rev-parse ABBREV')
        with tempfile.TemporaryDirectory() as tmp:
            task, _, evidence, git = self.checkout(tmp)
            base = evidence['base_commit']
            git('branch', 'work-base', base)
            self.assertEqual(git('rev-parse', '--verify', ':/upstream'), base)
            for rev in [':/upstream', '@{-1}', 'HEAD@{0}', 'HEAD:AGENTS.md', 'HEAD^{tree}', 'HEAD^{/upstream}',
                        'HEAD~1..HEAD', 'refs/heads/*', 'HEAD^!', '/HEAD', 'work-base', 'heads/work-base',
                        base[:12], base.upper(), 'FETCH_HEAD', 'ORIG_HEAD', '@', 'head', 'refs/']:
                with self.subTest(rev=rev):
                    result = workspace.scope_check(task, tmp, rev)
                    self.assertEqual((result['within_scope'], result['base_commit'], result['errors']),
                                     (False, None, [grammar]))
                    with self.assertRaises(core.ProtocolError) as raised:
                        workspace.evidence_skeleton(task, tmp, rev)
                    self.assertEqual(str(raised.exception), grammar)

    def test_colliding_names_resolve_exactly_and_never_by_git_preference(self):
        with tempfile.TemporaryDirectory() as tmp:
            task, _, evidence, git = self.checkout(tmp)
            base = evidence['base_commit']
            pathlib.Path(tmp, 'outside.txt').write_text('out of scope')
            git('add', 'outside.txt')
            git('commit', '-q', '-m', 'out of scope')
            head = git('rev-parse', 'HEAD')
            git('branch', 'work-base', base)
            git('tag', 'work-base', 'HEAD')
            git('update-ref', 'refs/tags/refs/heads/work-base', 'HEAD')
            git('update-ref', 'refs/refs/heads/ghost', 'HEAD')
            git('update-ref', 'refs/heads/HEAD', base)
            git('update-ref', 'refs/heads/FETCH_HEAD', 'HEAD')
            pathlib.Path(tmp, '.git', 'FETCH_HEAD').write_text(base + '\t\tbranch main of https://github.com/acme/photos\n')
            pathlib.Path(tmp, '.git', 'refs', 'heads', 'crlf').write_text(base + '\r\n', newline='')
            os.mkfifo(pathlib.Path(tmp, '.git', 'slow-ref'))
            git('branch', 'slow-ref', base)
            # Raw Git silently prefers one meaning; the resolver only accepts exact names.
            self.assertEqual(git('rev-parse', '--verify', 'work-base'), head)
            self.assertEqual(git('rev-parse', '--verify', 'refs/heads/ghost'), head)
            for rev, expected in [('refs/heads/work-base', base), ('refs/tags/work-base', head),
                                  ('refs/tags/refs/heads/work-base', head), ('HEAD', head), ('refs/heads/HEAD', base),
                                  ('refs/heads/FETCH_HEAD', head), ('refs/heads/crlf', base),
                                  ('refs/heads/slow-ref', base)]:
                with self.subTest(rev=rev):
                    self.assertEqual(workspace.resolve_base(tmp, rev), expected)
            result = workspace.scope_check(task, tmp, 'refs/heads/work-base')
            self.assertEqual(result['violations'], [{'path': 'outside.txt', 'rule': 'not in allowed_paths'}])
            with self.assertRaises(core.ProtocolError) as raised:
                workspace.resolve_base(tmp, 'refs/heads/ghost')
            self.assertEqual(raised.exception.code, 'invalid_base')
            self.assertEqual(workspace.evidence_skeleton(task, tmp, 'refs/heads/work-base')['base_commit'], base)
            # A FIFO under .git is never opened: the CLI answers promptly for short and exact names.
            contract = pathlib.Path(tmp).parent / (pathlib.Path(tmp).name + '-task.json')
            contract.write_text(json.dumps(task))
            self.addCleanup(contract.unlink)
            for rev, code in [('slow-ref', 1), ('refs/heads/slow-ref', 1)]:
                with self.subTest(rev=rev):
                    completed = subprocess.run([sys.executable, '-m', 'agent_contribute', 'scope-check', str(contract),
                                                '--repo-dir', tmp, '--base', rev], capture_output=True, text=True,
                                               timeout=10, cwd=pathlib.Path(__file__).resolve().parent.parent)
                    self.assertEqual(completed.returncode, code)
            self.assertEqual(json.loads(completed.stdout)['base_commit'], base)

    def test_ref_moving_after_lookup_does_not_change_the_selected_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            task, _, evidence, git = self.checkout(tmp)
            base = evidence['base_commit']
            git('branch', 'race', base)
            real = core.git_read

            def moving(directory, *args):
                output = real(directory, *args)
                if args[0] == 'show-ref':
                    git('update-ref', 'refs/heads/race', 'HEAD')
                    git('tag', 'race', 'HEAD')
                return output
            with patch.object(core, 'git_read', side_effect=moving):
                self.assertEqual(workspace.resolve_base(tmp, 'refs/heads/race'), base)
            self.assertEqual(workspace.resolve_base(tmp, 'refs/heads/race'), evidence['git_head'])

    def test_default_base_outside_head_history_warns_and_still_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            task, _, evidence, git = self.checkout(tmp)
            head = evidence['git_head']
            git('checkout', '-q', '--orphan', 'other')
            git('commit', '-q', '-m', 'unrelated root')
            unrelated = git('rev-parse', 'HEAD')
            git('checkout', '-q', '-f', head)
            task['source']['commit'] = unrelated
            result = workspace.scope_check(task, tmp)
            self.assertFalse(result['within_scope'])
            self.assertEqual(result['errors'], ['Base commit is missing or not an ancestor of HEAD'])
            self.assertEqual(result['warnings'], ['Default base source.commit is not an ancestor of HEAD; for '
                                                  'stacked or rebased work pass --base REV naming the commit '
                                                  'your change starts from'])
            result = workspace.scope_check(task, tmp, unrelated)
            self.assertFalse(result['within_scope'])
            self.assertEqual(result['warnings'], [])

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
            code, result = run('--base=--output=x')
            self.assertEqual((code, result['base_commit']), (1, None))
            code, result = run('--base', 'HEAD~1')
            self.assertEqual((code, result['base_commit']), (1, task['source']['commit']))
            code, result = run('--base', task['source']['commit'][:12])
            self.assertEqual((code, result['base_commit']), (1, None))


if __name__ == '__main__':
    unittest.main()
