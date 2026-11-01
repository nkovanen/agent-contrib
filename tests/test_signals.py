"""Opt-in ranking signals: deterministic, explained, no extra reads, default output frozen."""
import contextlib
import copy
import datetime as dt
import io
import json
import time
import unittest
from unittest.mock import patch

from agent_contribute import cli, core, signals
from tests.test_protocol import FakeGitHub

NOW = dt.datetime(2030, 1, 1, tzinfo=dt.timezone.utc)
PATHS = ['README.md', 'src/thumb.rs', 'src/lib/decode.py', 'docs/a/util.py', 'tests/b/util.py']


class SignalGitHub(FakeGitHub):
    """Two issues so ordering by signal score is observable."""
    def request(self, endpoint):
        path = endpoint.split('?')[0]
        if path.endswith('/issues') and endpoint.startswith('repos/acme/photos/issues'):
            base = super().request('repos/acme/photos/issues/12')
            vague = dict(copy.deepcopy(base), number=3, title='Thumbnails broken', body='They break sometimes.',
                         html_url='https://github.com/acme/photos/issues/3')
            clear = dict(copy.deepcopy(base), number=12, author_association='MEMBER',
                         body='Crash in src/thumb.rs:10\n- [ ] bounds check\n## Expected\nerror\n```\ntrace\n```')
            return [vague, clear]
        if '/git/trees/' in path:
            tree = super().request(endpoint)
            tree['tree'].append({'path': 'src/thumb.rs', 'type': 'blob'})
            return tree
        return super().request(endpoint)


class ExtractorTests(unittest.TestCase):
    def test_paths_stack_frames_and_unique_basenames(self):
        text = ('See ./src/thumb.rs:12 and File "/home/u/proj/src/lib/decode.py", line 3. '
                'decode.py again; util.py is ambiguous; ../../etc/passwd; src/missing.rs.')
        result = signals.location_hints(text, PATHS)
        self.assertEqual(result['value'], 'found')
        self.assertEqual(result['hints'], ['src/thumb.rs', 'src/lib/decode.py'])
        self.assertTrue(result['explanation'])

    def test_traversal_strings_are_lookups_never_paths(self):
        result = signals.location_hints('../../../../etc/passwd /etc/shadow C:\\Windows\\x.dll', PATHS)
        self.assertEqual((result['value'], result['hints']), ('none', []))

    def test_truncated_tree_is_unknown_not_none(self):
        self.assertEqual(signals.location_hints('src/thumb.rs', None)['value'], 'unknown')

    def test_adversarial_input_is_bounded_and_linear(self):
        for text in ['a/' * 200000, 'a.' * 200000, ('x' * 299 + '/') * 2000, '- [ ' * 100000, '`' * 300000,
                     ' ' * 8 + 'expected' * 50000]:
            started = time.monotonic()
            signals.issue_signals({'title': 't', 'body': text}, PATHS * 2000, NOW)
            self.assertLess(time.monotonic() - started, 2.0)
        hints = signals.location_hints(' '.join('src/f%d.rs' % i for i in range(100)),
                                       ['src/f%d.rs' % i for i in range(100)])['hints']
        self.assertEqual(len(hints), signals.MAX_HINTS)

    def test_acceptance_clarity_levels(self):
        self.assertEqual(signals.acceptance_clarity('plain text')['value'], 'low')
        self.assertEqual(signals.acceptance_clarity('- [ ] a')['value'], 'medium')
        high = signals.acceptance_clarity('Steps to reproduce:\n1. x\n**Expected** y\n```\nz\n```')
        self.assertEqual((high['value'], high['markers']), ('high', ['expected/actual sections', 'reproduction steps', 'code block']))

    def test_activity_and_maintainer_tolerate_malformed_payloads(self):
        issue = {'created_at': '2029-12-01T00:00:00Z', 'updated_at': 'yesterday', 'comments': True,
                 'reactions': {'total_count': 4}, 'author_association': 'OWNER'}
        self.assertEqual(signals.activity(issue, NOW)['value'],
                         {'age_days': 31, 'updated_days': None, 'comments': None, 'reactions': 4})
        self.assertEqual(signals.maintainer_signal(issue)['value'], 'maintainer')
        self.assertEqual(signals.maintainer_signal({'author_association': 'CONTRIBUTOR'})['value'], 'other')
        self.assertEqual(signals.maintainer_signal({'author_association': 7})['value'], 'unknown')


