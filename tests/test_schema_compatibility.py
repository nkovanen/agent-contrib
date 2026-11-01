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
