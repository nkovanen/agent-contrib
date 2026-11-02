"""Drift report: per-file baselines from the pinned commit, explicit unknowns, contract untouched."""
import base64
import contextlib
import io
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from agent_contribute import cli, core, drift, textfmt
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

    def test_source_tracker_switch_is_drift(self):
        # R1-06: the fork disables Issues, so the same reference now resolves to the parent's tracker.
        import copy
        from tests.test_resolution import RepositoryGitHub
        client = RepositoryGitHub()
        client.metadata['person/photos']['has_issues'] = True
        client.repos['person/photos'].policy = copy.deepcopy(client.repos['acme/photos'].policy)
        task = core.prepare(core.inspect_issue('person/photos#12', client))
        client.metadata['person/photos']['has_issues'] = False
        result = drift.drift(task, client)
        self.assertTrue(result['complete'], result['errors'])
        self.assertTrue(result['drifted'], 'a different source tracker is drift')
        self.assertEqual((result['source']['stored_repository'], result['source']['current_repository']),
                         ('person/photos', 'acme/photos'))
        self.assertTrue(result['source']['changed'])
        self.assertTrue(result['drifted'])
        self.assertNotIn('stored_identity', result['source'], 'schema 0.1 stores no numeric identities')
        self.assertIn('  - Source changed: person/photos -> acme/photos\n', textfmt.render('drift', result))

    def test_schema_02_recreated_source_identity_is_drift(self):
        task, client = candidate_task()
        self.assertFalse(drift.drift(task, client)['drifted'])
        client.metadata['id'] = 102  # same canonical name, new repository
        result = drift.drift(task, client)
        self.assertTrue(result['complete'], result['errors'])
        self.assertTrue(result['drifted'], 'a recreated repository is drift')
        self.assertEqual(result['source']['stored_identity']['repository_id'], 101)
        self.assertEqual(result['source']['current_identity']['repository_id'], 102)
        self.assertIn('  - Source issue URL or repository/issue identity changed\n', textfmt.render('drift', result))
        self.assertTrue(result['source']['changed'])
        self.assertTrue(result['drifted'])

    def test_schema_02_unresolved_source_identity_is_incomplete(self):
        task, client = candidate_task()
        issue = client.request('repos/acme/photos/issues/12')
        client.overrides['repos/acme/photos/issues/12'] = dict(issue, repository_url='https://api.github.com/repos/x/y')
        result = drift.drift(task, client)
        self.assertFalse(result['complete'])
        self.assertIn('Could not resolve current source identity: Issue ID or canonical repository URL is unresolved',
                      result['errors'])
        self.assertIsNone(result['source']['current_identity'])

    def test_issue_changing_between_reads_is_incomplete(self):
        task, client = ready_contract()
        original, reads = client.request, [0]
        def request(endpoint):
            value = original(endpoint)
            if endpoint.split('?')[0].endswith('/issues/12'):
                reads[0] += 1
                if reads[0] > 1:
                    value = dict(value, body='Changed acceptance', state='closed')
            return value
        client.request = request
        result = drift.drift(task, client)
        self.assertFalse(result['complete'])
        self.assertIn('Issue changed between reads; rerun drift', result['errors'])
        self.assertIsNone(result['issue']['current_components'])

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

    def assert_single_reason(self, result, reason):
        self.assertTrue(result['complete'], result['errors'])
        self.assertIs(result['drifted'], True)
        reasons = {'issue': result['issue']['changed'], 'instructions': result['instructions']['changed'],
                   'policy': result['policy']['changed'], 'overlap': bool(result['overlap']['added']),
                   'branch': result['default_branch']['stored_branch'] != result['default_branch']['current_branch']}
        self.assertEqual([key for key, value in reasons.items() if value], [reason])

    def test_new_overlapping_pr_alone_is_drift(self):
        task, client = ready_contract()
        client.prs = [{'number': 40, 'title': 'x', 'body': 'Fixes #12', 'html_url': 'https://github.com/acme/photos/pull/40'}]
        result = drift.drift(task, client)
        self.assert_single_reason(result, 'overlap')
        self.assertEqual(result['overlap']['added'], ['https://github.com/acme/photos/pull/40'])

    def test_default_branch_rename_alone_is_drift(self):
        task, client = ready_contract()
        original = client.request
        def request(endpoint):
            path = endpoint.split('?')[0]
            if path == 'repos/acme/photos':
                return dict(original(endpoint), default_branch='trunk')
            if path.endswith('/commits/trunk'):
                return original(endpoint.replace('/commits/trunk', '/commits/main'))
            return original(endpoint)
        client.request = request
        result = drift.drift(task, client)
        self.assert_single_reason(result, 'branch')
        self.assertEqual((result['default_branch']['stored_branch'], result['default_branch']['current_branch']),
                         ('main', 'trunk'))
        self.assertFalse(result['default_branch']['advanced'])

    def test_schema_02_policy_hash_change_alone_is_drift(self):
        task, client = candidate_task()
        client.policy = {'schema_version': '0.1', 'agent_approved_labels': ['agent-ok'],
                         'label_authority': 'repository-label-permission'}
        result = drift.drift(task, client)
        self.assert_single_reason(result, 'policy')
        self.assertEqual((result['policy']['stored_approval'], result['policy']['current_approval']),
                         ('candidate', 'candidate'))
        self.assertNotEqual(result['policy']['stored_policy_sha256'], result['policy']['current_policy_sha256'])

    def test_pinned_baseline_with_different_aggregate_hash_is_incomplete(self):
        # E.g. instruction-path rules changed between CLI versions: the pinned re-read succeeds but differs.
        task, client = ready_contract()
        task['source']['instructions_sha256'] = '0' * 64
        result = drift.drift(task, client)
        self.assertFalse(result['complete'])
        self.assertFalse(result['instructions']['baseline_verified'])
        self.assertEqual(result['errors'], ['Pinned instruction baseline could not be reconstructed to the stored hash'])
        self.assertEqual(result['instructions']['modified'], [])

    def test_failed_live_pr_listing_is_incomplete_even_with_verified_baseline(self):
        task, client = ready_contract()
        original, pulls = client.request, []
        def request(endpoint):
            if '/pulls' in endpoint:
                pulls.append(endpoint)
                if len(pulls) == 1:
                    raise core.ProtocolError('api_error', 'Synthetic live PR listing failure')
            return original(endpoint)
        client.request = request
        result = drift.drift(task, client)
        self.assertTrue(result['instructions']['baseline_verified'])
        self.assertIs(result['drifted'], False)
        self.assertFalse(result['complete'])
        self.assertEqual(result['errors'], ['Synthetic live PR listing failure'])

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
