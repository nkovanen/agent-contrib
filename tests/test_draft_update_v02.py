"""Host-context 0.2 draft_update (#21, slice 1): strictly parsed and reported, never consulted by a gate."""
import copy
import datetime as dt
import unittest

from agent_contribute import core
from tests import test_lifecycle
from tests.test_authorization import NOW, event_binding
from tests.test_host_context_v02 import section_for as disposition_for

REPORT_KEYS = {'status', 'trust', 'sha256', 'from_head', 'candidate_head', 'current', 'errors', 'note'}


def update_for(task, context, evidence, **changes):
    record = {'id': 'fixture-update-1', 'nonce': 'fixture-update-random-nonce-0001',
              'issued_at': (NOW - dt.timedelta(minutes=20)).isoformat(),
              'expires_at': (NOW + dt.timedelta(hours=2)).isoformat(),
              'contract_sha256': core.canonical_hash(task), 'mandate_sha256': core.canonical_hash(context['mandate']),
              'credential_actor_id': 7, 'repository_id': 101, 'pr_number': 30, 'pr_id': 3001,
              'from_head': evidence['git_head'],
              'event': {'kind': 'human', 'reference': 'fixture://update-event', 'text_sha256': 'e' * 64,
                        'binding_sha256': '0' * 64}}
    record.update(changes)
    record['event']['binding_sha256'] = event_binding(record)
    return record


class DraftUpdateSchemaTests(unittest.TestCase):
    def setUp(self):
        self.task, _ = test_lifecycle.candidate_task()
        self.context = test_lifecycle.host_context(self.task)
        self.section = update_for(self.task, self.context, {'git_head': 'c' * 40})

    def errors(self, document):
        return core.schema_errors(document, core.host_context_schema(document))

    def test_the_section_exists_only_in_0_2_and_coexists_with_dispositions(self):
        self.assertEqual(self.errors(dict(self.context, schema_version='0.2', draft_update=self.section)), [])
        both = dict(self.context, schema_version='0.2', draft_update=self.section,
                    overlap_dispositions=disposition_for(self.task, self.context))
        self.assertEqual(self.errors(both), [])
        self.assertTrue(self.errors(dict(self.context, draft_update=self.section)), '0.1 is closed')

    def test_section_fields_are_strict(self):
        changes = {
            'extra field': lambda s: s.update(to_head='d' * 40),
            'missing from_head': lambda s: s.pop('from_head'),
            'short from_head': lambda s: s.update(from_head='c' * 39),
            'uppercase from_head': lambda s: s.update(from_head='C' * 40),
            'pr_id zero': lambda s: s.update(pr_id=0),
            'pr_number text': lambda s: s.update(pr_number='30'),
            'repository_id bool': lambda s: s.update(repository_id=True),
            'actor missing': lambda s: s.pop('credential_actor_id'),
            'mandate hash format': lambda s: s.update(mandate_sha256='x'),
            'short nonce': lambda s: s.update(nonce='short'),
            'event kind': lambda s: s['event'].update(kind='host'),
            'event extra': lambda s: s['event'].update(note='x'),
            'not an object': lambda s: s.clear(),
        }
        for name, change in changes.items():
            with self.subTest(change=name):
                section = copy.deepcopy(self.section)
                change(section)
                self.assertTrue(self.errors(dict(self.context, schema_version='0.2', draft_update=section)))

    def test_mandate_hash_is_unchanged_by_the_section(self):
        from agent_contribute import authorization
        _, client = test_lifecycle.candidate_task()
        hashes = {authorization.check(self.task, document, client, NOW)['mandate_sha256'] for document in
                  (self.context, dict(self.context, schema_version='0.2', draft_update=self.section))}
        self.assertEqual(hashes, {core.canonical_hash(self.context['mandate'])})


class MissingPulls(dict):
    """PR details the fixture does not define are a failed read, as on GitHub, not a test crash."""
    def __missing__(self, number):
        raise core.ProtocolError('api_error', 'Synthetic missing pull request')


