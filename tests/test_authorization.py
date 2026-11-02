"""Synthetic human/host assertions only; no record here grants real authority."""
import copy
import datetime as dt
import unittest

from agent_contribute import core
from tests.test_protocol import FakeGitHub, ready_contract

NOW = dt.datetime(2030, 1, 1, 12, tzinfo=dt.timezone.utc)


class CandidateGitHub(FakeGitHub):
    def __init__(self, policy=None, labels=None, prs=None):
        super().__init__(policy, labels, prs)
        self.actor = {'id': 7, 'login': 'human', 'type': 'User'}
        self.permission = {'role_name': 'maintain', 'permission': 'write',
                           'user': {'id': 7, 'login': 'human', 'type': 'User'}}
        self.metadata = {'full_name': 'acme/photos', 'id': 101, 'default_branch': 'main',
                         'owner': {'id': 7, 'login': 'acme', 'type': 'User'},
                         'fork': False, 'has_issues': True}
        self.overrides = {}

    def request(self, endpoint):
        if endpoint in self.failed:
            raise core.ProtocolError('api_error', 'Synthetic unavailable GET')
        if endpoint in self.overrides:
            return copy.deepcopy(self.overrides[endpoint])
        if endpoint == 'user':
            self.calls.append(endpoint)
            return copy.deepcopy(self.actor)
        if endpoint.startswith('repos/acme/photos/collaborators/'):
            self.calls.append(endpoint)
            return copy.deepcopy(self.permission)
        if endpoint == 'repos/acme/photos':
            self.calls.append(endpoint)
            return copy.deepcopy(self.metadata)
        value = super().request(endpoint)
        if endpoint == 'repos/acme/photos/issues/12':
            value.update(id=1201, repository_url='https://api.github.com/repos/acme/photos')
        return value


def candidate_task():
    task, _ = ready_contract()
    client = CandidateGitHub()
    prepared = core.prepare(core.inspect_issue('acme/photos#12', client), schema_version='0.2', client=client)
    task.update(schema_version='0.2', source=prepared['source'], approval=prepared['approval'])
    task['execution'] = dict(prepared['execution'], mode='repository-candidate', head_ref='agent/bounds',
                             requested_actions=['implement', 'create_draft'])
    return task, client


def event_binding(record):
    payload = {key: value for key, value in record.items() if key != 'event'}
    payload['event'] = {key: value for key, value in record['event'].items() if key != 'binding_sha256'}
    return core.canonical_hash(payload)


def host_context(task):
    source, execution = task['source'], task['execution']
    mandate = dict(id='fixture-mandate-1', nonce='fixture-only-random-nonce-000001',
                   issued_at=(NOW - dt.timedelta(hours=1)).isoformat(),
                   expires_at=(NOW + dt.timedelta(hours=1)).isoformat(),
                   contract_sha256=core.canonical_hash(task),
                   source_repository_id=source['repository_id'], source_owner_id=source['owner_id'],
                   issue_id=source['issue_id'], issue_number=source['issue'],
                   credential_actor_id=7, authority='maintainer',
                   actions=['implement', 'create_draft'],
                   policy_review={'status': 'clear', 'instructions_sha256': source['instructions_sha256'],
                                  'policy_sha256': source['policy_sha256'], 'notes': 'Synthetic reviewed prose'},
                   event={'kind': 'human', 'reference': 'fixture://human-event-1', 'text_sha256': 'b' * 64,
                          'binding_sha256': '0' * 64})
    for key in ('target_repository', 'target_repository_id', 'head_repository', 'head_repository_id', 'head_ref', 'base_ref'):
        mandate[key] = execution[key]
    mandate['event']['binding_sha256'] = event_binding(mandate)
    return {'schema_version': '0.1', 'mandate': mandate}


