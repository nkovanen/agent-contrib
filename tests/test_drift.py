"""Drift report: per-file baselines from the pinned commit, explicit unknowns, contract untouched."""
import base64
import contextlib
import io
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from agent_contribute import cli, core, drift
from tests.test_authorization import candidate_task
from tests.test_protocol import FakeGitHub, ready_contract

PINNED, LATER = 'a' * 40, 'c' * 40


def advance(client, changes=None, extra=None):
    """Move the default branch to LATER, optionally changing or adding instruction files there."""
    client.commit = LATER
    original = client.request
    def request(endpoint):
        if '/git/trees/' + LATER in endpoint and extra:
            tree = original(endpoint)
            tree['tree'] += [{'path': path, 'type': 'blob'} for path in extra]
            return tree
        if '/contents/' in endpoint and 'ref=' + LATER in endpoint:
            name = endpoint.split('/contents/')[1].split('?')[0]
            if name in (changes or {}) or name in (extra or []):
                client.calls.append(endpoint)
                text = (changes or {}).get(name, 'new file')
                return {'encoding': 'base64', 'content': base64.b64encode(text.encode()).decode()}
        return original(endpoint)
    client.request = request


class DriftTests(unittest.TestCase):
    def test_no_drift(self):
        task, client = ready_contract()
        result = drift.drift(task, client)
        self.assertTrue(result['complete'], result['errors'])
        self.assertIs(result['drifted'], False)
        self.assertTrue(result['instructions']['baseline_verified'])
        self.assertTrue(all('ref=' + PINNED in c for c in client.calls if '/contents/' in c))

    def test_instruction_changes_are_located_per_file(self):
        task, client = ready_contract()
        advance(client, {'AGENTS.md': 'weakened rules'}, extra=['docs/CONTRIBUTING.md'])
        result = drift.drift(task, client)
        self.assertTrue(result['complete'], result['errors'])
        self.assertTrue(result['drifted'])
        self.assertTrue(result['default_branch']['advanced'])
        self.assertEqual([m['path'] for m in result['instructions']['modified']], ['AGENTS.md'])
        self.assertEqual(result['instructions']['added'], ['docs/CONTRIBUTING.md'])
        self.assertEqual(result['instructions']['removed'], [])

    def test_branch_advance_alone_is_not_drift(self):
        task, client = ready_contract()
        advance(client)
        result = drift.drift(task, client)
        self.assertTrue(result['default_branch']['advanced'])
        self.assertIs(result['drifted'], False)

    def test_issue_policy_and_overlap_changes(self):
        task, client = ready_contract()
        original = client.request
        def request(endpoint):
            value = original(endpoint)
            if endpoint.split('?')[0].endswith('/issues/12'):
                value = dict(value, body='Rewritten acceptance', assignees=[{'login': 'mallory'}])
            return value
        client.request = request
        client.labels = []
        client.prs = [{'number': 40, 'title': 'x', 'body': 'Fixes #12', 'html_url': 'https://github.com/acme/photos/pull/40'}]
        result = drift.drift(task, client)
        self.assertTrue(result['issue']['changed'])
        self.assertEqual(result['issue']['current_components']['assignees'], ['mallory'])
        self.assertIn('unavailable', result['issue']['component_baseline'])
        self.assertEqual((result['policy']['stored_approval'], result['policy']['current_approval']), ('approved', 'candidate'))
        self.assertEqual(result['overlap']['added'], ['https://github.com/acme/photos/pull/40'])
        self.assertTrue(result['drifted'])

    def test_schema_02_policy_hash(self):
        task, client = candidate_task()
        result = drift.drift(task, client)
        self.assertIn('stored_policy_sha256', result['policy'])
        self.assertFalse(result['policy']['changed'], result['policy'])

    def test_unreadable_sources_are_incomplete(self):
        task, client = ready_contract()
        client.failed.add('/contents/AGENTS.md?ref=' + PINNED)
        result = drift.drift(task, client)
        self.assertFalse(result['complete'])
        self.assertFalse(result['instructions']['baseline_verified'])
        task, client = ready_contract()
        client.failed.add('repos/acme/photos')
        result = drift.drift(task, client)
        self.assertEqual((result['complete'], result['drifted']), (False, None))
        with self.assertRaises(core.ProtocolError):
            drift.drift({'schema_version': '0.1'}, FakeGitHub())

    def test_cli_never_rewrites_contract(self):
        task, client = ready_contract()
        advance(client, {'AGENTS.md': 'weakened rules'})
        with tempfile.TemporaryDirectory() as tmp:
            contract = pathlib.Path(tmp, 'task.json')
            contract.write_text(json.dumps(task))
            before = contract.read_bytes()
            output = io.StringIO()
            with patch.object(core, 'GitHub', return_value=client), contextlib.redirect_stdout(output):
                code = cli.main(['drift', str(contract)])
            self.assertEqual(code, 1)
            self.assertTrue(json.loads(output.getvalue())['drifted'])
            self.assertEqual(contract.read_bytes(), before)
            self.assertEqual(sorted(p.name for p in pathlib.Path(tmp).iterdir()), ['task.json'])


if __name__ == '__main__':
    unittest.main()
