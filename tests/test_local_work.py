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


class LocalWorkTests(unittest.TestCase):
    def test_references_to_the_same_repository_in_unpublished_commits_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            git, base = checkout(tmp)
            fix = commit(git, 'Bounds check\n\nFixes #12 and refs acme/photos#3; ACME/Photos#3 again')
            commit(git, 'Unrelated: other/repo#5, abc#7, https://x/#8, GH-9 and #0')
            report = workspace.local_issue_references(tmp, 'acme/photos', base)
            self.assertEqual(report['issues'], [{'number': 3, 'commits': [fix]}, {'number': 12, 'commits': [fix]}])
            self.assertEqual((report['complete'], report['commits_scanned'], report['base']), (True, 2, base))
            self.assertEqual(report['head'], git('rev-parse', 'HEAD'))
            # Commits already in the source default branch are not unpublished work.
            self.assertEqual(workspace.local_issue_references(tmp, 'acme/photos', fix)['issues'], [])

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
                                                    'explanation': 'Referenced by 1 local commit(s) not in the source '
                                                                   'default branch; the work may already exist'})
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
                commit(git, f'Step {n} for #12')
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
