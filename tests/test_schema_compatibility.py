"""Frozen 0.1 decisions: later schemas must never reinterpret these tasks."""
import copy
import datetime as dt
import tempfile
import unittest
from unittest.mock import patch

from agent_contribute import core
from tests.test_protocol import FakeGitHub, ready_contract, evidence_checkout


class FrozenClock(dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2030, 1, 1, tzinfo=dt.timezone.utc).astimezone(tz)


class LegacyGoldenTests(unittest.TestCase):
    def setUp(self):
        self.clock = patch.object(core.dt, 'datetime', FrozenClock)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def decision(self, result):
        return {key: result[key] for key in (
            'schema_version', 'schema_valid', 'execution_ready', 'evidence_valid',
            'upstream_submission_ready', 'fork_completion_ready', 'errors', 'evidence_errors')}

    def test_policy_approved_local_work_still_needs_completion_evidence(self):
        task, client = ready_contract()
        self.assertEqual(task['source']['fetched_at'], '2030-01-01T00:00:00+00:00')
        self.assertEqual(self.decision(core.verify(task, client=client)), {
            'schema_version': '0.1', 'schema_valid': True, 'execution_ready': True,
            'evidence_valid': False, 'upstream_submission_ready': False,
            'fork_completion_ready': False, 'errors': [],
            'evidence_errors': ['No execution evidence, independent review or human signoff provided']})

    def test_fork_authorization_does_not_approve_upstream(self):
        task, _ = ready_contract()
        task['execution'].update(mode='fork-experiment', target_repository='human/photos')
        result = core.verify(task, client=FakeGitHub(labels=['agent-ok']))
        self.assertEqual(result['approval']['status'], 'candidate')
        self.assertEqual(self.decision(result), {
            'schema_version': '0.1', 'schema_valid': True, 'execution_ready': True,
            'evidence_valid': False, 'upstream_submission_ready': False,
            'fork_completion_ready': False, 'errors': [],
            'evidence_errors': ['No execution evidence, independent review or human signoff provided']})

    def test_pending_final_signoff_remains_a_completion_blocker(self):
        with tempfile.TemporaryDirectory() as directory:
            task, client, evidence, _ = evidence_checkout(directory)
            evidence['human_signoff']['status'] = 'pending'
            self.assertEqual(self.decision(core.verify(task, evidence, directory, client)), {
                'schema_version': '0.1', 'schema_valid': True, 'execution_ready': True,
                'evidence_valid': False, 'upstream_submission_ready': False,
                'fork_completion_ready': False, 'errors': [],
                'evidence_errors': ['human_signoff is missing, failed, pending or stale']})

    def test_dogfood_policy_own_pr_and_pending_signoff_stay_blocked(self):
        # Synthetic fixture reproduces both historical blockers without shipping a session dump.
        with tempfile.TemporaryDirectory() as directory:
            task, _, evidence, _ = evidence_checkout(directory)
            client = FakeGitHub(labels=['agent-ok'], prs=[{'number': 2, 'title': 'Contribution', 'body': 'Fixes #12',
                                      'html_url': 'https://github.com/acme/photos/pull/2'}])
            client.commit = task['source']['commit']
            task['approval'] = copy.deepcopy(core.prepare(core.inspect_issue('acme/photos#12', FakeGitHub()))['approval'])
            evidence['contract_sha256'] = core.canonical_hash(task)
            for name in ('independent_review', 'human_signoff'):
                evidence[name]['contract_sha256'] = evidence['contract_sha256']
            evidence['human_signoff']['status'] = 'pending'
            self.assertEqual(self.decision(core.verify(task, evidence, directory, client)), {
                'schema_version': '0.1', 'schema_valid': True, 'execution_ready': False,
                'evidence_valid': False, 'upstream_submission_ready': False,
                'fork_completion_ready': False,
                'errors': ['Live issue is excluded or overlaps an open PR',
                           'Upstream execution needs current repository approval and matching target'],
                'evidence_errors': ['human_signoff is missing, failed, pending or stale']})