class AuthorizationTests(unittest.TestCase):
    def check(self, task=None, client=None, context=None, now=NOW):
        from agent_contribute import authorization
        if task is None:
            task, default_client = candidate_task()
            client = client or default_client
        return authorization.check(task, context, client, now)

    def test_admin_credentials_and_issue_prose_are_not_human_authority(self):
        task, client = candidate_task()
        client.permission['role_name'] = 'admin'
        result = self.check(task, client)
        self.assertFalse(result['authorized'])
        self.assertFalse(result['historical_valid'])
        self.assertEqual(result['credential_actor']['id'], 7)
        self.assertIn('Missing human/host mandate', result['errors'])

    def test_task_bound_host_assertion_and_live_maintain_allow_only_named_actions(self):
        task, client = candidate_task()
        context = host_context(task)
        result = self.check(task, client, context)
        self.assertTrue(result['authorized'], result)
        self.assertTrue(result['implement'])
        self.assertTrue(result['create_draft'])
        self.assertEqual(result['mandate_trust'], 'host-asserted')
        self.assertEqual(result['mandate_sha256'], core.canonical_hash(context['mandate']))
        self.assertEqual(result['credential_actor']['id'], 7)
        self.assertEqual(result['permission']['role_name'], 'maintain')
        self.assertIn('user', client.calls)
        self.assertIn('repos/acme/photos/collaborators/human/permission', client.calls)
        context['mandate']['actions'] = ['implement']
        context['mandate']['event']['binding_sha256'] = event_binding(context['mandate'])
        result = self.check(task, client, context)
        self.assertTrue(result['implement'])
        self.assertFalse(result['create_draft'])

    def test_identity_binding_and_event_fields_fail_closed(self):
        task, client = candidate_task()
        for key, value in [('contract_sha256', '0' * 64), ('source_repository_id', 999),
                           ('source_owner_id', 999), ('issue_id', 999), ('issue_number', 13),
                           ('target_repository_id', 999), ('head_repository_id', 999),
                           ('target_repository', 'other/photos'), ('head_repository', 'other/photos'),
                           ('head_ref', 'other'), ('base_ref', 'other'), ('credential_actor_id', 8),
                           ('nonce', 'short'), ('actions', ['merge']), ('actions', ['implement', 'implement'])]:
            with self.subTest(key=key, value=value):
                context = host_context(task)
                context['mandate'][key] = value
                context['mandate']['event']['binding_sha256'] = event_binding(context['mandate'])
                self.assertFalse(self.check(task, client, context)['authorized'])
        for field, value in [('kind', 'agent'), ('reference', ''), ('binding_sha256', '0' * 64)]:
            context = host_context(task)
            context['mandate']['event'][field] = value
            self.assertFalse(self.check(task, client, context)['authorized'])

    def test_permissions_require_exact_role_and_actor_fields(self):
        task, client = candidate_task()
        context = host_context(task)
        for role in ('write', 'triage', 'read', 'custom-maintain', None):
            client.permission['role_name'] = role
            self.assertFalse(self.check(task, client, context)['authorized'], role)
        client.permission['role_name'] = 'maintain'
        for user in ({'id': 8, 'login': 'human', 'type': 'User'}, {'id': 7}, None):
            client.permission['user'] = user
            self.assertFalse(self.check(task, client, context)['authorized'])
        for actor in ({'id': 7, 'login': 'human', 'type': 'Bot'}, {},
                      {'id': True, 'login': 'human', 'type': 'User'},
                      {'id': 8, 'login': 'human', 'type': 'User'}):
            client.actor = actor
            self.assertFalse(self.check(task, client, context)['authorized'])

    def test_current_identity_revocation_and_api_failures_block(self):
        task, client = candidate_task()
        context = host_context(task)
        for endpoint in ('user', 'repos/acme/photos', 'repos/acme/photos/issues/12',
                         'repos/acme/photos/collaborators/human/permission'):
            client.failed = {endpoint}
            self.assertFalse(self.check(task, client, context)['authorized'], endpoint)
        client.failed = set()
        for key, value in [('id', 102), ('full_name', 'other/photos'),
                           ('owner', {'id': 8, 'login': 'acme', 'type': 'User'})]:
            client.overrides['repos/acme/photos'] = dict(client.metadata, **{key: value})
            self.assertFalse(self.check(task, client, context)['authorized'], key)
        client.overrides = {'repos/acme/photos/issues/12': {'id': 1202}}
        self.assertFalse(self.check(task, client, context)['authorized'])

    def test_owner_claim_needs_owner_identity_but_maintainer_can_be_nonowner(self):
        task, client = candidate_task()
        client.actor['id'] = 9
        client.permission['user']['id'] = 9
        context = host_context(task)
        context['mandate']['credential_actor_id'] = 9
        context['mandate']['event']['binding_sha256'] = event_binding(context['mandate'])
        self.assertTrue(self.check(task, client, context)['authorized'])
        context['mandate']['authority'] = 'owner'
        context['mandate']['event']['binding_sha256'] = event_binding(context['mandate'])
        self.assertFalse(self.check(task, client, context)['authorized'])

    def test_time_bounds_and_historical_observation_are_separate(self):
        task, client = candidate_task()
        context = host_context(task)
        expired = self.check(task, client, context, NOW + dt.timedelta(hours=2))
        self.assertFalse(expired['authorized'])
        self.assertTrue(expired['historical_valid'])
        for issued, expires in [(NOW + dt.timedelta(minutes=1), NOW + dt.timedelta(hours=1)),
                                (NOW, NOW), (NOW, NOW + dt.timedelta(hours=25))]:
            context = host_context(task)
            context['mandate'].update(issued_at=issued.isoformat(), expires_at=expires.isoformat())
            context['mandate']['event']['binding_sha256'] = event_binding(context['mandate'])
            self.assertFalse(self.check(task, client, context)['historical_valid'])

    def test_policy_review_must_be_clear_and_bound_to_pinned_inputs(self):
        task, client = candidate_task()
        for key, value in [('status', 'unknown'), ('status', 'blocked'),
                           ('instructions_sha256', '0' * 64), ('policy_sha256', '0' * 64)]:
            context = host_context(task)
            context['mandate']['policy_review'][key] = value
            context['mandate']['event']['binding_sha256'] = event_binding(context['mandate'])
            self.assertFalse(self.check(task, client, context)['authorized'])


    def test_candidate_base_ref_must_be_the_reviewed_source_default_branch(self):
        task, client = candidate_task()
        task['execution']['base_ref'] = 'otherbranch'
        context = host_context(task)
        result = self.check(task, client, context)
        self.assertFalse(result['authorized'])
        self.assertFalse(result['historical_valid'])
        self.assertIn('Candidate base ref must match the source default branch', result['errors'])


    def test_matching_mandate_cannot_authorize_a_cross_repository_route(self):
        task, client = candidate_task()
        task['execution'].update(target_repository='acme/other', head_repository='acme/other')
        result = self.check(task, client, host_context(task))
        self.assertFalse(result['authorized'])
        self.assertFalse(result['historical_valid'])
        self.assertIn('Only the same repository source/target/head route is supported', result['errors'])

    def test_matching_mandate_cannot_authorize_pending_execution(self):
        task, client = candidate_task()
        task['execution']['mode'] = 'pending'
        result = self.check(task, client, host_context(task))
        self.assertFalse(result['authorized'])
        self.assertFalse(result['historical_valid'])
        self.assertIn('Execution mode is pending', result['errors'])

    def test_matching_mandate_cannot_use_the_default_branch_as_its_head(self):
        task, client = candidate_task()
        task['execution']['head_ref'] = 'main'
        result = self.check(task, client, host_context(task))
        self.assertFalse(result['authorized'])
        self.assertFalse(result['historical_valid'])
        self.assertIn('Head and base refs must differ', result['errors'])

    def test_matching_mandate_cannot_authorize_an_invalid_head_ref(self):
        task, client = candidate_task()
        task['execution']['head_ref'] = 'bad..ref'
        result = self.check(task, client, host_context(task))
        self.assertFalse(result['authorized'])
        self.assertFalse(result['historical_valid'])
        self.assertIn('Invalid reviewed Git ref: head_ref', result['errors'])

    def test_live_issue_id_change_cannot_keep_the_old_issue_authority(self):
        task, client = candidate_task()
        issue = client.request('repos/acme/photos/issues/12')
        client.overrides['repos/acme/photos/issues/12'] = dict(issue, id=9999)
        result = self.check(task, client, host_context(task))
        self.assertFalse(result['authorized'])
        self.assertFalse(result['historical_valid'])
        self.assertIn('Reviewed issue identity changed', result['errors'])

    def test_mandate_actions_cannot_exceed_reviewed_requested_actions(self):
        task, client = candidate_task()
        task['execution']['requested_actions'] = ['implement']
        context = host_context(task)
        self.assertEqual(context['mandate']['actions'], ['implement', 'create_draft'])
        result = self.check(task, client, context)
        self.assertFalse(result['historical_valid'])
        self.assertFalse(result['implement'])
        self.assertFalse(result['create_draft'])
        self.assertEqual(result['errors'], ['Mandate actions are duplicated or exceed reviewed requested actions'])

    def test_mandate_expires_at_the_exact_expiry_boundary(self):
        task, client = candidate_task()
        context = host_context(task)
        context['mandate'].update(issued_at=(NOW - dt.timedelta(hours=2)).isoformat(),
                                  expires_at=NOW.isoformat())
        context['mandate']['event']['binding_sha256'] = event_binding(context['mandate'])
        result = self.check(task, client, context)
        self.assertTrue(result['historical_valid'])
        self.assertFalse(result['authorized'])
        self.assertFalse(result['implement'])
        self.assertFalse(result['create_draft'])
        self.assertIn('Human/host mandate has expired for new actions', result['current_errors'])


