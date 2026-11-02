"""Host-context 0.2: versions, schema and the overlap_dispositions report when the record cannot waive anything."""
import contextlib
import copy
import datetime as dt
import io
import hashlib
import json
import unittest

from agent_contribute import authorization, cli, core
from tests import test_lifecycle
from tests.test_authorization import NOW, event_binding

SECTION_KEYS = {'status', 'trust', 'sha256', 'errors', 'waived', 'unused'}


def section_for(task, context, number=31, author_id=8):
    record = {'id': 'fixture-disposition-1', 'nonce': 'fixture-disposition-nonce-0001',
              'issued_at': (NOW - dt.timedelta(minutes=30)).isoformat(),
              'expires_at': (NOW + dt.timedelta(hours=1)).isoformat(),
              'contract_sha256': core.canonical_hash(task),
              'mandate_sha256': core.canonical_hash(context['mandate']),
              'credential_actor_id': 7,
              'dispositions': [{
                  'repository_id': 101, 'pr_number': number, 'pr_id': 3101, 'author_id': author_id,
                  'disposition': 'unrelated',
                  'match_reason': 'Potential title/checklist overlap; review manually (shared title words: bounds, thumbnail)',
                  'pr_state': 'open', 'draft': False, 'head_repository_id': 101, 'head_sha': 'c' * 40,
                  'updated_at': '2029-12-31T00:00:00Z', 'content_sha256': 'd' * 64,
                  'comparison': {'base_tip_sha': 'b' * 40, 'base_sha': 'e' * 40, 'head_sha': 'c' * 40,
                                 'material_sha256': 'f' * 64},
                  'rationale': 'Reviewed code: a renderer refactor, unrelated to the bounds check'}],
              'event': {'kind': 'human', 'reference': 'fixture://disposition-event', 'text_sha256': 'a' * 64,
                        'binding_sha256': '0' * 64}}
    record['event']['binding_sha256'] = event_binding(record)
    return record


def rebind_event(record):
    record['event']['binding_sha256'] = event_binding(record)
    return record


class HostContextSchemaTests(unittest.TestCase):
    def setUp(self):
        self.task, _ = test_lifecycle.candidate_task()
        self.context = test_lifecycle.host_context(self.task)

    def errors(self, document):
        return core.schema_errors(document, core.host_context_schema(document))

    def test_versions_are_exact_and_the_section_exists_only_in_0_2(self):
        section = section_for(self.task, self.context)
        self.assertEqual(self.errors(dict(self.context, schema_version='0.2')), [])
        self.assertEqual(self.errors(dict(self.context, schema_version='0.2', overlap_dispositions=section)), [])
        self.assertEqual(self.errors(self.context), [])
        self.assertTrue(self.errors(dict(self.context, overlap_dispositions=section)))  # 0.1 is closed
        for version in ('0.3', 0.2, None, '0.20', ['0.2']):
            with self.subTest(version=version):
                self.assertTrue(self.errors(dict(self.context, schema_version=version)))
        missing = dict(self.context, schema_version='0.2', overlap_dispositions=section)
        del missing['mandate']
        self.assertTrue(self.errors(missing))
        self.assertTrue(self.errors(['0.2']))
        with self.assertRaises(core.ProtocolError):
            core.bundled_schema('host-context', '0.3')

    def test_section_fields_are_strict(self):
        base = dict(self.context, schema_version='0.2', overlap_dispositions=section_for(self.task, self.context))
        changes = [
            ('dispositions', lambda s: s.update(dispositions=[])),
            ('too many', lambda s: s.update(dispositions=s['dispositions'] * 21)),
            ('kind', lambda s: s['dispositions'][0].update(disposition='complementary')),
            ('state', lambda s: s['dispositions'][0].update(pr_state='closed')),
            ('draft type', lambda s: s['dispositions'][0].update(draft='false')),
            ('head sha', lambda s: s['dispositions'][0].update(head_sha='C' * 40)),
            ('comparison extra', lambda s: s['dispositions'][0]['comparison'].update(diff_url='x')),
            ('no base tip', lambda s: s['dispositions'][0]['comparison'].pop('base_tip_sha')),
            ('base tip format', lambda s: s['dispositions'][0]['comparison'].update(base_tip_sha='main')),
            ('missing author', lambda s: s['dispositions'][0].pop('author_id')),
            ('extra field', lambda s: s.update(waive_all=True)),
            ('event kind', lambda s: s['event'].update(kind='host')),
            ('short nonce', lambda s: s.update(nonce='short')),
        ]
        for name, change in changes:
            with self.subTest(change=name):
                document = copy.deepcopy(base)
                change(document['overlap_dispositions'])
                self.assertTrue(self.errors(document))

    def test_mandate_hash_is_independent_of_the_wrapper_version(self):
        def independent(value):
            encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                                 separators=(',', ':')).encode('utf-8')
            return hashlib.sha256(encoded).hexdigest()
        _, client = test_lifecycle.candidate_task()
        hashes = []
        for document in (self.context, dict(self.context, schema_version='0.2'),
                         dict(self.context, schema_version='0.2',
                              overlap_dispositions=section_for(self.task, self.context))):
            result = authorization.check(self.task, document, client, NOW)
            self.assertTrue(result['authorized'], result['errors'])
            hashes.append(result['mandate_sha256'])
        self.assertEqual(set(hashes), {independent(self.context['mandate'])})


