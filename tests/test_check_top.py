"""discover --signals --check-top N: bounded ownership reads for the top N only, re-ranked within N, report only."""
import contextlib
import copy
import datetime as dt
import io
import json
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from agent_contribute import cli, core, signals
from tests.test_ownership import pull, xref
from tests.test_protocol import FakeGitHub

FRESH = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=2)).isoformat()


def issue(number, assignees=()):
    return {'number': number, 'state': 'open', 'title': f'Task {number}', 'body': 'Details',
            'labels': [], 'assignees': [{'login': login} for login in assignees],
            'html_url': f'https://github.com/acme/photos/issues/{number}', 'updated_at': '2026-11-01T00:00:00Z'}


def comment(identity, body, created):
    return {'id': identity, 'user': {'login': 'carol', 'id': 41}, 'author_association': 'NONE', 'body': body,
            'created_at': created}


class CheckGitHub(FakeGitHub):
    """Six equal-score issues. 1: merged same-repo fix. 2: fresh claim. 3: assigned. 4: merged fix elsewhere.
    5: stale claim. 6: would be demoted, but is below the checked range. 7: overlaps an open PR, so it sorts last."""
    def __init__(self):
        super().__init__(prs=[{'number': 70, 'title': 'Other', 'body': 'Fixes #7', 'head': None,
                               'html_url': 'https://github.com/acme/photos/pull/70'}])
        self.issues = [issue(n, ['alice'] if n == 3 else ()) for n in range(1, 8)]
        self.timelines = {1: [xref('acme/photos', 31)], 4: [xref('third/party', 9)], 6: [xref('acme/photos', 31)]}
        self.comments = {2: [comment(10, "I'm working on this", FRESH)],
                         5: [comment(11, "I'm working on this", '2020-01-01T00:00:00Z')]}
        self.details = {'repos/acme/photos/pulls/31': pull('acme/photos', 31, 'Fixes #1 and #6', 'closed', merged=True),
                        'repos/third/party/pulls/9': pull('third/party', 9, 'Fixes acme/photos#4', 'closed', merged=True)}

    def request(self, endpoint):
        path = endpoint.split('?')[0]
        parts = path.split('/')
        if path == 'repos/acme/photos/issues':
            self.calls.append(endpoint)
            return copy.deepcopy(self.issues)
        if len(parts) == 6 and parts[3] == 'issues' and parts[5] in ('timeline', 'comments'):
            self.calls.append(endpoint)
            source = self.timelines if parts[5] == 'timeline' else self.comments
            return copy.deepcopy(source.get(int(parts[4]), []))
        if path in self.details:
            self.calls.append(endpoint)
            return copy.deepcopy(self.details[path])
        return super().request(endpoint)


def run(client, *argv):
    output = io.StringIO()
    with patch.object(core, 'GitHub', return_value=client), contextlib.redirect_stdout(output):
        code = cli.main(list(argv))
    return code, json.loads(output.getvalue())


def ownership_reads(client):
    return [call for call in client.calls if '/timeline' in call or '/comments' in call or '/pulls/' in call]


