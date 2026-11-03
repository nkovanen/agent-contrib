"""Pinned invitations are source restrictions, never authority."""
import base64
import copy
import json
import unittest
from unittest.mock import patch

from agent_contribute import core, tipjar, policy, multi
from tests.test_protocol import FakeGitHub, ready_contract


class JarGitHub(FakeGitHub):
    def __init__(self, state=None):
        super().__init__({'schema_version': '0.1', 'agent_approved_labels': ['agent-ok'],
                          'label_authority': 'repository-label-permission'}, ['agent-ok'])
        self.jar = None if state is None else json.dumps({'schema_version': '0.1', 'status': state}).encode()
        self.baseline_jar = self.jar
        self.commit = 'a' * 40
        self.jar_failed = False

    def request_once(self, endpoint):
        self.calls.append(endpoint)
        if self.jar_failed:
            raise core.ProtocolError('api_error', 'jar unavailable')
        historical = '?ref=' + 'a' * 40 in endpoint or '/trees/' + 'a' * 40 in endpoint
        data = self.baseline_jar if historical else self.jar
        if '/contents/.tipjar.json' in endpoint:
            return {'path': tipjar.PATH, 'type': 'file', 'encoding': 'base64', 'size': len(data),
                    'sha': tipjar.cache.blob_sha(data), 'content': base64.b64encode(data).decode()}
        result = copy.deepcopy(super().request(endpoint))
        if '/git/trees/' in endpoint:
            result['sha'] = 'c' * 40
            for entry in result['tree']:
                entry.update(mode='100644', sha='b' * 40)
            if data is not None:
                result['tree'].append({'path': tipjar.PATH, 'type': 'blob', 'mode': '100644',
                                       'sha': tipjar.cache.blob_sha(data)})
        return result


class TipjarPolicyTests(unittest.TestCase):
    def test_missing_jar_keeps_candidate_and_existing_fork_route(self):
        task, _ = ready_contract()
        client = JarGitHub()
        inspected = core.inspect_issue('acme/photos#12', client)
        self.assertEqual(inspected['tipjar']['state'], 'undeclared')
        self.assertEqual(core.prepare(inspected)['execution']['mode'], 'pending')
        self.assertTrue(core.verify(task, client=client)['execution_ready'])

    def test_welcome_does_not_change_label_approval_or_pending_execution(self):
        client = JarGitHub('welcome')
        client.policy = None
        inspected = core.inspect_issue('acme/photos#12', client)
        self.assertEqual(inspected['approval']['status'], 'candidate')
        self.assertEqual(core.prepare(inspected)['execution']['mode'], 'pending')

    def test_prepare_closed_or_unknown_writes_nothing(self):
        for state in ('closed', 'invalid'):
            client = JarGitHub(state)
            inspected = core.inspect_issue('acme/photos#12', client)
            for version in ('0.1', '0.2'):
                with self.subTest(state=state, version=version), self.assertRaises(core.ProtocolError):
                    core.prepare(inspected, schema_version=version, client=client)
        inspected.pop('tipjar')
        with self.assertRaises(core.ProtocolError):
            core.prepare(inspected)

    def test_closed_beats_approved_label(self):
        task, _ = ready_contract()
        checked = core.verify(task, client=JarGitHub('closed'))
        self.assertFalse(checked['execution_ready'])
        self.assertTrue(any('Tipjar' in error for error in checked['errors']))

    def test_old_contract_detects_added_changed_removed_jar(self):
        task, _ = ready_contract()
        for before, after in ((None, b'{"schema_version":"0.1","status":"welcome"}'),
                              (b'{"schema_version":"0.1","status":"welcome"}', None),
                              (b'{"schema_version":"0.1","status":"welcome"}',
                               b'{ "schema_version":"0.1","status":"welcome"}')):
            client = JarGitHub()
            client.baseline_jar, client.jar, client.commit = before, after, 'd' * 40
            checked = core.verify(task, client=client)
            self.assertFalse(checked['execution_ready'])
            self.assertTrue(any('Tipjar' in error for error in checked['errors']))

    def test_harmless_branch_advance_does_not_change_jar(self):
        task, _ = ready_contract()
        client = JarGitHub('welcome')
        client.commit = 'd' * 40
        self.assertTrue(core.verify(task, client=client)['execution_ready'])

    def test_unknown_and_historical_failure_block(self):
        task, _ = ready_contract()
        client = JarGitHub()
        current = core.inspect_issue('acme/photos#12', client)
        client.jar_failed = True
        self.assertTrue(tipjar.live_errors(task, current, client))
        self.assertTrue(tipjar.preparation_errors(None))

    def test_jar_is_inventory_source_without_keyword_hints(self):
        client = JarGitHub('welcome')
        inspected = core.inspect_issue('acme/photos#12', client)
        result = policy.for_inspected(inspected, client)
        self.assertEqual(result['inventory_format'], 3)
        self.assertTrue(tipjar.same_declaration(result['tipjar'], inspected['tipjar']))
        self.assertEqual(result['tipjar']['commit'], inspected['tipjar']['commit'])
        self.assertEqual(result['tipjar']['manifest']['status'], 'welcome')

    def test_selection_runs_after_scans_before_limits(self):
        for state, included in ((None, False), ('welcome', True), ('closed', False), ('invalid', False)):
            client = JarGitHub(state)
            result = core.discover('acme/photos', client, welcomed_only=True, limit=1)
            self.assertEqual(result['selection']['included'], included)
            self.assertEqual(bool(result['issues']), included)
            self.assertTrue(any('/issues?' in call for call in client.calls))
            self.assertEqual(result['complete'], state != 'invalid')