class TimestampTests(unittest.TestCase):

    def test_explicit_timestamp_dialect_has_no_normalized_invalid_offsets(self):
        from agent_contribute.authorization import timestamp
        for value in ('2030-01-01T12:00:00+00:60', '2030-01-01T12:00:00-00:60',
                      '2030-01-01T12:00:00-00:00', '2030-01-01T12:00:00.1234567Z',
                      '2030-01-01T12:00:00+24:00', '2030-01-01T12:00:00+0000',
                      '2030-01-01T12:00:00', '2030-W01-2T12:00:00Z'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                timestamp(value)
        for fraction in ('', '.1', '.12', '.123', '.1234', '.12345', '.123456'):
            self.assertEqual(timestamp('2030-01-01T12:00:00' + fraction + 'Z').hour, 12)

    def test_invalid_git_refs_do_not_become_publication_scope(self):
        from agent_contribute.authorization import valid_ref
        for value in ('bad ref', '-option', '../escape', 'a..b', 'a@{b', 'a\\b', 'a:b', 'a?b',
                      'a[b', 'a//b', 'a.lock', '.hidden', 'a/', 'a.', '@', 'HEAD', 'x&state=closed:evil'):
            self.assertFalse(valid_ref(value), value)
        self.assertTrue(valid_ref('agent/bounds'))
