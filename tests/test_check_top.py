"""discover --signals --check-top N: bounded ownership reads for the top N only, re-ranked within N, report only."""
import contextlib
import copy
import datetime as dt
import io
import json
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
        self.assertEqual([item['number'] for item in result['issues']], [4, 5, 6, 1, 2, 3, 7])
        checks = {item['number']: item.get('top_check') for item in result['issues']}
        self.assertIsNone(checks[6])
        self.assertIsNone(checks[7])
        self.assertEqual(checks[1]['demotions'], ['possibly already fixed by a merged same-repository PR: '
                                                  'https://github.com/acme/photos/pull/31'])
        self.assertEqual(checks[2]['demotions'], ['claimed in a comment by carol 2 days ago'])
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

    def test_smaller_n_checks_only_that_many_but_demotes_below_all(self):
        client = CheckGitHub()
        client.comments = {}
        code, result = run(client, 'discover', 'acme/photos', '--signals', '--check-top', '2')
        self.assertEqual([item['number'] for item in result['issues']], [2, 3, 4, 5, 6, 1, 7])
        self.assertEqual([item['number'] for item in result['issues'] if 'top_check' in item], [2, 1])
        self.assertEqual(result['issues'][0]['top_check']['demotions'], [])
        self.assertFalse([call for call in ownership_reads(client) if '/issues/3/' in call])

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

    def test_pr_detail_cap(self):
        client = CheckGitHub()
        client.timelines[1] = [xref('acme/photos', n) for n in range(40, 46)]
        for n in range(40, 46):
            client.details[f'repos/acme/photos/pulls/{n}'] = pull('acme/photos', n, 'Refs #1')
        code, result = run(client, 'discover', 'acme/photos', '--signals', '--check-top', '1')
        check = result['issues'][0]['top_check']
        self.assertEqual(check['reads'], 2 + signals.CHECK_PR_DETAILS)
        self.assertIn(f'More than {signals.CHECK_PR_DETAILS} cross-referenced PRs; details are incomplete', check['errors'])
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
