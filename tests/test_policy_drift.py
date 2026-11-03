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

    def test_a_malformed_new_tree_entry_makes_policy_drift_unknown(self):
        # FR1-08: a new AI_POLICY.md entry whose type is missing or invalid was skipped as a non-blob, so the
        # current inventory looked unchanged and drift exited 0.
        self.client.advance({})
        original = self.client.request
        cases = {'type missing': {'path': 'AI_POLICY.md'}, 'type null': {'path': 'AI_POLICY.md', 'type': None},
                 'type list': {'path': 'AI_POLICY.md', 'type': []},
                 'type unknown': {'path': 'AI_POLICY.md', 'type': 'unknown'},
                 'mode contradicts type': {'path': 'AI_POLICY.md', 'type': 'tree', 'mode': '100644'},
                 'mode list': {'path': 'AI_POLICY.md', 'type': 'tree', 'mode': []},
                 'empty path': {'path': '', 'type': 'blob', 'mode': '100644'}}
        for name, entry in cases.items():
            def request(endpoint, entry=entry):
                value = original(endpoint)
                if '/git/trees/' + LATER in endpoint:
                    value['tree'].append(dict(entry))
                return value
            with self.subTest(case=name), patch.object(self.client, 'request', side_effect=request):
                code, result = run(self.client, 'drift', self.path, '--policy-sha256', self.recorded)
                self.assertEqual(code, 1)
                self.assertIs(result['complete'], False)
                self.assertIsNone(result['repository_policy_drift']['policy_drifted'])
        valid = [{'path': 'vendor', 'type': 'tree', 'mode': '040000', 'sha': 'd' * 40},
                 {'path': 'vendor/lib', 'type': 'commit', 'mode': '160000', 'sha': 'e' * 40}]

        def request(endpoint):
            value = original(endpoint)
            if '/git/trees/' + LATER in endpoint:
                value['tree'] += [dict(entry) for entry in valid]
            return value
        with patch.object(self.client, 'request', side_effect=request):
            code, result = run(self.client, 'drift', self.path, '--policy-sha256', self.recorded)
        self.assertIsNot(result['repository_policy_drift']['policy_drifted'], None, 'tree and commit entries are valid')

    def test_each_tree_reader_refuses_a_malformed_entry_on_its_own(self):
        # The source snapshot and the policy inventory each read the tree; neither may skip a malformed entry.
        original = self.client.request

        cases = {'malformed entry': ({'path': 'AI_POLICY.md', 'type': 'unknown'},
                                     'Invalid GitHub tree entry type, mode or path'),
                 'repeated path': ({'path': 'SECURITY.md', 'type': 'blob', 'sha': 'f' * 40},  # FR1-09
                                   'Repeated GitHub tree path')}
        for name, (entry, message) in cases.items():
            def request(endpoint, entry=entry):
                value = original(endpoint)
                if '/git/trees/' + PINNED in endpoint:
                    value['tree'].insert(0, dict(entry))
                return value
            with self.subTest(case=name), patch.object(self.client, 'request', side_effect=request):
                inspected = core.inspect_issue('acme/photos#12', self.client)
                self.assertIs(inspected['complete'], False)
                self.assertIn(message, ' '.join(inspected['errors']))
                report = policy.report('acme/photos', PINNED, [], self.client, default_branch='main')
                self.assertIn('repository tree not read', [item['reason'] for item in report['unassessed']])

    def test_conflicting_blob_ids_for_one_path_make_policy_drift_unknown_in_either_order(self):
        # FR1-09: the reviewed ID listed last used to win, so drift reported an unchanged inventory and exit 0.
        self.client.advance({'SECURITY.md': 'Report privately.'})
        original = self.client.request
        for position in ('first', 'last'):
            def request(endpoint, position=position):
                value = original(endpoint)
                if '/git/trees/' + LATER in endpoint:
                    conflict = {'path': 'SECURITY.md', 'type': 'blob', 'mode': '100644', 'sha': 'f' * 40}
                    value['tree'].insert(0 if position == 'first' else len(value['tree']), conflict)
                return value
            with self.subTest(position=position), patch.object(self.client, 'request', side_effect=request):
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
        from tests.test_cache import without_times
        self.assertEqual(without_times(result), without_times(drift.drift(self.task, self.client)))

    def test_text_output_names_policy_drift(self):
        self.client.advance({'SECURITY.md': 'Agents must not open PRs.'})
        output = io.StringIO()
        with patch.object(core, 'GitHub', return_value=self.client), contextlib.redirect_stdout(output):
            cli.main(['--format', 'text', 'drift', self.path, '--policy-sha256', self.recorded])
        self.assertIn('Policy inventory changed: SECURITY.md', output.getvalue())