class InertReportTests(unittest.TestCase):
    def setUp(self):
        test_lifecycle.IntegratedLifecycleTests.setUp(self)
        self.client.details = MissingPulls(self.client.details)

    verify = test_lifecycle.IntegratedLifecycleTests.verify
    publish = test_lifecycle.IntegratedLifecycleTests.publish

    def with_update(self, record=None, **extra):
        document = dict(copy.deepcopy(self.context), schema_version='0.2',
                        draft_update=record or update_for(self.task, self.context, self.evidence), **extra)
        base, self.context = self.context, document
        self.client.calls.clear()
        try:
            return self.verify(), list(self.client.calls)
        finally:
            self.context = base

    def without_update(self, **extra):
        document = dict(copy.deepcopy(self.context), schema_version='0.2', **extra)
        base, self.context = self.context, document
        self.client.calls.clear()
        try:
            return self.verify(), list(self.client.calls)
        finally:
            self.context = base

    def assert_inert(self, **extra):
        reference, reference_calls = self.without_update(**extra)
        self.assertNotIn('draft_update', reference, 'no record, no report: byte-identical to today')
        result, calls = self.with_update(**extra)
        report = result.pop('draft_update')
        self.assertEqual(result, reference, 'gates, blockers, next_action and every other field are unchanged')
        self.assertEqual(calls, reference_calls, 'no extra GitHub reads')
        return report

    def test_valid_record_is_reported_not_evaluated_before_and_after_publication(self):
        report = self.assert_inert()
        self.assertEqual(report['status'], 'invalid', 'a draft update needs a publication claim')
        self.assertIn('Draft update requires a publication claim', report['errors'])
        self.publish()
        report = self.assert_inert()
        self.assertEqual(set(report), REPORT_KEYS)
        self.assertEqual((report['status'], report['errors'], report['current'], report['candidate_head']),
                         ('not_evaluated', [], True, None))
        self.assertEqual(report['from_head'], self.evidence['git_head'])
        self.assertEqual(report['sha256'], core.canonical_hash(update_for(self.task, self.context, self.evidence)))
        self.assertIn('nothing is authorized', report['note'])

    def test_completion_is_unchanged_by_the_section(self):
        self.publish()
        self.context['final_signoff'] = test_lifecycle.signoff(self.task, self.context, self.evidence)
        report = self.assert_inert()
        self.assertEqual(report['status'], 'not_evaluated')

    def test_coexists_with_overlap_dispositions_without_changing_their_result(self):
        self.publish()
        self.client.prs.append({'id': 3101, 'number': 31, 'title': 'Thumbnail bounds renderer refactor', 'body': None,
                                'html_url': 'https://github.com/acme/photos/pull/31', 'head': {'ref': 'renderer'}})
        report = self.assert_inert(overlap_dispositions=disposition_for(self.task, self.context))
        self.assertEqual(report['status'], 'not_evaluated')

    def test_binding_errors_are_reported_without_changing_gates(self):
        self.publish()
        signoff = test_lifecycle.signoff(self.task, self.context, self.evidence)
        disposition = disposition_for(self.task, self.context)
        cases = {
            'Draft update contract hash differs': dict(contract_sha256='0' * 64),
            'Draft update mandate hash differs': dict(mandate_sha256='0' * 64),
            'Draft update credential actor differs': dict(credential_actor_id=99),
            'Draft update names another repository': dict(repository_id=202),
            'Draft update names another pull request than the publication claim': dict(pr_number=31),
            'Draft update names another pull request ID than the publication claim': dict(pr_id=9999),
            'Draft update reuses the mandate event identity': dict(nonce=self.context['mandate']['nonce']),
            'Draft update reuses the final sign-off event identity': dict(id=signoff['id']),
            'Draft update reuses the overlap disposition event identity': dict(
                event={'kind': 'human', 'reference': disposition['event']['reference'], 'text_sha256': 'e' * 64,
                       'binding_sha256': '0' * 64}),
            'Invalid human event interval (future, reversed or over 24 hours)': dict(
                issued_at=(NOW + dt.timedelta(minutes=5)).isoformat()),
        }
        for message, change in cases.items():
            with self.subTest(message=message):
                extra = {}
                if 'final sign-off' in message:
                    extra['final_signoff'] = signoff
                if 'overlap disposition' in message:
                    extra['overlap_dispositions'] = disposition
                record = update_for(self.task, self.context, self.evidence, **copy.deepcopy(change))
                reference, reference_calls = self.without_update(**extra)
                result, calls = self.with_update(record, **extra)
                report = result.pop('draft_update')
                self.assertEqual(result, reference)
                self.assertEqual(calls, reference_calls)
                self.assertEqual(report['status'], 'invalid')
                self.assertIn(message, report['errors'])
        record = update_for(self.task, self.context, self.evidence)
        record['event']['binding_sha256'] = '1' * 64
        report = self.with_update(record)[0]['draft_update']
        self.assertIn('Draft update event binding hash differs', report['errors'])

    def test_a_record_under_an_invalid_mandate_is_invalid(self):
        self.publish()
        self.context['mandate']['event']['binding_sha256'] = '1' * 64  # the mandate itself no longer validates
        record = update_for(self.task, self.context, self.evidence)  # bound to that same (invalid) mandate
        reference, _ = self.without_update()
        result, _ = self.with_update(record)
        report = result.pop('draft_update')
        self.assertEqual(result, reference)
        self.assertFalse(result['user_authorization']['historical_valid'])
        self.assertEqual(report['errors'], ['Draft update requires a valid mandate'])

    def test_an_expired_record_is_reported_but_not_an_error(self):
        self.publish()
        record = update_for(self.task, self.context, self.evidence, issued_at=(NOW - dt.timedelta(hours=3)).isoformat(),
                            expires_at=(NOW - dt.timedelta(minutes=1)).isoformat())
        reference, _ = self.without_update()
        result, _ = self.with_update(record)
        report = result.pop('draft_update')
        self.assertEqual(result, reference)
        self.assertEqual((report['status'], report['current'], report['errors']), ('not_evaluated', False, []))

    def test_a_malformed_section_fails_the_host_context_closed(self):
        record = update_for(self.task, self.context, self.evidence)
        record['from_head'] = 'not-a-sha'
        result, _ = self.with_update(record)
        self.assertFalse(result['user_authorization']['authorized'])
        self.assertEqual(result['draft_update']['status'], 'invalid')
        self.assertIn('Host context schema is invalid', result['draft_update']['errors'])

    def test_a_0_1_context_never_reports_the_section(self):
        self.publish()
        reference = self.verify()
        self.assertNotIn('draft_update', reference)


if __name__ == '__main__':
    unittest.main()
