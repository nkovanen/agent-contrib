"""Lifecycle state-table tests. All host events and publication facts are fixtures."""
import copy
import datetime as dt
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from agent_contribute import core, lifecycle
from tests.test_authorization import NOW, CandidateGitHub, candidate_task, host_context, event_binding
from tests.test_protocol import evidence_checkout


class Clock(dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz)


def absent_publication(*_):
    return {'status': 'absent', 'verified': False, 'creation_clear': True, 'own_pr': None,
            'errors': [], 'provenance': {'fixture': True}}


def own_publication(task, context, evidence):
    own = {'repository': 'acme/photos', 'repository_id': 101, 'number': 30, 'id': 3001,
           'url': 'https://github.com/acme/photos/pull/30', 'head_sha': evidence['git_head'],
           'head_ref': 'agent/bounds', 'base_ref': 'main', 'author_id': 7,
           'created_at': (NOW - dt.timedelta(minutes=30)).isoformat()}
    context['publication'] = {'repository_id': 101, 'pr_number': 30, 'pr_id': 3001,
                              'head_sha': evidence['git_head'], 'contract_sha256': core.canonical_hash(task),
                              'mandate_sha256': core.canonical_hash(context['mandate'])}
    return {'status': 'own_draft', 'verified': True, 'creation_clear': False,
            'own_pr': own, 'errors': [], 'provenance': {'fixture': True}}