class UnusableRecordTests(unittest.TestCase):
    setUp = test_lifecycle.IntegratedLifecycleTests.setUp
    verify = test_lifecycle.IntegratedLifecycleTests.verify

    def overlap(self):
        # A topical (non-direct) overlap: shared title words, no issue reference.
        self.client.prs = [{'id': 3101, 'number': 31, 'title': 'Thumbnail bounds renderer refactor', 'body': None,
                            'html_url': 'https://github.com/acme/photos/pull/31', 'head': {'ref': 'renderer'}}]

    def run_variants(self):
        base = copy.deepcopy(self.context)
        variants = {'0.1': base, '0.2': dict(base, schema_version='0.2')}
        results, calls = {}, {}
        for name, document in variants.items():
            self.context = copy.deepcopy(document)
            self.client.calls.clear()
            results[name] = self.verify()
            calls[name] = list(self.client.calls)
        self.context = base
        return results, calls

    def assert_identical_except_section(self, results):
        reference = results['0.1']
        self.assertNotIn('overlap_dispositions', reference)
        other = dict(results['0.2'])
        self.assertEqual(other.pop('overlap_dispositions'), {'status': 'absent', 'trust': 'host-asserted',
                                                              'sha256': None, 'errors': [], 'waived': [], 'unused': []})
        self.assertEqual(other.pop('waived_duplicates'), [])
        self.assertEqual(other, reference)

    def test_0_2_without_a_record_verifies_exactly_like_0_1(self):
        self.overlap()
        results, calls = self.run_variants()
        self.assert_identical_except_section(results)
        self.assertEqual(calls['0.2'], calls['0.1'])
        self.assertIn('Issue overlaps an open or unresolved prepared PR',
                      results['0.2']['stage_blockers']['implementation'])

    def test_publication_and_final_signoff_verify_identically_under_0_2(self):
        test_lifecycle.IntegratedLifecycleTests.publish(self)
        self.context['final_signoff'] = test_lifecycle.signoff(self.task, self.context, self.evidence)
        results, calls = self.run_variants()
        self.assert_identical_except_section(results)
        self.assertTrue(results['0.2']['completion_ready'], results['0.2']['stage_blockers'])
        self.assertEqual(results['0.2']['human_signoff']['status'], 'passed')
        self.assertEqual(calls['0.2'], calls['0.1'])

    def test_section_binding_errors_are_reported_without_changing_gates(self):
        self.overlap()
        reference = self.verify()
        cases = {
            'Overlap disposition contract hash differs': lambda s: s.update(contract_sha256='0' * 64),
            'Overlap disposition mandate hash differs': lambda s: s.update(mandate_sha256='0' * 64),
            'Overlap disposition credential actor differs': lambda s: s.update(credential_actor_id=99),
            'Overlap disposition names a PR by the credential actor: #31':
                lambda s: s['dispositions'][0].update(author_id=7),
            'Overlap disposition comparison head differs from bound head: #31':
                lambda s: s['dispositions'][0]['comparison'].update(head_sha='9' * 40),
            'Overlap disposition repeats a PR: #31': lambda s: s.update(dispositions=s['dispositions'] * 2),
            'Overlap disposition names another repository: #31':
                lambda s: s['dispositions'][0].update(repository_id=202),
            'Overlap disposition reuses the mandate event identity': lambda s: s.update(nonce=self.context['mandate']['nonce']),
            'Overlap disposition record expired': lambda s: s.update(
                issued_at=(NOW - dt.timedelta(hours=3)).isoformat(), expires_at=(NOW - dt.timedelta(minutes=1)).isoformat()),
            'Invalid human event interval (future, reversed or over 24 hours)': lambda s: s.update(
                issued_at=(NOW + dt.timedelta(minutes=5)).isoformat()),
        }
        for message, change in cases.items():
            with self.subTest(message=message):
                section = section_for(self.task, self.context)
                change(section)
                rebind_event(section)
                document = dict(copy.deepcopy(self.context), schema_version='0.2', overlap_dispositions=section)
                base, self.context = self.context, document
                try:
                    result = self.verify()
                finally:
                    self.context = base
                report = result.pop('overlap_dispositions')
                self.assertEqual(result.pop('waived_duplicates'), [])
                self.assertEqual(report['status'], 'invalid')
                self.assertIn(message, report['errors'])
                self.assertEqual(result, reference)
        section = section_for(self.task, self.context)
        section['event']['binding_sha256'] = '1' * 64
        base, self.context = self.context, dict(copy.deepcopy(self.context), schema_version='0.2',
                                                overlap_dispositions=section)
        try:
            report = self.verify()['overlap_dispositions']
        finally:
            self.context = base
        self.assertIn('Overlap disposition event binding hash differs', report['errors'])

    def test_malformed_section_fails_the_host_context_closed(self):
        section = section_for(self.task, self.context)
        section['dispositions'][0]['disposition'] = 'waive'
        self.context = dict(self.context, schema_version='0.2', overlap_dispositions=section)
        result = self.verify(evidence=False)
        self.assertFalse(result['implementation_ready'])
        self.assertFalse(result['user_authorization']['authorized'])
        self.assertEqual(result['overlap_dispositions']['status'], 'invalid')
        self.assertIn('Host context schema is invalid', result['overlap_dispositions']['errors'])



class InstructionsTests(unittest.TestCase):
    def test_instructions_report_both_host_context_versions(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(cli.main(['instructions']), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result['supported_host_context_versions'], ['0.1', '0.2'])
        self.assertEqual(result['resources']['host_context_schema_0.2'],
                         'agent_contribute/schemas/host-context/0.2.schema.json')
        self.assertIn('overlap dispositions waive only bound topical overlaps', result['host_authorization'])

if __name__ == '__main__':
    unittest.main()