class InventoryFormatTests(unittest.TestCase):
    """N11: the inventory hash carries an explicit format version, and a mismatch names format differences."""
    def setUp(self):
        self.client = VersionedGitHub()

    def drift(self, recorded):
        task, _ = reviewed(self.client)
        path = write(task)
        self.addCleanup(os.unlink, path)
        return run(self.client, 'drift', path, '--policy-sha256', recorded)

    def test_the_report_states_its_format_and_the_hash_covers_it(self):
        task, recorded = reviewed(self.client)
        inspected = core.inspect_issue('acme/photos#12', self.client)
        self.assertEqual(policy.for_inspected(inspected, self.client)['inventory_format'], policy.INVENTORY_FORMAT)
        self.assertEqual(policy.INVENTORY_FORMAT, 3)
        with patch.object(policy, 'INVENTORY_FORMAT', 4):
            self.assertNotEqual(policy.for_inspected(inspected, self.client)['inventory_sha256'], recorded)

    def test_a_format_1_hash_of_the_same_snapshot_is_named_not_blamed_on_the_owner(self):
        with patch.object(policy, 'INVENTORY_FORMAT', 1):
            _, legacy = reviewed(self.client)
        code, result = self.drift(legacy)
        self.assertEqual(code, 1, 'a format change still fails closed')
        report = result['repository_policy_drift']
        self.assertIs(report['policy_drifted'], True)
        self.assertEqual((report['current_inventory_format'], report['recorded_inventory_format']), (3, 1))
        self.assertIn('inventory format 1', report['note'])
        self.assertNotIn('owner .github repository may have moved', report['note'])
        self.assertEqual((report['added'], report['removed'], report['changed']), ([], [], []))

    def test_an_unknown_hash_may_come_from_another_format(self):
        code, result = self.drift('f' * 64)
        self.assertEqual(code, 1)
        report = result['repository_policy_drift']
        self.assertEqual(report['current_inventory_format'], 3)
        self.assertIsNone(report['recorded_inventory_format'])
        self.assertIn('may come from a different inventory format', report['note'])

    def test_a_matching_hash_reports_the_same_format(self):
        _, recorded = reviewed(self.client)
        code, result = self.drift(recorded)
        self.assertEqual(code, 0, result)
        report = result['repository_policy_drift']
        self.assertEqual((report['current_inventory_format'], report['recorded_inventory_format']), (3, 3))

    def test_a_matching_current_hash_names_its_format_without_a_baseline(self):
        task, recorded = reviewed(self.client)
        self.client.advance(dict(self.client.versions[PINNED]))
        self.client.failed.add('/git/trees/' + PINNED)
        path = write(task)
        self.addCleanup(os.unlink, path)
        code, result = run(self.client, 'drift', path, '--policy-sha256', recorded)
        report = result['repository_policy_drift']
        self.assertIs(report['policy_drifted'], False)
        self.assertFalse(report['baseline_verified'])
        self.assertEqual((report['current_inventory_format'], report['recorded_inventory_format']), (3, 3))

    def test_text_output_names_the_format_mismatch(self):
        with patch.object(policy, 'INVENTORY_FORMAT', 1):
            task, legacy = reviewed(self.client)
        path = write(task)
        self.addCleanup(os.unlink, path)
        output = io.StringIO()
        with patch.object(core, 'GitHub', return_value=self.client), contextlib.redirect_stdout(output):
            cli.main(['--format', 'text', 'drift', path, '--policy-sha256', legacy])
        self.assertIn('Policy inventory changed: recorded inventory_sha256 is inventory format 1, current format is 3',
                      output.getvalue())


if __name__ == '__main__':
    unittest.main()


class WorkflowDriftTests(unittest.TestCase):
    def test_quick_path_and_policy_step_run_policy_drift(self):
        import importlib.resources
        text = ' '.join(importlib.resources.files('agent_contribute').joinpath('instructions.md').read_text('utf-8').split())
        quick = text[text.index('## Quick path'):text.index('## Repository policy review')]
        self.assertIn('Run `agent-contrib drift task.json` before asking for any authorization, with '
                      '`--policy-sha256 HASH`.', quick)
        self.assertIn('Rerun `drift` first', quick)
        self.assertIn('`agent-contrib drift task.json --policy-sha256 HASH`, with the `inventory_sha256` recorded in '
                      '`ai-policy-review`, re-reads the inventory', text)
        self.assertIn('`policy_drifted` must be `false`; `true` means re-review, and `null` (an incomplete read) is '
                      'unresolved.', text)
