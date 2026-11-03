"""discover --repo-dir (F12): issues referenced by local commits not in the source default branch; report only."""
import contextlib
import io
import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from agent_contribute import cli, core, workspace
from tests.test_signals import SignalGitHub


def checkout(tmp):
    def git(*argv):
        return subprocess.check_output(['git', '-C', tmp, '-c', 'user.name=Test', '-c', 'user.email=test@example.org',
                                        *argv], text=True).strip()
    git.directory = tmp
    git('init', '-q')
    pathlib.Path(tmp, 'README.md').write_text('base')
    git('add', '.')
    git('commit', '-q', '-m', 'published base')
    return git, git('rev-parse', 'HEAD')


def commit(git, message):
    git('commit', '-q', '--allow-empty', '-m', message)
    return git('rev-parse', 'HEAD')


def run(client, *argv):
    output = io.StringIO()
    with patch.object(core, 'GitHub', return_value=client), contextlib.redirect_stdout(output):
        code = cli.main(list(argv))
    return code, json.loads(output.getvalue())


def import_commits(git, messages):
    """Many commits quickly: fast-import appends to the current branch without touching the worktree."""
    branch, parent = git('symbolic-ref', 'HEAD'), git('rev-parse', 'HEAD')
    stream = []
    for index, message in enumerate(messages):
        data = message.encode('utf-8')
        stream.append(f'commit {branch}\nmark :{index + 1}\ncommitter T <t@e> 1700000000 +0000\n'
                      f'data {len(data)}\n'.encode() + data + b'\n' +
                      (f'from {parent}\n' if index == 0 else '').encode())
    subprocess.run(['git', '-C', git.directory, 'fast-import', '--quiet'], input=b''.join(stream), check=True)
    return git('rev-parse', 'HEAD')