def signoff(task, context, evidence):
    record = {'id': 'fixture-final-1', 'nonce': 'fixture-final-random-nonce-0001',
              'issued_at': (NOW - dt.timedelta(minutes=5)).isoformat(),
              'expires_at': (NOW + dt.timedelta(hours=1)).isoformat(),
              'contract_sha256': core.canonical_hash(task), 'mandate_sha256': core.canonical_hash(context['mandate']),
              'git_head': evidence['git_head'], 'review_sha256': core.canonical_hash(evidence['independent_review']),
              'credential_actor_id': 7,
              'event': {'kind': 'human', 'reference': 'fixture://final-event',
                        'text_sha256': 'c' * 64, 'binding_sha256': '0' * 64}}
    record['event']['binding_sha256'] = event_binding(record)
    return record


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.clock = patch.object(core.dt, 'datetime', Clock)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.publication = patch.object(lifecycle, 'check_publication', side_effect=absent_publication, create=True)
        self.boundary = self.publication.start()
        self.addCleanup(self.publication.stop)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.task, self.client = candidate_task()
        legacy, _, self.evidence, self.git = evidence_checkout(self.directory.name)
        self.git('checkout', '-q', '-b', 'agent/bounds')
        self.task['source']['commit'] = legacy['source']['commit']
        self.client.commit = legacy['source']['commit']
        self.context = host_context(self.task)
        digest = core.canonical_hash(self.task)
        self.evidence.update(schema_version='0.2', contract_sha256=digest)
        del self.evidence['human_signoff']
        self.evidence['independent_review'].update(contract_sha256=digest,
                                                  reviewed_at=(NOW - dt.timedelta(minutes=10)).isoformat())
        for validation in self.evidence['validations']:
            validation.update(started_at=(NOW - dt.timedelta(minutes=20)).isoformat(),
                              finished_at=(NOW - dt.timedelta(minutes=19)).isoformat())

    def verify(self, evidence=True, context=True):
        return core.verify(self.task, self.evidence if evidence else None,
                           self.directory.name, self.client, host_context=self.context if context else None)

    def publish_fixture(self):
        fact = own_publication(self.task, self.context, self.evidence)
        self.boundary.side_effect = lambda *_: copy.deepcopy(fact)
        self.client.prs = [{'id': 3001, 'number': 30, 'title': 'Contribution', 'body': 'Fixes #12',
                            'html_url': fact['own_pr']['url'], 'head': {'ref': 'agent/bounds'}}]
        return fact

    def test_full_candidate_journey_separates_every_gate(self):
        result = self.verify(evidence=False, context=False)
        self.assertFalse(result['implementation_ready'])
        self.assertEqual(result['contract_sha256'], core.canonical_hash(self.task))
        self.assertEqual(result['repository_approval']['status'], 'candidate')
        result = self.verify(evidence=False)
        self.assertTrue(result['implementation_ready'], result)
        self.assertFalse(result['technical_evidence_valid'])
        result = self.verify()
        self.assertTrue(result['technical_evidence_valid'], result)
        self.assertTrue(result['independent_review']['valid'], result)
        self.assertTrue(result['draft_create_ready'], result)
        self.assertEqual(result['next_action'], 'create_draft')
        self.assertFalse(result['completion_ready'])
        self.publish_fixture()
        result = self.verify()
        self.assertFalse(result['implementation_ready'])
        self.assertFalse(result['draft_create_ready'])
        self.assertTrue(result['publication']['verified'], result)
        self.assertEqual(result['next_action'], 'none')
        self.assertEqual(result['human_signoff']['status'], 'pending')
        self.assertFalse(result['completion_ready'])
        self.context['final_signoff'] = signoff(self.task, self.context, self.evidence)
        result = self.verify()
        self.assertTrue(result['completion_ready'], result)
        self.assertEqual(result['repository_approval']['status'], 'candidate')
        self.assertEqual(result['mandate_sha256'], core.canonical_hash(self.context['mandate']))
        self.assertEqual(result['final_signoff_sha256'], core.canonical_hash(self.context['final_signoff']))

    def test_action_scopes_cannot_be_inferred_from_credentials_or_publication(self):
        for actions in (['implement'], ['create_draft']):
            self.context = host_context(self.task)
            self.context['mandate']['actions'] = actions
            self.context['mandate']['event']['binding_sha256'] = event_binding(self.context['mandate'])
            result = self.verify()
            self.assertFalse(result['draft_create_ready'])
            self.publish_fixture()
            self.assertFalse(self.verify()['publication']['verified'])
            self.client.prs = []
            self.boundary.side_effect = absent_publication

    def test_own_plus_unrelated_overlap_and_stale_source_block_publication(self):
        self.publish_fixture()
        self.client.prs.append({'id': 3101, 'number': 31, 'title': 'Contribution', 'body': 'Fixes #12',
                                'html_url': 'https://github.com/acme/photos/pull/31', 'head': {'ref': 'other'}})
        result = self.verify()
        self.assertFalse(result['publication']['verified'])
        self.assertEqual([x['number'] for x in result['blocking_duplicates']], [31])
        self.client.prs.pop()
        self.task['source']['instructions_sha256'] = '0' * 64
        self.assertFalse(self.verify()['publication']['verified'])

    def test_saved_duplicate_is_only_resolved_by_exact_live_identity(self):
        self.task['discovery']['duplicate_prs'] = [
            {'repository': 'acme/photos', 'number': 30, 'url': 'https://github.com/acme/photos/pull/30', 'reason': 'Fixture own'}]
        self.rebind()
        self.publish_fixture()
        self.assertTrue(self.verify()['publication']['verified'])
        self.task['discovery']['duplicate_prs'][0]['url'] = 'https://github.com/other/photos/pull/30'
        self.rebind()
        self.publish_fixture()
        self.assertFalse(self.verify()['publication']['verified'])

    def rebind(self):
        digest = core.canonical_hash(self.task)
        self.evidence['contract_sha256'] = digest
        self.evidence['independent_review']['contract_sha256'] = digest
        self.context = host_context(self.task)

    def test_expiry_preserves_readonly_draft_but_never_creation(self):
        self.context['mandate'].update(issued_at=(NOW - dt.timedelta(hours=3)).isoformat(),
                                      expires_at=(NOW - dt.timedelta(minutes=15)).isoformat())
        self.context['mandate']['event']['binding_sha256'] = event_binding(self.context['mandate'])
        self.assertFalse(self.verify()['draft_create_ready'])
        self.publish_fixture()
        result = self.verify()
        self.assertTrue(result['publication']['verified'], result)
        self.assertFalse(result['draft_create_ready'])
        self.assertFalse(result['implementation_ready'])
        self.assertEqual(result['next_action'], 'none')

    def test_real_technical_checks_remain_separate_from_review(self):
        self.evidence['independent_review']['status'] = 'pending'
        result = self.verify()
        self.assertTrue(result['technical_evidence_valid'], result)
        self.assertFalse(result['independent_review']['valid'])
        self.assertFalse(result['draft_create_ready'])
        self.evidence['independent_review']['status'] = 'passed'
        self.evidence['validations'][0]['skipped'] = 1
        self.assertFalse(self.verify()['technical_evidence_valid'])
        self.evidence['validations'][0]['skipped'] = 0
        pathlib.Path(self.directory.name, 'dirty').write_text('untracked')
        self.assertFalse(self.verify()['technical_evidence_valid'])

    def test_invalid_technical_or_stale_review_cannot_borrow_identity_success(self):
        self.publish_fixture()
        self.evidence['git_tree'] = '0' * 40
        self.assertFalse(self.verify()['publication']['verified'])
        self.evidence['git_tree'] = self.git('rev-parse', 'HEAD^{tree}')
        self.evidence['independent_review']['git_head'] = '0' * 40
        self.assertFalse(self.verify()['publication']['verified'])

    def test_signoff_is_distinct_current_event_bound_to_final_revision(self):
        self.publish_fixture()
        for key, value in [('git_head', '0' * 40), ('contract_sha256', '0' * 64),
                           ('mandate_sha256', '0' * 64), ('review_sha256', '0' * 64),
                           ('credential_actor_id', 8),
                           ('issued_at', (NOW - dt.timedelta(minutes=40)).isoformat()),
                           ('issued_at', (NOW + dt.timedelta(minutes=1)).isoformat()),
                           ('expires_at', NOW.isoformat())]:
            self.context['final_signoff'] = signoff(self.task, self.context, self.evidence)
            self.context['final_signoff'][key] = value
            self.context['final_signoff']['event']['binding_sha256'] = event_binding(self.context['final_signoff'])
            result = self.verify()
            self.assertFalse(result['completion_ready'], key)
            self.assertEqual(result['human_signoff']['status'], 'invalid', key)
        self.context['final_signoff'] = signoff(self.task, self.context, self.evidence)
        self.client.permission['role_name'] = 'write'
        self.assertFalse(self.verify()['completion_ready'])

    def test_policy_states_and_incomplete_reads(self):
        policy = {'schema_version': '0.1', 'agent_approved_labels': ['agent-ok'],
                  'label_authority': 'repository-label-permission'}
        for value, labels, status in [(None, [], 'candidate'), (policy, [], 'candidate'),
                                       (policy, ['agent-ok'], 'approved')]:
            self.client = CandidateGitHub(value, labels)
            prepared = core.prepare(core.inspect_issue('acme/photos#12', self.client), schema_version='0.2', client=self.client)
            self.task['source'] = prepared['source']
            self.task['source']['commit'] = self.evidence['base_commit']
            self.client.commit = self.evidence['base_commit']
            self.rebind()
            result = self.verify()
            self.assertTrue(result['implementation_ready'], result)
            self.assertEqual(result['repository_approval']['status'], status)
        self.client.failed = {'/pulls'}
        self.assertFalse(self.verify()['implementation_ready'])
        self.client.failed = set()
        self.client.policy = {'schema_version': '999'}
        self.assertFalse(self.verify()['implementation_ready'])

    def test_evidence_human_signoff_and_legacy_schema_are_rejected(self):
        self.evidence['human_signoff'] = {'status': 'passed'}
        self.assertFalse(self.verify()['technical_evidence_valid'])
        del self.evidence['human_signoff']
        self.evidence['schema_version'] = '0.1'
        self.assertFalse(self.verify()['technical_evidence_valid'])

    def test_local_branch_and_pinned_source_history_must_match_reviewed_scope(self):
        self.git('checkout', '-q', '-b', 'wrong-branch')
        self.assertFalse(self.verify()['technical_evidence_valid'])
        self.git('checkout', '-q', 'agent/bounds')
        self.client.compare_status = 'ahead'
        result = self.verify(evidence=False)
        self.assertFalse(result['implementation_ready'])


