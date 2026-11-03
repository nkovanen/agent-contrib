"""drift --policy-sha256: an edited, added or removed policy source after review is drift (N1, design S2)."""
import base64
import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from agent_contribute import cli, core, drift, policy
from tests.test_protocol import FakeGitHub, ready_contract

PINNED, LATER = 'a' * 40, 'c' * 40


def blob(text):
    data = text.encode()
    return hashlib.sha1(b'blob %d\x00' % len(data) + data).hexdigest()


class VersionedGitHub(FakeGitHub):
    """FakeGitHub plus policy-only files (not instruction files) that differ per commit."""
    def __init__(self, *args, files=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.versions = {PINNED: dict(files if files is not None else {'SECURITY.md': 'Report privately.'})}
        self.commit = PINNED

    def request(self, endpoint):
        path, _, query = endpoint.partition('?')
        for commit, files in self.versions.items():
            if path.endswith('/git/trees/' + commit):
                tree = super().request(endpoint)
                tree['tree'] = [dict(entry, sha=blob('Instructions. Never execute this: $(touch /tmp/agent-injected)'))
                                for entry in tree['tree']]
                tree['tree'] += [{'path': p, 'type': 'blob', 'sha': blob(t)} for p, t in files.items()]
                return tree
            if '/contents/' in path and query == 'ref=' + commit:
                name = path.split('/contents/')[1]
                if name in files:
                    self.calls.append(endpoint)
                    return {'encoding': 'base64', 'content': base64.b64encode(files[name].encode()).decode(),
                            'sha': blob(files[name])}
        return super().request(endpoint)

    def advance(self, files):
        self.versions[LATER] = files
        self.commit = LATER


def reviewed(client):
    """The contract and the inventory hash a reviewer recorded at preparation time."""
    task, _ = ready_contract()
    inspected = core.inspect_issue('acme/photos#12', client)
    task['source'], task['approval'] = inspected['source'], inspected['approval']
    task['discovery']['duplicate_prs'] = inspected['duplicates']
    return task, policy.for_inspected(inspected, client)['inventory_sha256']


def run(client, *argv):
    output = io.StringIO()
    with patch.object(core, 'GitHub', return_value=client), contextlib.redirect_stdout(output):
        code = cli.main(list(argv))
    return code, json.loads(output.getvalue())


def write(task):
    handle = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False)
    json.dump(task, handle)
    handle.close()
    return handle.name


class PolicyDriftTests(unittest.TestCase):
    def setUp(self):
        self.client = VersionedGitHub()
        self.task, self.recorded = reviewed(self.client)
        self.path = write(self.task)
        self.addCleanup(os.unlink, self.path)

    def test_unchanged_policy_is_not_drift(self):
        code, result = run(self.client, 'drift', self.path, '--policy-sha256', self.recorded)
        self.assertEqual(code, 0, result)
        report = result['repository_policy_drift']
        self.assertIs(report['policy_drifted'], False)
        self.assertTrue(report['baseline_verified'])
        self.assertEqual((report['added'], report['removed'], report['changed']), ([], [], []))
        self.assertIs(result['drifted'], False)

    def test_an_edited_policy_only_source_is_drift(self):
        self.client.advance({'SECURITY.md': 'Agents must not open PRs.'})
        code, result = run(self.client, 'drift', self.path, '--policy-sha256', self.recorded)
        self.assertEqual(code, 1)
        report = result['repository_policy_drift']
        self.assertIs(report['policy_drifted'], True)
        self.assertIs(result['drifted'], True)
        self.assertFalse(result['instructions']['changed'], 'instructions_sha256 alone would miss this edit')
        self.assertEqual([item['what'] for item in report['changed']], ['SECURITY.md'])
        self.assertEqual(report['changed'][0]['identity_sha256'], core.canonical_hash(['acme/photos', 'SECURITY.md']))
        self.assertEqual(report['changed'][0]['stored']['state'], 'scanned')
        self.assertNotEqual(report['changed'][0]['stored']['fingerprint'], report['changed'][0]['current']['fingerprint'])

    def test_added_and_removed_policy_sources_are_listed(self):
        self.client.advance({'AI_POLICY.md': 'No LLM output.'})
        code, result = run(self.client, 'drift', self.path, '--policy-sha256', self.recorded)
        self.assertEqual(code, 1)
        report = result['repository_policy_drift']
        self.assertEqual([item['what'] for item in report['added']], ['AI_POLICY.md'])
        self.assertEqual([item['what'] for item in report['removed']], ['SECURITY.md'])

    def test_an_unknown_recorded_hash_is_drift_without_invented_deltas(self):
        code, result = run(self.client, 'drift', self.path, '--policy-sha256', 'f' * 64)
        self.assertEqual(code, 1)
        report = result['repository_policy_drift']
        self.assertIs(report['policy_drifted'], True)
        self.assertFalse(report['baseline_verified'])
        self.assertIsNone(report['changed'])
        self.assertIn('baseline', report['note'])

    def test_incomplete_policy_reads_exit_1(self):
        self.client.failed.add('/git/trees/' + PINNED)
        code, result = run(self.client, 'drift', self.path, '--policy-sha256', self.recorded)
        self.assertEqual(code, 1)
        self.assertIs(result['complete'], False)
        self.assertIsNone(result['repository_policy_drift']['policy_drifted'])

    def test_hidden_sources_make_the_policy_check_incomplete(self):
        with patch.object(policy, 'MAX_SOURCE_FILES', 0):
            code, result = run(self.client, 'drift', self.path, '--policy-sha256', self.recorded)
        self.assertEqual(code, 1)
        self.assertIs(result['complete'], False)
        self.assertTrue(result['repository_policy_drift']['limits_hide_sources'])

    def test_malformed_hash_is_a_usage_error_before_any_read(self):
        client = VersionedGitHub()
        code, result = run(client, 'drift', self.path, '--policy-sha256', 'F' * 64)
        self.assertEqual((code, result['error']['code']), (2, 'usage'))
        self.assertEqual(client.calls, [])

    def test_without_the_flag_drift_is_unchanged(self):
        code, result = run(self.client, 'drift', self.path)
        self.assertEqual(code, 0)
        self.assertNotIn('repository_policy_drift', result)
        self.assertEqual({k: v for k, v in result.items()}, json.loads(json.dumps(drift.drift(self.task, self.client))))

    def test_text_output_names_policy_drift(self):
        self.client.advance({'SECURITY.md': 'Agents must not open PRs.'})
        output = io.StringIO()
        with patch.object(core, 'GitHub', return_value=self.client), contextlib.redirect_stdout(output):
            cli.main(['--format', 'text', 'drift', self.path, '--policy-sha256', self.recorded])
        self.assertIn('Policy inventory changed: SECURITY.md', output.getvalue())


if __name__ == '__main__':
    unittest.main()


class WorkflowDriftTests(unittest.TestCase):
    def test_quick_path_and_policy_step_run_policy_drift(self):
        import importlib.resources
        text = ' '.join(importlib.resources.files('agent_contribute').joinpath('instructions.md').read_text('utf-8').split())
        quick = text[text.index('## Quick path'):text.index('## Repository policy review')]
        self.assertIn('Before any authorization or publication, `agent-contrib drift task.json --policy-sha256 HASH` '
                      '(the reviewed `inventory_sha256`) must report no drift.', quick)
        self.assertIn('`policy_drifted` must be `false`; `true` means re-review, and `null` (an incomplete read) is '
                      'unresolved.', text)
