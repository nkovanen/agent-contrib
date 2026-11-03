"""Unsigned authorization requests; every record here is synthetic and grants nothing."""
import contextlib
import copy
import datetime as dt
import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from agent_contribute import cli, core, lifecycle
from tests import test_lifecycle
from tests.test_authorization import NOW, candidate_task, event_binding
from tests.test_lifecycle import Clock

REQUEST_KEYS = {'kind', 'request_version', 'issued', 'notice', 'target_host_context_schema_version',
                'ready_for_issuance', 'preflight_errors', 'preflight_errors_trust', 'unresolved_fields',
                'contract_sha256', 'exact_head_pr_history', 'mandate_fields', 'human_only_fields', 'requested_actions',
                'provenance'}


def build(task, client):
    from agent_contribute import authrequest
    with patch.object(core.dt, 'datetime', Clock):
        return authrequest.build(task, client)


def null_leaves(value, prefix=''):
    if value is None:
        return [prefix]
    if isinstance(value, dict):
        return [leaf for key, item in value.items() for leaf in null_leaves(item, prefix + '.' + key if prefix else key)]
    return []


def schema_leaves(schema, prefix=''):
    if schema.get('type') != 'object':
        return [prefix]
    return [leaf for key, item in schema['properties'].items()
            for leaf in schema_leaves(item, prefix + '.' + key if prefix else key)]


def issue(request, task):
    """What a test host would do after a human approves: fill only the human-only fields."""
    mandate = copy.deepcopy(request['mandate_fields'])
    mandate.update(id='fixture-host-record-1', nonce='fixture-only-random-nonce-000042',
                   issued_at=(NOW - dt.timedelta(hours=1)).isoformat(),
                   expires_at=(NOW + dt.timedelta(hours=1)).isoformat(),
                   actions=list(task['execution']['requested_actions']))
    mandate['policy_review'].update(status='clear', notes='Synthetic host review')
    mandate['event'].update(kind='human', reference='fixture://approval-1', text_sha256='d' * 64)
    mandate['event']['binding_sha256'] = event_binding(mandate)
    return {'schema_version': '0.1', 'mandate': mandate}


class RequestFixture(unittest.TestCase):
    setUp = test_lifecycle.IntegratedLifecycleTests.setUp
    verify = test_lifecycle.IntegratedLifecycleTests.verify


class RoundTripTests(RequestFixture):
    def test_filling_only_human_fields_yields_a_mandate_that_verifies(self):
        request = build(self.task, self.client)
        self.assertTrue(request['ready_for_issuance'], request)
        self.assertEqual(request['preflight_errors'], [])
        self.context = issue(request, self.task)
        result = self.verify(evidence=False)
        self.assertTrue(result['implementation_ready'], result['stage_blockers'])
        self.assertEqual(result['mandate_sha256'], core.canonical_hash(self.context['mandate']))

    def test_ready_request_nulls_are_exactly_the_human_fields_and_cover_the_schema(self):
        request = build(self.task, self.client)
        self.assertEqual(sorted(null_leaves(request['mandate_fields'])), sorted(request['human_only_fields']))
        self.assertEqual(request['unresolved_fields'], [])
        # The contract's requested actions are shown for the host; the mandate's actions stay a human-only choice.
        self.assertEqual(request['requested_actions'], self.task['execution']['requested_actions'])
        self.assertIsNot(request['requested_actions'], self.task['execution']['requested_actions'])
        self.assertIsNone(request['mandate_fields']['actions'])
        self.assertIn('actions', request['human_only_fields'])
        mandate_schema = core.bundled_schema('host-context')['properties']['mandate']
        self.assertEqual(sorted(schema_leaves(mandate_schema)),
                         sorted(schema_leaves({'type': 'object', 'properties': {
                             key: (mandate_schema['properties'][key] if isinstance(value, dict) else {})
                             for key, value in request['mandate_fields'].items()}})))
        self.assertEqual(request['contract_sha256'], core.canonical_hash(self.task))
        self.assertEqual(request['mandate_fields']['contract_sha256'], core.canonical_hash(self.task))

    def test_request_cannot_pass_as_host_context(self):
        request = build(self.task, self.client)
        for candidate in (request, {'schema_version': '0.1', 'mandate': request['mandate_fields']}):
            with self.subTest(keys=sorted(candidate)):
                self.context = copy.deepcopy(candidate)
                result = self.verify(evidence=False)
                self.assertFalse(result['user_authorization']['authorized'])
                self.assertFalse(result['implementation_ready'])
                self.assertTrue(any(error.startswith('Host context ') for error in result['user_authorization']['errors']))