class IntegratedGitHub(CandidateGitHub):
    def __init__(self):
        super().__init__()
        self.history = []
        self.details = {}

    def request(self, endpoint):
        if endpoint.startswith('repos/acme/photos/pulls?state=all'):
            self.calls.append(endpoint)
            if endpoint in self.failed:
                raise core.ProtocolError('api_error', 'Synthetic incomplete history')
            return copy.deepcopy(self.history)
        if endpoint.startswith('repos/acme/photos/pulls/'):
            self.calls.append(endpoint)
            return copy.deepcopy(self.details[int(endpoint.rsplit('/', 1)[1])])
        return super().request(endpoint)


class IntegratedLifecycleTests(unittest.TestCase):
    # These run the real PR identity module: only external GETs and the clock are replaced.
    def setUp(self):
        LifecycleTests.setUp(self)
        self.publication.stop()
        self.client = IntegratedGitHub()
        self.client.commit = self.evidence['base_commit']

    verify = LifecycleTests.verify
    rebind = LifecycleTests.rebind

    def publish(self, number=30):
        fact = own_publication(self.task, self.context, self.evidence)
        pr = {'id': 3001, 'number': number, 'title': 'Contribution', 'body': 'Fixes #12',
              'html_url': f'https://github.com/acme/photos/pull/{number}',
              'state': 'open', 'draft': True, 'merged': False, 'merged_at': None,
              'created_at': fact['own_pr']['created_at'], 'user': {'id': 7, 'login': 'human', 'type': 'User'},
              'head': {'ref': 'agent/bounds', 'sha': self.evidence['git_head'],
                       'repo': {'id': 101, 'full_name': 'acme/photos'}},
              'base': {'ref': 'main', 'sha': self.evidence['base_commit'],
                       'repo': {'id': 101, 'full_name': 'acme/photos'}}}
        self.client.prs = [copy.deepcopy(pr)]
        self.client.history = [copy.deepcopy(pr)]
        self.client.details[number] = copy.deepcopy(pr)
        return pr

    def test_real_modules_complete_candidate_journey_with_pending_then_final_human_event(self):
        first = self.verify(evidence=False)
        self.assertTrue(first['implementation_ready'], first)
        draft = self.verify()
        self.assertTrue(draft['draft_create_ready'], draft)
        self.publish()
        retry = self.verify()
        self.assertTrue(retry['publication']['verified'], retry)
        self.assertFalse(retry['draft_create_ready'])
        self.assertFalse(retry['implementation_ready'])
        self.assertFalse(retry['completion_ready'])
        self.assertEqual(retry['next_action'], 'none')
        self.context['final_signoff'] = signoff(self.task, self.context, self.evidence)
        complete = self.verify()
        self.assertTrue(complete['completion_ready'], complete)
        self.assertEqual(complete['repository_approval']['status'], 'candidate')
        self.assertTrue(complete['publication']['provenance']['history']['complete'])

    def test_history_without_claim_incomplete_history_and_unrelated_overlap_are_blockers(self):
        self.publish()
        del self.context['publication']
        self.assertFalse(self.verify()['draft_create_ready'])
        self.publish()
        self.client.prs.append(dict(self.client.prs[0], id=3101, number=31,
                                    html_url='https://github.com/acme/photos/pull/31'))
        result = self.verify()
        self.assertTrue(result['publication']['identity_verified'])
        self.assertFalse(result['publication']['verified'])
        self.assertEqual(result['blocking_duplicates'][0]['number'], 31)
        self.client.prs.pop()
        history_endpoint = next(endpoint for endpoint in self.client.calls if '/pulls?state=all' in endpoint)
        self.client.failed = {history_endpoint}
        self.assertFalse(self.verify()['publication']['verified'])

    def test_real_expired_publication_is_observed_without_new_action(self):
        self.context['mandate'].update(issued_at=(NOW - dt.timedelta(hours=3)).isoformat(),
                                      expires_at=(NOW - dt.timedelta(minutes=15)).isoformat())
        self.context['mandate']['event']['binding_sha256'] = event_binding(self.context['mandate'])
        self.publish()
        result = self.verify()
        self.assertTrue(result['publication']['verified'], result)
        self.assertFalse(result['implementation_ready'])
        self.assertFalse(result['draft_create_ready'])
        self.assertEqual(result['next_action'], 'none')

    def test_remote_or_local_new_head_and_premature_signoff_never_complete(self):
        self.publish()
        self.context['final_signoff'] = signoff(self.task, self.context, self.evidence)
        self.context['final_signoff']['issued_at'] = (NOW - dt.timedelta(minutes=40)).isoformat()
        self.context['final_signoff']['event']['binding_sha256'] = event_binding(self.context['final_signoff'])
        self.assertFalse(self.verify()['completion_ready'])
        del self.context['final_signoff']
        self.client.history[0]['head']['sha'] = 'f' * 40
        self.client.details[30]['head']['sha'] = 'f' * 40
        self.assertFalse(self.verify()['publication']['verified'])
        self.publish()
        pathlib.Path(self.directory.name, 'src/thumb.rs').write_text('new revision')
        self.git('add', '.')
        self.git('commit', '-q', '-m', 'new revision without evidence')
        self.assertFalse(self.verify()['publication']['verified'])

    def test_action_laundering_cannot_use_real_identity_as_permission(self):
        self.context['mandate']['actions'] = ['implement']
        self.context['mandate']['event']['binding_sha256'] = event_binding(self.context['mandate'])
        self.publish()
        result = self.verify()
        self.assertTrue(result['publication']['identity_verified'])
        self.assertFalse(result['publication']['verified'])
        self.assertFalse(result['draft_create_ready'])

    def test_recreated_repository_and_transferred_issue_fail_live_identity(self):
        self.publish()
        self.client.metadata['id'] = 999
        self.assertFalse(self.verify()['publication']['verified'])
        self.client.metadata['id'] = 101
        issue = self.client.request('repos/acme/photos/issues/12')
        self.client.overrides['repos/acme/photos/issues/12'] = dict(issue, repository_url='https://api.github.com/repos/other/photos')
        self.assertFalse(self.verify()['publication']['verified'])
