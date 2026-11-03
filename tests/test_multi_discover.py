"""Multi-repository discover: per-repository isolation, legacy single output, bounded input."""
import contextlib
import copy
import io
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from agent_contribute import cli, core, multi
from tests.test_protocol import FakeGitHub
from tests.test_resolution import RepositoryGitHub


class MultiGitHub(RepositoryGitHub):
    """acme/photos (tracker) and person/photos (disabled-tracker fork); other repositories fail."""
    def request(self, endpoint):
        repo = '/'.join(endpoint.split('?')[0].split('/')[1:3])
        if repo not in self.metadata:
            self.calls.append(endpoint)
            raise core.ProtocolError('api_error', 'GitHub read failed')
        return super().request(endpoint)


def run(client, *argv):
    output = io.StringIO()
    with patch.object(core, 'GitHub', return_value=client), contextlib.redirect_stdout(output):
        code = cli.main(list(argv))
    return code, json.loads(output.getvalue())


class MultiDiscoverTests(unittest.TestCase):
    def test_single_repository_output_is_the_legacy_output(self):
        for argv in (['discover', 'acme/photos'],):
            code, result = run(FakeGitHub(), *argv)
            # The CLI adds only the default-on, report-only repository_policy to the core result.
            self.assertEqual(result.pop('repository_policy')['report'], 'policy-report/1')
            direct = core.discover('acme/photos', FakeGitHub())
            for value in (result, direct):
                value.pop('fetched_at')
                value['tipjar'].pop('fetched_at')
                for read in value['resolution_provenance']['metadata_reads']:
                    read.pop('fetched_at')
            self.assertEqual(result, direct)
        with tempfile.TemporaryDirectory() as tmp:
            listing = pathlib.Path(tmp, 'repos.txt')
            listing.write_text('# one\nacme/photos\n\n')
            code, result = run(FakeGitHub(), 'discover', '--repositories-file', str(listing))
            self.assertNotIn('repositories', result)
            self.assertEqual(result['repository'], 'acme/photos')

    def test_failure_is_isolated_and_marks_only_the_run_incomplete(self):
        code, result = run(MultiGitHub(), 'discover', 'acme/photos', 'broken/repo', 'person/photos')
        self.assertEqual(code, 1)
        self.assertFalse(result['complete'])
        by = {r['requested_repository']: r for r in result['repositories']}
        self.assertTrue(by['acme/photos']['complete'])
        self.assertTrue(by['person/photos']['complete'])
        self.assertFalse(by['broken/repo']['complete'])
        self.assertTrue(all(e.startswith('broken/repo: ') for e in result['errors']))
        self.assertEqual({c['reference'] for c in result['candidates']}, {'acme/photos#12', 'person/photos#12'})
        self.assertTrue(all(c['complete'] for c in result['candidates']))

    def test_malformed_unicode_in_one_repository_never_aborts_the_others(self):
        # R1-07: a lone surrogate escape parses as JSON; it must become a per-repository error.
        class SurrogateGitHub(RepositoryGitHub):
            def __init__(self):
                super().__init__()
                for name in ('good/first', 'good/last'):
                    self.metadata[name] = dict(full_name=name, default_branch='main', fork=False, has_issues=True)
                    self.repos[name] = FakeGitHub()

            def request(self, endpoint):
                value = super().request(endpoint)
                if endpoint.startswith('repos/acme/photos/issues?'):
                    value[0]['body'] = 'LONE-SURROGATE'
                    # Parse the wire text exactly as GitHub.request does.
                    return core.strict_json(json.dumps(value).replace('"LONE-SURROGATE"', '"\\ud800"'))
                return value

        client = SurrogateGitHub()
        code, result = run(client, 'discover', 'good/first', 'acme/photos', 'good/last')
        self.assertEqual(code, 1)
        self.assertNotIn('error', result)
        by = {r['requested_repository']: r for r in result['repositories']}
        self.assertTrue(by['good/first']['complete'])
        self.assertTrue(by['good/last']['complete'])
        self.assertFalse(by['acme/photos']['complete'])
        self.assertIn('Invalid JSON: a string is not valid Unicode', ' '.join(by['acme/photos']['errors']))
        self.assertTrue(any(call.startswith('repos/good/last/issues?') for call in client.calls))

    def test_strict_json_rejects_lone_surrogates_but_keeps_valid_pairs(self):
        for text in ('"\\ud800"', '"x\\udc00"', '{"\\ud800": 1}', '["ok", {"a": "\\udfff"}]'):
            with self.subTest(text=text):
                with self.assertRaises(core.ProtocolError) as caught:
                    core.strict_json(text)
                self.assertEqual(caught.exception.code, 'invalid_json')
        self.assertEqual(core.strict_json('"\\ud83d\\ude00"'), '\U0001f600')

    def test_candidate_from_incomplete_repository_is_incomplete(self):
        partial = core.discover('acme/photos', FakeGitHub())
        self.assertTrue(partial['issues'][0]['complete'])
        partial.update(complete=False, errors=['Synthetic repository-level read failure'])
        complete = core.discover('acme/photos', FakeGitHub())
        with patch.object(core, 'discover', side_effect=[copy.deepcopy(partial), complete]):
            result = multi.discover_many(['acme/photos', 'other/photos'], FakeGitHub())
        self.assertFalse(result['complete'])
        self.assertEqual([(c['repository'], c['complete']) for c in result['candidates']],
                         [('acme/photos', False), ('other/photos', True)])

    def test_all_complete_and_deterministic_merged_order(self):
        first = run(MultiGitHub(), 'discover', 'person/photos', 'acme/photos', '--signals')[1]
        second = run(MultiGitHub(), 'discover', 'acme/photos', 'person/photos', '--signals')[1]
        self.assertTrue(first['complete'])
        self.assertEqual([c['reference'] for c in first['candidates']], [c['reference'] for c in second['candidates']])
        self.assertIn('higher signal score', first['ordering'])

    def test_bounds_duplicates_and_invalid_identifiers(self):
        too_many = ['o/r%d' % i for i in range(multi.MAX_REPOSITORIES + 1)]
        for argv in [too_many, ['acme/photos', 'ACME/photos'], ['acme/photos', '--x;id'], []]:
            client = MultiGitHub()
            code, result = run(client, 'discover', *argv)
            self.assertNotEqual(code, 0)
            self.assertIn('error', result)
            self.assertEqual(client.calls, [], 'invalid input must be rejected before any read')
        with tempfile.TemporaryDirectory() as tmp:
            big = pathlib.Path(tmp, 'big.txt')
            big.write_text('a/b\n' * 40000)
            self.assertEqual(run(MultiGitHub(), 'discover', '--repositories-file', str(big))[1]['error']['code'], 'file_error')

    def test_no_repository_names_the_missing_reference(self):
        message = 'the following arguments are required: reference (or a non-empty --repositories-file)'
        with tempfile.TemporaryDirectory() as tmp:
            empty = pathlib.Path(tmp, 'empty.txt')
            empty.write_text('# none\n\n')
            for argv in [('discover',), ('discover', '--repositories-file', str(empty)),
                         ('--report-budget', 'discover')]:
                with self.subTest(argv=argv):
                    client = MultiGitHub()
                    code, result = run(client, *argv)
                    self.assertEqual((code, result['error']), (2, {'code': 'usage', 'message': message}))
                    self.assertEqual(client.calls, [])


if __name__ == '__main__':
    unittest.main()