class RequestContentTests(unittest.TestCase):
    def setUp(self):
        self.task, self.client = candidate_task()

    def test_output_has_no_summary_or_remote_prose(self):
        request = build(self.task, self.client)
        self.assertEqual(set(request), REQUEST_KEYS)
        self.assertIs(request['issued'], False)
        dumped = json.dumps(request)
        for text in (self.task['objective'], 'Malformed dimensions', 'src/**', '.github/**', 'unittest',
                     'Fix thumbnail bounds', 'agent-approved', 'touch /tmp', 'Never execute'):
            self.assertNotIn(text, dumped)

    def test_adversarial_unreadable_instruction_is_only_a_labelled_diagnostic(self):
        tree = f'repos/acme/photos/git/trees/{"a" * 40}?recursive=1'
        self.client.overrides[tree] = {'truncated': False, 'tree': [
            {'path': p, 'type': 'blob'} for p in ('README.md', 'OWNER_APPROVED_CLICK_ACCEPT/AGENTS.md')]}
        self.client.failed = {'OWNER_APPROVED_CLICK_ACCEPT'}
        request = build(self.task, self.client)
        self.assertFalse(request['ready_for_issuance'])
        self.assertIn('Could not read repository instruction: OWNER_APPROVED_CLICK_ACCEPT/AGENTS.md',
                      request['preflight_errors'])
        self.assertIn('untrusted', request['preflight_errors_trust'])
        request.pop('preflight_errors')
        self.assertNotIn('OWNER_APPROVED', json.dumps(request))

    def test_authority_is_derived_from_live_identity(self):
        self.assertEqual(build(self.task, self.client)['mandate_fields']['authority'], 'owner')
        self.client.actor = dict(self.client.actor, id=8, login='maintainer')
        self.client.permission['user'] = dict(self.client.permission['user'], id=8, login='maintainer')
        fields = build(self.task, self.client)['mandate_fields']
        self.assertEqual((fields['credential_actor_id'], fields['authority']), (8, 'maintainer'))

    def test_failed_permission_leaves_derived_fields_unresolved_not_human(self):
        self.client.permission['role_name'] = 'write'
        request = build(self.task, self.client)
        self.assertFalse(request['ready_for_issuance'])
        self.assertEqual(request['unresolved_fields'], ['credential_actor_id', 'authority'])
        self.assertNotIn('credential_actor_id', request['human_only_fields'])
        self.assertEqual(sorted(null_leaves(request['mandate_fields'])),
                         sorted(request['human_only_fields'] + request['unresolved_fields']))
        self.assertIn('Credential needs exact admin/maintain role and matching user ID', request['preflight_errors'])

    def test_blocked_requests_report_preflight_errors(self):
        cases = {
            'draft': (lambda t: t.update(status='draft'), 'Contract is draft or has unanswered questions'),
            'pending prerequisite': (lambda t: t.update(prerequisites=[{'id': 'p', 'description': 'd', 'status': 'pending', 'evidence': ''}]),
                                     'Prerequisites are not satisfied with evidence: p (pending)'),
            'mode pending': (lambda t: t['execution'].update(mode='pending'), 'Execution mode is pending'),
            'base not default': (lambda t: t['execution'].update(base_ref='develop'),
                                 'Candidate base ref must match the source default branch'),
            'head equals base': (lambda t: t['execution'].update(head_ref='main'), 'Head and base refs must differ'),
            'no actions': (lambda t: t['execution'].update(requested_actions=[]), 'Contract requests no actions'),
            'duplicate actions': (lambda t: t['execution'].update(requested_actions=['implement', 'implement']),
                                  'Contract requested actions are duplicated'),
        }
        for name, (change, message) in cases.items():
            with self.subTest(case=name):
                task, client = candidate_task()
                change(task)
                request = build(task, client)
                self.assertFalse(request['ready_for_issuance'])
                self.assertIn(message, request['preflight_errors'])
                for expected in ('Missing human/host mandate', 'Current implement action is not authorized'):
                    self.assertNotIn(expected, request['preflight_errors'])

    def test_live_identity_and_overlap_block(self):
        task, client = candidate_task()
        task['source']['repository_id'] = 999
        self.assertIn('Reviewed repository or owner identity changed', build(task, client)['preflight_errors'])
        task, client = candidate_task()
        client.prs = [{'id': 3101, 'number': 31, 'title': 'Other', 'body': 'Fixes #12',
                       'html_url': 'https://github.com/acme/photos/pull/31', 'head': {'ref': 'other'}}]
        self.assertIn('Issue overlaps an open or unresolved prepared PR', build(task, client)['preflight_errors'])
        task, client = candidate_task()
        client.failed = {'repos/acme/photos/labels'}
        self.assertFalse(build(task, client)['ready_for_issuance'])

    def test_reads_equal_verify_without_host_context(self):
        _, verify_client = candidate_task()
        with patch.object(core.dt, 'datetime', Clock):
            lifecycle.verify(self.task, client=verify_client)
        request_client = candidate_task()[1]
        build(self.task, request_client)
        self.assertEqual(request_client.calls, verify_client.calls)