class DiscoverSignalTests(unittest.TestCase):
    def test_default_discover_is_unchanged_and_makes_the_same_reads(self):
        plain, opted = SignalGitHub(), SignalGitHub()
        default = core.discover('acme/photos', plain)
        with_signals = core.discover('acme/photos', opted, signals=True)
        self.assertEqual(plain.calls, opted.calls, 'signals must not add reads')
        self.assertNotIn('ordering', default)
        self.assertTrue(all('signals' not in issue for issue in default['issues']))
        stripped = copy.deepcopy(with_signals)
        stripped.pop('ordering')
        for issue in stripped['issues']:
            issue.pop('signals')
        stripped['issues'].sort(key=lambda issue: issue['number'])
        default['issues'].sort(key=lambda issue: issue['number'])
        for result in (stripped, default):
            result.pop('fetched_at')
            for read in result['resolution_provenance']['metadata_reads']:
                read.pop('fetched_at')
        self.assertEqual(stripped, default)

    def test_signals_reorder_only_after_exclusions_and_overlap(self):
        self.assertEqual([i['number'] for i in core.discover('acme/photos', SignalGitHub())['issues']], [3, 12])
        result = core.discover('acme/photos', SignalGitHub(), signals=True)
        self.assertEqual([i['number'] for i in result['issues']], [12, 3])
        top = result['issues'][0]['signals']
        self.assertEqual(top['code_location']['hints'], ['src/thumb.rs'])
        self.assertEqual(top['maintainer']['value'], 'maintainer')
        overlapping = SignalGitHub(prs=[{'number': 9, 'title': 'x', 'body': 'Fixes #12',
                                         'html_url': 'https://github.com/acme/photos/pull/9'}])
        self.assertEqual([i['number'] for i in core.discover('acme/photos', overlapping, signals=True)['issues']], [3, 12])

    def test_malformed_remote_signal_fields_degrade_through_cli(self):
        for malformed in ([], {}, None, -7):
            with self.subTest(malformed=malformed):
                client = SignalGitHub()
                original = client.request
                def request(endpoint, original=original, malformed=malformed):
                    value = original(endpoint)
                    if endpoint.startswith('repos/acme/photos/issues?'):
                        # updated_at is a required issue field validated by issue_data; leave it intact.
                        value = [dict(item, author_association=malformed, created_at=malformed,
                                      comments=malformed, reactions=malformed) for item in value]
                    return value
                client.request = request
                output = io.StringIO()
                with patch.object(core, 'GitHub', return_value=client), contextlib.redirect_stdout(output):
                    code = cli.main(['discover', 'acme/photos', '--signals'])
                result = json.loads(output.getvalue())
                self.assertEqual(code, 0, result)
                for issue in result['issues']:
                    self.assertEqual(issue['signals']['maintainer']['value'], 'unknown')
                    activity = issue['signals']['activity']['value']
                    self.assertEqual({activity[k] for k in ('age_days', 'comments', 'reactions')}, {None})
                    self.assertNotEqual(issue['approval']['status'], 'approved')

    def test_cli_flag_is_opt_in(self):
        client = SignalGitHub()
        for argv, expected in [(['discover', 'acme/photos'], False), (['discover', 'acme/photos', '--signals'], True)]:
            output = io.StringIO()
            with patch.object(core, 'GitHub', return_value=client), contextlib.redirect_stdout(output):
                self.assertEqual(cli.main(argv), 0)
            self.assertEqual('signals' in json.loads(output.getvalue())['issues'][0], expected)


if __name__ == '__main__':
    unittest.main()
