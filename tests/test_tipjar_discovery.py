"""Welcome selection is a projection after full scans, never source approval."""
import base64
import contextlib
import copy
import hashlib
import io
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from agent_contribute import cli, core, multi, outputs, tipjar
from tests.test_resolution import RepositoryGitHub


class SourcesGitHub(RepositoryGitHub):
    def __init__(self, states):
        super().__init__()
        self.states = states
        self.metadata['person/photos']['has_issues'] = True

    def request_once(self, endpoint):
        name = '/'.join(endpoint.split('/')[1:3])
        state = self.states.get(name)
        data = json.dumps({'schema_version': '0.1', 'status': state}).encode()
        if '/contents/.tipjar.json?' in endpoint:
            self.calls.append(endpoint)
            return {'path': tipjar.PATH, 'type': 'file', 'encoding': 'base64', 'size': len(data),
                    'sha': tipjar.cache.blob_sha(data), 'content': base64.b64encode(data).decode()}
        result = super().request_once(endpoint)
        if '/git/trees/' in endpoint and state is not None:
            result['tree'].append({'path': tipjar.PATH, 'sha': tipjar.cache.blob_sha(data),
                                   'type': 'blob', 'mode': '100644'})
        return result


class TipjarDiscoveryTests(unittest.TestCase):
    def test_explicit_no_jar_still_discovers_and_prepares(self):
        client = SourcesGitHub({})
        found = core.discover('acme/photos', client)
        self.assertTrue(found['selection']['included'])
        self.assertEqual(found['tipjar']['state'], 'undeclared')
        self.assertTrue(found['issues'])
        self.assertEqual(core.prepare(core.inspect_issue(found['issues'][0]['reference'], client))['execution']['mode'], 'pending')

    def test_welcomed_filter_includes_only_declared_sources(self):
        client = SourcesGitHub({'acme/photos': 'welcome'})
        found = multi.discover_many(['acme/photos', 'person/photos'], client, welcomed_only=True, limit=1)
        self.assertTrue(found['complete'])
        self.assertEqual([c['repository'] for c in found['candidates']], ['acme/photos'])
        self.assertEqual(found['repositories'][1]['tipjar']['state'], 'undeclared')
        self.assertEqual(found['repositories'][1]['issues'], [])
        self.assertTrue(found['repositories'][1]['issue_scan']['complete'])
        self.assertTrue(any('repos/person/photos/issues?' in call for call in client.calls))

    def test_mixed_unknown_keeps_exit_one_and_complete_repo_findings(self):
        client = SourcesGitHub({'acme/photos': 'welcome', 'person/photos': 'bad'})
        found = multi.discover_many(['acme/photos', 'person/photos'], client, welcomed_only=True)
        self.assertFalse(found['complete'])
        self.assertTrue(found['errors'])
        self.assertTrue(found['repositories'][0]['complete'])
        self.assertTrue(found['repositories'][0]['issues'])
        self.assertEqual(found['repositories'][1]['tipjar']['state'], 'unknown')
        self.assertFalse(found['repositories'][1]['selection']['included'])

    def test_all_undeclared_is_complete_empty_selection(self):
        found = multi.discover_many(['acme/photos', 'person/photos'], SourcesGitHub({}), welcomed_only=True)
        self.assertTrue(found['complete'])
        self.assertEqual(found['candidates'], [])
        self.assertTrue(all(not r['issues'] for r in found['repositories']))

    def test_fork_jar_cannot_replace_parent_source_jar(self):
        client = SourcesGitHub({'acme/photos': 'closed', 'person/photos': 'welcome'})
        client.metadata['person/photos']['has_issues'] = False
        found = core.discover('person/photos', client, welcomed_only=True)
        self.assertEqual(found['tipjar']['repository'], 'acme/photos')
        self.assertEqual(found['tipjar']['state'], 'closed')
        self.assertFalse(found['selection']['included'])
        self.assertFalse(any('/contents/.tipjar.json?' in c and 'person/photos' in c for c in client.calls))

    def test_enabled_tracker_fork_uses_own_jar(self):
        found = core.discover('person/photos', SourcesGitHub({'acme/photos': 'closed', 'person/photos': 'welcome'}), welcomed_only=True)
        self.assertEqual(found['tipjar']['repository'], 'person/photos')
        self.assertTrue(found['selection']['included'])
        self.assertEqual(found['issues'][0]['approval']['status'], 'candidate')

    def test_filter_does_not_promote_or_waive_overlap(self):
        client = SourcesGitHub({'acme/photos': 'welcome'})
        client.repos['acme/photos'].prs = [{'number': 30, 'title': 'Existing change', 'body': 'Fixes #12',
            'html_url': 'https://github.com/acme/photos/pull/30', 'head': None}]
        ordinary = core.discover('acme/photos', client, signals=True)
        filtered = core.discover('acme/photos', client, signals=True, welcomed_only=True)
        self.assertEqual(ordinary['issues'], filtered['issues'])
        self.assertTrue(filtered['issues'][0]['duplicates'])

    def test_default_closed_findings_are_diagnostic_not_combined_candidates(self):
        found = multi.discover_many(['acme/photos', 'person/photos'], SourcesGitHub({'acme/photos': 'closed'}))
        self.assertTrue(found['complete'])
        self.assertTrue(found['repositories'][0]['issues'])
        self.assertFalse(found['repositories'][0]['selection']['included'])
        self.assertEqual([c['repository'] for c in found['candidates']], ['person/photos'])

    def test_parser_single_list_and_file_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'repos.txt'
            path.write_text('acme/photos\nperson/photos\n')
            for args in (['acme/photos'], ['acme/photos', 'person/photos'], ['--repositories-file', str(path)]):
                out = io.StringIO()
                with patch.object(core, 'GitHub', return_value=SourcesGitHub({'acme/photos': 'welcome'})), contextlib.redirect_stdout(out):
                    code = cli.main(['discover', *args, '--welcomed-only', '--limit', '1'])
                self.assertEqual(code, 0)
                found = json.loads(out.getvalue())
                for result in found.get('repositories', [found]):
                    self.assertEqual(result['selection']['mode'], 'welcomed-only')

    def test_output2_selection_schema_reserves_both_modes(self):
        schema = outputs.output_schema('discover')
        selection = schema['$defs']['discover_result']['properties']['selection']
        self.assertEqual(selection['properties']['mode']['enum'], ['explicit', 'welcomed-only'])
        found = core.discover('acme/photos', SourcesGitHub({'acme/photos': 'welcome'}))
        for mode in ('explicit', 'welcomed-only'):
            found['selection']['mode'] = mode
            self.assertEqual(core.schema_errors(found, schema), [])
        found['selection']['mode'] = 'force'
        self.assertTrue(core.schema_errors(found, schema))