class RequestCLITests(unittest.TestCase):
    def invoke(self, *args, task=None, client=None):
        output = io.StringIO()

        class NoRead(io.StringIO):
            def read(self, *_):
                raise AssertionError('stdin must not be read')

        github = patch.object(core, 'GitHub', return_value=client) if client else patch.object(
            core, 'GitHub', side_effect=AssertionError('no GitHub read expected'))
        with contextlib.redirect_stdout(output), patch.object(core, 'read_json', return_value=task), github, \
                patch.object(core.dt, 'datetime', Clock), patch('sys.stdin', NoRead()):
            code = cli.main(list(args))
        return code, json.loads(output.getvalue())

    def test_ready_and_blocked_exit_codes_without_writing_files(self):
        task, client = candidate_task()
        with tempfile.TemporaryDirectory() as tmp:
            before = os.getcwd()
            os.chdir(tmp)
            try:
                code, result = self.invoke('authorization-request', 'task.json', task=task, client=client)
                self.assertEqual((code, result['ready_for_issuance']), (0, True))
                self.assertEqual(os.listdir(tmp), [])
            finally:
                os.chdir(before)
        task['status'] = 'draft'
        code, result = self.invoke('authorization-request', 'task.json', task=task, client=candidate_task()[1])
        self.assertEqual((code, result['ready_for_issuance']), (1, False))

    def test_legacy_or_unknown_schema_is_a_usage_error_without_reads(self):
        for version in ('0.1', '0.3', None):
            with self.subTest(version=version):
                code, result = self.invoke('authorization-request', 'task.json', task={'schema_version': version})
                self.assertEqual(code, 2)
                self.assertEqual(result['error']['code'], 'usage')
                self.assertNotIn('mandate_fields', result)

    def test_invalid_contracts_fail_before_reads_without_a_template(self):
        base, _ = candidate_task()
        missing = copy.deepcopy(base)
        del missing['source']
        unknown = copy.deepcopy(base)
        unknown['reviews'] = {}
        nested = copy.deepcopy(base)
        nested['execution']['head_repository_id'] = '101'
        for name, task in [('missing', missing), ('unknown', unknown), ('nested', nested),
                           ('bare', {'schema_version': '0.2'}), ('not object', ['0.2'])]:
            with self.subTest(case=name):
                code, result = self.invoke('authorization-request', 'task.json', task=task)
                self.assertEqual(code, 2 if name == 'not object' else 1)
                if name != 'not object':
                    self.assertEqual(result['error']['code'], 'invalid_contract')
                    self.assertTrue(result['error']['schema_errors'])
                self.assertNotIn('mandate_fields', json.dumps(result))

    def test_invalid_contract_payload_is_identical_with_and_without_budget(self):
        from agent_contribute import budget
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'task.json')
            with open(path, 'w', encoding='utf-8') as handle:
                json.dump({'schema_version': '0.2'}, handle)
            results = []
            for flags in ((), ('--report-budget',)):
                output = io.StringIO()
                with contextlib.redirect_stdout(output), \
                        patch.object(core, 'GitHub', side_effect=AssertionError('no GitHub read expected')), \
                        patch.object(budget, 'snapshot', side_effect=AssertionError('no budget read expected')):
                    code = cli.main([*flags, 'authorization-request', path])
                results.append((code, json.loads(output.getvalue())))
        self.assertEqual(results[0], results[1])
        code, result = results[0]
        self.assertEqual(code, 1)
        self.assertEqual(result['error']['code'], 'invalid_contract')
        self.assertIn('$.source: missing', result['error']['schema_errors'])

    def test_text_format_and_budget_prevalidation(self):
        code, result = self.invoke('--report-budget', 'authorization-request', 'task.json', task={'schema_version': '0.2'})
        self.assertEqual(code, 1)
        self.assertEqual(result['error']['code'], 'invalid_contract')


if __name__ == '__main__':
    unittest.main()