class CheckTopTests(unittest.TestCase):
    def test_demoted_top_n_issues_move_below_every_other_candidate(self):
        client = CheckGitHub()
        code, result = run(client, 'discover', 'acme/photos', '--signals', '--check-top', '5')
        self.assertEqual(code, 0)
        self.assertEqual([item['number'] for item in result['issues']], [2, 4, 5, 6, 1, 3, 7])
        checks = {item['number']: item.get('top_check') for item in result['issues']}
        self.assertIsNone(checks[6])
        self.assertIsNone(checks[7])
        self.assertEqual(checks[1]['demotions'], ['possibly already fixed by a merged same-repository PR: '
                                                  'https://github.com/acme/photos/pull/31'])
        self.assertEqual(checks[2]['demotions'], [])  # a fresh claim comment is report-only
        self.assertEqual(checks[3]['demotions'], ['assigned to alice'])
        self.assertEqual((checks[4]['demotions'], checks[5]['demotions']), ([], []))
        self.assertTrue(all(checks[n]['complete'] for n in range(1, 6)))
        self.assertEqual({n: checks[n]['reads'] for n in range(1, 6)}, {1: 3, 2: 2, 3: 2, 4: 3, 5: 2})
        self.assertFalse([call for call in ownership_reads(client) if '/issues/6/' in call])
        self.assertEqual(result['top_check'], {'requested': 5, 'checked': 5, 'reads': 12, 'read_cap': 30,
                                               'complete': True, 'notice': signals.CHECK_TOP_NOTICE})
        self.assertIn('--check-top', result['ordering'])
        for number in (1, 2, 3):
            entry = next(item for item in result['issues'] if item['number'] == number)
            self.assertEqual((entry['duplicates'], entry['exclusions'], entry['approval']['status']), ([], [], 'candidate'))

    def test_claim_comments_never_demote(self):
        # Coordinator decision after review R8-03/R8-07: claims are visible only in the ownership report.
        for body, association in [("I'm working on this", 'NONE'), ('/assign', 'FIRST_TIME_CONTRIBUTOR'),
                                  ('Can I take this?', 'CONTRIBUTOR'), ('\u201c' * 50000, 'NONE')]:
            with self.subTest(body=body[:20]):
                client = CheckGitHub()
                client.timelines = {}
                client.comments = {1: [dict(comment(10, body, FRESH), author_association=association)]}
                code, result = run(client, 'discover', 'acme/photos', '--signals', '--check-top', '1')
                self.assertEqual(code, 0)
                self.assertEqual(result['issues'][0]['number'], 1)
                self.assertEqual(result['issues'][0]['top_check']['demotions'], [])
        self.assertFalse(hasattr(signals, 'ranking_claim'))

    def test_smaller_n_checks_only_that_many_but_demotes_below_all(self):
        client = CheckGitHub()
        client.comments = {}
        code, result = run(client, 'discover', 'acme/photos', '--signals', '--check-top', '2')
        self.assertEqual([item['number'] for item in result['issues']], [2, 3, 4, 5, 6, 1, 7])
        self.assertEqual([item['number'] for item in result['issues'] if 'top_check' in item], [2, 1])
        self.assertEqual(result['issues'][0]['top_check']['demotions'], [])
        self.assertFalse([call for call in ownership_reads(client) if '/issues/3/' in call])

    def test_assignees_appear_only_with_check_top(self):
        # Review R8-06: plain --signals output must not gain the check-top input field.
        code, plain = run(CheckGitHub(), 'discover', 'acme/photos', '--signals')
        self.assertFalse([item for item in plain['issues'] if 'assignees' in item['signals']])
        code, checked = run(CheckGitHub(), 'discover', 'acme/photos', '--signals', '--check-top', '1')
        self.assertEqual({item['number']: item['signals']['assignees'] for item in checked['issues']}[3], ['alice'])

    def test_default_and_plain_signals_make_no_ownership_reads(self):
        for argv in (['discover', 'acme/photos'], ['discover', 'acme/photos', '--signals']):
            with self.subTest(argv=argv):
                client = CheckGitHub()
                code, result = run(client, *argv)
                self.assertEqual(code, 0)
                self.assertEqual(ownership_reads(client), [])
                self.assertNotIn('top_check', result)
                self.assertEqual([item['number'] for item in result['issues']], [1, 2, 3, 4, 5, 6, 7])

    def test_per_issue_page_cap_and_total_read_cap_mark_checks_incomplete(self):
        client = CheckGitHub()
        client.timelines[4] = [{'id': 1000 + i, 'event': 'labeled'} for i in range(100)]
        code, result = run(client, 'discover', 'acme/photos', '--signals', '--check-top', '5')
        check = next(item for item in result['issues'] if item['number'] == 4)['top_check']
        self.assertFalse(check['complete'])
        self.assertIn('Pagination reached the 1-page limit', check['errors'])
        self.assertFalse([call for call in client.calls if '/issues/4/timeline' in call and 'page=2' in call])
        self.assertFalse(result['top_check']['complete'])
        self.assertEqual(code, 1)
        client = CheckGitHub()
        with patch.object(signals, 'CHECK_READ_CAP', 5):
            code, result = run(client, 'discover', 'acme/photos', '--signals', '--check-top', '5')
        self.assertEqual(len(ownership_reads(client)), 5)
        self.assertEqual(result['top_check']['reads'], 5)
        checks = {item['number']: item['top_check'] for item in result['issues'] if 'top_check' in item}
        self.assertEqual({n: check['reads'] for n, check in checks.items()}, {1: 3, 2: 2, 3: 0, 4: 0, 5: 0})
        for number in (3, 4, 5):
            self.assertFalse(checks[number]['complete'])
            self.assertIn('Total --check-top read cap of 5 reached', checks[number]['errors'])
        self.assertEqual(checks[3]['demotions'], ['assigned to alice'])  # the listing already showed the assignee
        self.assertEqual(code, 1)

    def test_cap_counts_transport_attempts_because_retries_are_off(self):
        # Review R8-04: GitHub.request retries transient errors up to three times; check reads must not.
        def failure(argv, **kwargs):
            kwargs['stderr'].write(b'gh: Server Error (HTTP 500)')
            return subprocess.CompletedProcess(argv, 1)
        with patch('subprocess.run', side_effect=failure) as run_gh, patch('time.sleep'):
            with self.assertRaises(core.ProtocolError):
                core.GitHub().request_once('repos/acme/photos/issues/1/timeline')
            self.assertEqual(run_gh.call_count, 1)
            with self.assertRaises(core.ProtocolError) as raised:
                core.GitHub().request('repos/acme/photos/issues/1/timeline')
            self.assertEqual(run_gh.call_count, 4)
            self.assertEqual(str(raised.exception), 'GitHub GET failed; check gh auth, access and rate limits')

        class OnceGitHub(CheckGitHub):
            def request_once(self, endpoint):
                if '/timeline' in endpoint or '/comments' in endpoint or '/pulls/' in endpoint:
                    self.once = getattr(self, 'once', 0) + 1
                return super().request_once(endpoint)
        client = OnceGitHub()
        code, result = run(client, 'discover', 'acme/photos', '--signals', '--check-top', '5')
        self.assertEqual(client.once, result['top_check']['reads'])
        self.assertEqual(client.once, len(ownership_reads(client)))
        self.assertIn('without retries', result['top_check']['notice'])

    def test_text_output_shows_top_check_status_demotions_and_errors(self):
        # Review R8-05: text said 'Complete: yes' with no hint why --check-top exited 1.
        client = CheckGitHub()
        client.timelines[4] = [{'id': 1000 + i, 'event': 'labeled'} for i in range(100)]
        output = io.StringIO()
        with patch.object(core, 'GitHub', return_value=client), contextlib.redirect_stdout(output):
            code = cli.main(['--format', 'text', 'discover', 'acme/photos', '--signals', '--check-top', '5'])
        text = output.getvalue()
        self.assertEqual(code, 1)
        self.assertIn('Complete: yes\n', text)
        self.assertIn('Top check: complete no; checked 5 of 5; 11 GitHub reads (cap 30)\n', text)
        self.assertIn('Top check demotions (2):\n  - acme/photos#1: possibly already fixed', text)
        self.assertIn('Top check errors (1):\n  - acme/photos#4: Pagination reached the 1-page limit\n', text)

    def test_local_work_and_check_top_share_one_known_bad_sort(self):
        from tests.test_local_work import checkout, commit
        with tempfile.TemporaryDirectory() as tmp:
            git, base = checkout(tmp)
            commit(git, 'Fix #4')
            client = CheckGitHub()
            client.commit = base
            code, result = run(client, 'discover', 'acme/photos', '--signals', '--check-top', '2', '--repo-dir', tmp)
        self.assertEqual(code, 0)
        # 4 is locally referenced, so the top two checked are 1 and 2; the known-bad 1 and 4 sort together
        # below the other candidates and above the overlapping 7.
        self.assertEqual([item['number'] for item in result['issues']], [2, 3, 5, 6, 1, 4, 7])
        self.assertEqual(sorted(item['number'] for item in result['issues'] if 'top_check' in item), [1, 2])
        self.assertEqual(result['ordering'], core.KNOWN_BAD_ORDERING)
        self.assertFalse([call for call in ownership_reads(client) if '/issues/4/' in call])

    def test_local_work_runs_before_choosing_the_top_n(self):
        # Review mutant C-M07: with the first-ranked issue referenced locally, check-top must skip it.
        from tests.test_local_work import checkout, commit
        with tempfile.TemporaryDirectory() as tmp:
            git, base = checkout(tmp)
            commit(git, 'Fix #1\nFix #4')  # one whole-line trailer per reference
            client = CheckGitHub()
            client.commit = base
            code, result = run(client, 'discover', 'acme/photos', '--signals', '--check-top', '2', '--repo-dir', tmp)
        self.assertEqual(sorted(item['number'] for item in result['issues'] if 'top_check' in item), [2, 3])
        self.assertEqual([item['number'] for item in result['issues']], [2, 5, 6, 1, 3, 4, 7])
        self.assertFalse([call for call in ownership_reads(client) if '/issues/1/' in call])

    def test_pr_detail_cap(self):
        client = CheckGitHub()
        client.timelines[1] = [xref('acme/photos', n) for n in range(40, 46)]
        for n in range(40, 46):
            client.details[f'repos/acme/photos/pulls/{n}'] = pull('acme/photos', n, 'Refs #1')
        code, result = run(client, 'discover', 'acme/photos', '--signals', '--check-top', '1')
        check = result['issues'][0]['top_check']
        # The documented bound is four PR details, independent of the constant (review mutant R8-R2-M03).
        self.assertEqual(check['reads'], 2 + 4)
        self.assertIn('More than 4 cross-referenced PRs; details are incomplete', check['errors'])
        self.assertFalse(check['complete'])

    def test_usage_errors(self):
        for argv in (['discover', 'acme/photos', '--check-top', '3'],
                     ['discover', 'acme/photos', '--signals', '--check-top', '0'],
                     ['discover', 'acme/photos', '--signals', '--check-top', '6'],
                     ['discover', 'acme/photos', 'acme/other', '--signals', '--check-top', '3']):
            with self.subTest(argv=argv):
                client = CheckGitHub()
                code, result = run(client, *argv)
                self.assertEqual((code, result['error']['code']), (2, 'usage'))
                self.assertEqual(client.calls, [])


if __name__ == '__main__':
    unittest.main()