class LocalWorkTests(unittest.TestCase):
    def test_references_to_the_same_repository_in_unpublished_commits_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            git, base = checkout(tmp)
            fix = commit(git, 'Bounds check\n\nFixes #12 and closes acme/photos#3; fixes ACME/Photos#3 again')
            commit(git, 'Unrelated: other/repo#5, abc#7, https://x/#8, GH-9 and #0')
            report = workspace.local_issue_references(tmp, 'acme/photos', base)
            self.assertEqual(report['issues'], [{'number': 3, 'commits': [fix]}, {'number': 12, 'commits': [fix]}])
            self.assertEqual((report['complete'], report['commits_scanned'], report['base']), (True, 2, base))
            self.assertEqual(report['head'], git('rev-parse', 'HEAD'))
            # Commits already in the source default branch are not unpublished work.
            self.assertEqual(workspace.local_issue_references(tmp, 'acme/photos', fix)['issues'], [])

    def test_only_closing_keyword_references_count(self):
        # Dogfood 4 N4: every '#N' counted, including other projects, quoted text, examples and partial work.
        with tempfile.TemporaryDirectory() as tmp:
            git, base = checkout(tmp)
            done = commit(git, 'Bounds check\n\nFixes #12, closes acme/photos#3. Resolved: #4\n'
                               'Fixes #20, #21 and #22')
            commit(git, "Port the ripgrep #278 workaround; test text \"I'm working on issue #999\"; cut '#1234567890'\n"
                        'Refs #25 (part 1 of 3); see PR #2; Fixes other/repo#6; prefixes #30; fix-ups #31')
            report = workspace.local_issue_references(tmp, 'acme/photos', base)
            self.assertEqual([item['number'] for item in report['issues']], [3, 4, 12, 20, 21, 22])
            self.assertTrue(all(item['commits'] == [done] for item in report['issues']))

    def test_discover_signals_moves_locally_implemented_issues_below_other_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            git, base = checkout(tmp)
            fix = commit(git, 'Fix #12')
            client = SignalGitHub()
            client.commit = base
            code, plain = run(client, 'discover', 'acme/photos', '--signals')
            self.assertEqual([item['number'] for item in plain['issues']], [12, 3])
            self.assertNotIn('local_work', plain)
            code, result = run(client, 'discover', 'acme/photos', '--signals', '--repo-dir', tmp)
            self.assertEqual(code, 0)
            self.assertEqual([item['number'] for item in result['issues']], [3, 12])
            twelve = result['issues'][1]['signals']
            self.assertEqual(twelve['local_work'], {'value': 'referenced', 'commits': [fix],
                                                    'explanation': 'Closed by 1 local commit(s) not in the source default '
                                                                   'branch (fixes, closes or resolves); the work may '
                                                                   'already exist'})
            self.assertEqual(twelve['score'], plain['issues'][0]['signals']['score'])
            self.assertEqual(result['issues'][0]['signals']['local_work']['value'], 'none')
            self.assertEqual(result['local_work']['issues'], [{'number': 12, 'commits': [fix]}])
            self.assertIn('locally referenced', result['ordering'])
            code, default = run(client, 'discover', 'acme/photos')
            code, unsignalled = run(client, 'discover', 'acme/photos', '--repo-dir', tmp)
            self.assertEqual(unsignalled['issues'], default['issues'])  # without --signals: report only
            self.assertNotIn('signals', unsignalled['issues'][0])
            self.assertEqual(unsignalled['local_work']['issues'], [{'number': 12, 'commits': [fix]}])
            # Overlapping issues still rank last, below locally referenced ones.
            client.prs = [{'number': 40, 'title': 'Other', 'body': 'Fixes #3', 'head': None,
                           'html_url': 'https://github.com/acme/photos/pull/40'}]
            code, result = run(client, 'discover', 'acme/photos', '--signals', '--repo-dir', tmp)
            self.assertEqual([item['number'] for item in result['issues']], [12, 3])

    def test_bounds_missing_base_and_unsafe_checkouts_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            git, base = checkout(tmp)
            for n in range(4):
                commit(git, f'Step {n}, fixes #12')
            with patch.object(workspace, 'MAX_LOCAL_COMMITS', 3):
                report = workspace.local_issue_references(tmp, 'acme/photos', base)
            self.assertFalse(report['complete'])
            self.assertEqual(report['commits_scanned'], 3)
            self.assertIn('More than 3 local commits after the source default branch; only the newest 3 were read',
                          report['errors'])
            self.assertEqual(len(report['issues'][0]['commits']), 3)
            missing = workspace.local_issue_references(tmp, 'acme/photos', 'f' * 40)
            self.assertFalse(missing['complete'])
            self.assertEqual(missing['errors'], ['Source default-branch commit ' + 'f' * 40 + ' is not in this checkout; '
                                                 'fetch it with your own tools (the CLI never fetches)'])
            git('config', 'gpg.program', 'touch /tmp/agent-contrib-pwned')
            unsafe = workspace.local_issue_references(tmp, 'acme/photos', base)
            self.assertFalse(unsafe['complete'])
            self.assertTrue(unsafe['errors'][0].startswith('Checkout Git config sets gpg.program'))
            git('config', '--unset', 'gpg.program')
            sub = pathlib.Path(tmp, 'sub')
            sub.mkdir()
            self.assertFalse(workspace.local_issue_references(str(sub), 'acme/photos', base)['complete'])

    def test_message_bytes_are_bounded_before_reading_and_never_parsed_partially(self):
        # Review R11-01: a 64 Ki character slice turned '#1234567890' into '#12' and buffered whole messages.
        with tempfile.TemporaryDirectory() as tmp:
            git, base = checkout(tmp)
            near = import_commits(git, ['x' * 65000 + ' Fixes #11'])
            report = workspace.local_issue_references(tmp, 'acme/photos', base)
            self.assertEqual((report['complete'], report['issues']), (True, [{'number': 11, 'commits': [near]}]))
            long = import_commits(git, ['x' * 65532 + ' #1234567890'])
            wide = import_commits(git, ['\u00e9' * 40000 + ' Fixes acme/photos#12'])
            report = workspace.local_issue_references(tmp, 'acme/photos', base)
            self.assertFalse(report['complete'])
            self.assertEqual(report['issues'], [{'number': 11, 'commits': [near]}])
            for commit_id in (long, wide):
                self.assertIn(f'Commit {commit_id} is larger than 65536 bytes; its message was not read', report['errors'])
            self.assertEqual(report['commits_scanned'], 1)

    def raw_commit(self, git, message, literally=False):
        head = git('rev-parse', 'HEAD')
        prefix = (f'tree {git("rev-parse", "HEAD^{tree}")}\nparent {head}\n'
                  'author T <t@e> 1700000000 +0000\ncommitter T <t@e> 1700000000 +0000\n\n').encode()
        body = prefix + (message if isinstance(message, bytes) else message.encode())
        argv = ['git', '-C', git.directory, 'hash-object', '-w', '-t', 'commit', '--stdin'] + (['--literally'] if literally else [])
        sha = subprocess.run(argv, input=body, capture_output=True, check=True).stdout.decode().strip()
        git('update-ref', git('symbolic-ref', 'HEAD'), sha)
        return sha, len(body)

    def test_exact_object_size_boundary(self):
        # Review mutant C-M11: accept exactly 65,536 bytes, refuse 65,537, independent of the constant.
        with tempfile.TemporaryDirectory() as tmp:
            git, base = checkout(tmp)
            sha, size = self.raw_commit(git, 'Fix #1 ')
            pad = 65536 - size
            git('update-ref', git('symbolic-ref', 'HEAD'), base)
            sha, size = self.raw_commit(git, 'Fix #1 ' + 'x' * pad)
            self.assertEqual(size, 65536)
            report = workspace.local_issue_references(tmp, 'acme/photos', base)
            self.assertEqual((report['complete'], report['issues']), (True, [{'number': 1, 'commits': [sha]}]))
            git('update-ref', git('symbolic-ref', 'HEAD'), base)
            sha, size = self.raw_commit(git, 'Fix #1 ' + 'x' * (pad + 1))
            self.assertEqual(size, 65537)
            report = workspace.local_issue_references(tmp, 'acme/photos', base)
            self.assertFalse(report['complete'])
            self.assertEqual(report['issues'], [])

    def test_nul_bearing_commit_message_is_incomplete_not_shortened(self):
        # Review R11-03: %B stops at an embedded NUL, so a later 'Fix #1' vanished from a complete report.
        with tempfile.TemporaryDirectory() as tmp:
            git, base = checkout(tmp)
            sha, _ = self.raw_commit(git, b'Unrelated text\0Fix #1\n', literally=True)
            report = workspace.local_issue_references(tmp, 'acme/photos', base)
            self.assertFalse(report['complete'])
            self.assertEqual(report['issues'], [])
            self.assertIn(f'Commit {sha} has a NUL byte in its message; it was not read', report['errors'])
            client = SignalGitHub()
            client.commit = base
            code, result = run(client, 'discover', 'acme/photos', '--signals', '--repo-dir', tmp)
            self.assertEqual(code, 1)
            self.assertEqual({item['signals']['local_work']['value'] for item in result['issues']}, {'unknown'})

    def test_only_the_message_is_parsed_not_the_commit_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            git, base = checkout(tmp)
            git('commit', '-q', '--allow-empty', '--author', 'Fixer #7 <fixer@example.org>', '-m', 'Fixes #8')
            report = workspace.local_issue_references(tmp, 'acme/photos', base)
            self.assertEqual([item['number'] for item in report['issues']], [8])

    def test_total_message_bytes_are_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            git, base = checkout(tmp)
            import_commits(git, [f'Step {n} fixes #12 ' + 'y' * 60000 for n in range(72)])
            report = workspace.local_issue_references(tmp, 'acme/photos', base)
            self.assertFalse(report['complete'])
            self.assertIn('Local commit messages exceed 4194304 bytes in total; only the newest commits within that '
                          'bound were read', report['errors'])
            self.assertLess(report['commits_scanned'], 72)
            self.assertEqual(report['issues'][0]['number'], 12)

    def test_the_500_commit_limit_is_exact(self):
        # Review mutant R11-M03: the earlier test patched the limit, so 500 itself was never pinned.
        with tempfile.TemporaryDirectory() as tmp:
            git, base = checkout(tmp)
            import_commits(git, [f'Step {n}' for n in range(500)])
            report = workspace.local_issue_references(tmp, 'acme/photos', base)
            self.assertEqual((report['complete'], report['commits_scanned'], report['commit_limit']), (True, 500, 500))
            import_commits(git, ['One more for #12'])
            report = workspace.local_issue_references(tmp, 'acme/photos', base)
            self.assertFalse(report['complete'])
            self.assertEqual(report['commits_scanned'], 500)
            self.assertIn('More than 500 local commits after the source default branch; only the newest 500 were read',
                          report['errors'])

    def test_shallow_checkout_is_incomplete_even_when_the_base_is_present(self):
        # Review R11-02: a shallow boundary can hide intermediate commits while git log still succeeds.
        with tempfile.TemporaryDirectory() as tmp:
            git, base = checkout(tmp)
            commit(git, 'Fix #12')
            tip = commit(git, 'Unrelated')
            pathlib.Path(tmp, '.git', 'shallow').write_text(tip + '\n')
            report = workspace.local_issue_references(tmp, 'acme/photos', base)
            self.assertFalse(report['complete'])
            self.assertEqual(report['issues'], [])
            self.assertEqual(report['errors'], ['Checkout is shallow, so local history may be missing; deepen it with '
                                                'your own tools (git fetch --unshallow) and retry'])
            client = SignalGitHub()
            client.commit = base
            code, result = run(client, 'discover', 'acme/photos', '--signals', '--repo-dir', tmp)
            self.assertEqual(code, 1)
            self.assertEqual({item['signals']['local_work']['value'] for item in result['issues']}, {'unknown'})

    def test_cli_exit_usage_and_no_gate_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            git, base = checkout(tmp)
            commit(git, 'Fix #12')
            client = SignalGitHub()
            client.commit = 'f' * 40
            code, result = run(client, 'discover', 'acme/photos', '--signals', '--repo-dir', tmp)
            self.assertEqual(code, 1)
            self.assertFalse(result['local_work']['complete'])
            self.assertTrue(result['complete'])
            self.assertEqual({item['signals']['local_work']['value'] for item in result['issues']}, {'unknown'})
            for item in result['issues']:
                self.assertEqual((item['exclusions'], item['duplicates']), ([], []))
            unresolved = SignalGitHub()
            unresolved.failed = {'repos/acme/photos'}
            code, result = run(unresolved, 'discover', 'acme/photos', '--signals', '--repo-dir', tmp)
            self.assertEqual(code, 1)
            self.assertEqual(result['local_work']['errors'],
                             ['Discovery did not resolve a source snapshot; the checkout was not read'])
            code, result = run(SignalGitHub(), 'discover', 'acme/photos', 'acme/other', '--repo-dir', tmp)
            self.assertEqual((code, result['error']['code']), (2, 'usage'))


if __name__ == '__main__':
    unittest.main()