class TipjarLifecycleTests(unittest.TestCase):
    from tests.test_lifecycle import LifecycleTests as _Harness
    setUp = _Harness.setUp
    verify = _Harness.verify
    publish_fixture = _Harness.publish_fixture

    def install_jar(self, state):
        original = self.client.request_once
        data = json.dumps({'schema_version': '0.1', 'status': state}).encode()
        def once(endpoint):
            if '/contents/.tipjar.json?' in endpoint:
                return {'type': 'file', 'path': tipjar.PATH, 'size': len(data), 'encoding': 'base64',
                        'sha': tipjar.cache.blob_sha(data), 'content': base64.b64encode(data).decode()}
            result = original(endpoint)
            if '/git/trees/' in endpoint:
                result['tree'].append({'path': tipjar.PATH, 'sha': tipjar.cache.blob_sha(data),
                                       'type': 'blob', 'mode': '100644'})
            return result
        self.client.request_once = once

    def test_closed_beats_host_mandate_without_invalidating_technical_evidence(self):
        self.assertTrue(self.verify()['implementation_ready'])
        self.install_jar('closed')
        result = self.verify()
        self.assertTrue(result['technical_evidence_valid'])
        for gate in ('implementation_ready', 'draft_create_ready', 'completion_ready'):
            self.assertFalse(result[gate])
        for stage in ('implementation', 'draft', 'completion'):
            self.assertTrue(any('Tipjar' in error for error in result['stage_blockers'][stage]))

    def test_unknown_blocks_host_route(self):
        self.install_jar('unsupported-status')
        result = self.verify()
        self.assertFalse(result['implementation_ready'])
        self.assertFalse(result['draft_create_ready'])
        self.assertFalse(result['completion_ready'])


class TipjarInventoryTests(unittest.TestCase):
    def source(self, *, owner=None, extra=None):
        from tests.test_policy import PolicyGitHub
        class PinnedPolicyGitHub(PolicyGitHub):
            def request_once(self, endpoint):
                result = super().request_once(endpoint)
                if '/contents/.tipjar.json?' in endpoint:
                    data = base64.b64decode(result['content'])
                    result.update(type='file', path=tipjar.PATH, size=len(data))
                return result
        files = {tipjar.PATH: json.dumps({'schema_version': '0.1', 'status': 'welcome',
            'wanted': ['Small examples'], 'boundaries': ['Read all policies']})}
        files.update(extra or {})
        return PinnedPolicyGitHub(files, owner)

    def test_owner_prose_conflict_stays_unresolved(self):
        client = self.source(owner={'CONTRIBUTING.md': 'AI-generated contributions are not allowed.',
                                    tipjar.PATH: '{"schema_version":"0.1","status":"closed"}'})
        found = policy.report('acme/photos', 'a' * 40, [], client)
        self.assertEqual(found['tipjar']['state'], 'welcome', 'owner jars are never inherited')
        self.assertTrue(any(s['origin'] == 'owner-github' for s in found['sources_scanned']))
        self.assertTrue(any(h['kind'] in policy.STOP_HINTS for h in found['hints']))
        self.assertNotIn('approved', found)
        self.assertFalse(any('contents/.tipjar.json' in c and 'acme/.github' in c for c in client.calls))

    def test_referenced_unreadable_policy_stays_unresolved(self):
        found = policy.report('acme/photos', 'a' * 40, [], self.source(extra={
            'CONTRIBUTING.md': 'Read [AI policy](private-rules.md) before contributing.'}))
        self.assertEqual(found['tipjar']['state'], 'welcome')
        self.assertTrue(any(item['reason'] == 'referenced, not assessed' for item in found['unassessed']))

    def test_jar_cannot_be_hidden_by_prose_file_budget(self):
        client = self.source(extra={f'docs/{n}/CONTRIBUTING.md': 'Contribution rules.'
                                   for n in range(policy.MAX_SOURCE_FILES + 4)})
        found = policy.report('acme/photos', 'a' * 40, [], client)
        self.assertTrue(found['limits_hide_sources'])
        self.assertEqual(found['tipjar']['state'], 'welcome')
        self.assertEqual(found['tipjar']['manifest']['boundaries'], ['Read all policies'])
        self.assertEqual(found['tipjar']['commit'], 'a' * 40)