class SchemaSelectionTests(unittest.TestCase):
    def test_explicit_prepare_is_closed_and_pending_without_authority(self):
        from tests.test_authorization import CandidateGitHub
        client = CandidateGitHub()
        inspected = core.inspect_issue('acme/photos#12', client)
        self.assertEqual(core.prepare(inspected)['schema_version'], '0.1')
        task = core.prepare(inspected, schema_version='0.2', client=client)
        self.assertEqual(core.validate_contract(task), [])
        self.assertEqual(task['source']['repository_id'], 101)
        self.assertEqual(task['source']['owner_id'], 7)
        self.assertEqual(task['source']['issue_id'], 1201)
        self.assertEqual(task['execution']['mode'], 'pending')
        self.assertNotIn('authorized_by', task['execution'])
        for mode in ('fork-experiment', 'upstream-contribution'):
            other = copy.deepcopy(task)
            other['execution']['mode'] = mode
            self.assertTrue(core.validate_contract(other))
        task['execution']['authorized_by'] = 'human prose cannot authorize'
        self.assertTrue(core.validate_contract(task))

    def test_unsupported_schema_and_resource_names_fail_closed(self):
        task, client = ready_contract()
        with self.assertRaises(core.ProtocolError):
            core.prepare(core.inspect_issue('acme/photos#12', client), schema_version='9')
        for name, version in [('task', '9'), ('../task', '0.2'), ('unknown', '0.1')]:
            with self.subTest(name=name, version=version), self.assertRaises(core.ProtocolError):
                core.bundled_schema(name, version)

    def test_legacy_host_input_is_explicitly_rejected(self):
        task, client = ready_contract()
        client.calls.clear()
        result = core.verify(task, client=client, host_context={})
        self.assertFalse(result['execution_ready'])
        self.assertIn('Host context is unsupported for schema 0.1', result['errors'])
        self.assertTrue(result['schema_valid'], 'a valid contract stays schema-valid (A1-16)')
        self.assertEqual(client.calls, [], 'rejected before any GitHub read')

    def test_evidence_cannot_mix_versions_or_smuggle_human_approval(self):
        from tests.test_authorization import candidate_task
        task, client = candidate_task()
        for value in ({'schema_version': '0.1'}, {'schema_version': '9'}):
            result = core.verify(task, evidence=value, client=client)
            self.assertFalse(result['technical_evidence_valid'])
            self.assertTrue(result['evidence_errors'])
        schema = core.bundled_schema('evidence', '0.2')
        self.assertNotIn('human_signoff', schema['properties'])
        self.assertFalse(schema['additionalProperties'])


class FullLegacyGoldenTests(unittest.TestCase):
    setUp = LegacyGoldenTests.setUp
    def test_full_results_match_baseline_766bfcd(self):
        import json
        from pathlib import Path
        task, client = ready_contract()
        actual = {'approved': core.verify(task, client=client),
                  'candidate': core.verify(task, client=FakeGitHub(labels=['agent-ok'])),
                  'malformed': core.verify({'schema_version': '9'})}
        for name, result in actual.items():
            with self.subTest(name=name):
                path = Path(__file__).parent / 'fixtures' / 'legacy' / (name + '.json')
                self.assertEqual(result, json.loads(path.read_text()))


class PrepareRouteTests(unittest.TestCase):
    def test_explicit_v2_cannot_replace_a_fork_target_with_the_source(self):
        from tests.test_authorization import CandidateGitHub
        client = CandidateGitHub()
        inspected = core.inspect_issue('human/photos#12', client)
        with self.assertRaises(core.ProtocolError) as caught:
            core.prepare(inspected, schema_version='0.2', client=client)
        self.assertEqual(caught.exception.code, 'unsupported_route')

    def test_legacy_empty_host_contexts_all_reject(self):
        task, client = ready_contract()
        for value in ({}, [], 0, ''):
            self.assertFalse(core.verify(task, client=client, host_context=value)['execution_ready'])
