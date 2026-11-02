"""Overlap dispositions (#7): a host record waives one topical overlap at one observed PR state, nothing else."""
import contextlib
import copy
import datetime as dt
import io
import unittest
from unittest.mock import patch

from agent_contribute import cli, core, textfmt
from tests import test_lifecycle
from tests.test_authorization import NOW, event_binding

SOURCE = 'acme/photos'
TOPICAL = 'Potential title/checklist overlap; review manually (shared title words: bounds, thumbnail)'
DIRECT = 'Explicit reference to this issue'
OVERLAP = 'Issue overlaps an open or unresolved prepared PR'
TIP, HEAD, MERGE_BASE = '1' * 40, 'c' * 40, 'e' * 40
TIP_ENDPOINT = 'repos/acme/photos/git/ref/heads/main'


def pr_detail(number=31, **changes):
    pr = {'id': 3000 + number + 100, 'number': number, 'title': 'Thumbnail bounds renderer refactor', 'body': None,
          'html_url': f'https://github.com/{SOURCE}/pull/{number}', 'state': 'open', 'draft': False,
          'updated_at': '2029-12-31T00:00:00Z', 'user': {'id': 8, 'login': 'someone', 'type': 'User'},
          'head': {'ref': 'renderer', 'sha': HEAD, 'repo': {'id': 101, 'full_name': SOURCE}},
          'base': {'ref': 'main', 'sha': TIP, 'repo': {'id': 101, 'full_name': SOURCE}}}
    pr.update(changes)
    return pr


def content_hash(pr):
    return core.canonical_hash({'title': pr['title'], 'body': pr['body'] or '', 'head_ref': pr['head']['ref'],
                                'base_ref': pr['base']['ref']})


def entry_for(pr, tip=TIP, reason=TOPICAL):
    """What a host computes from its own reads of the PR and the base-branch tip."""
    return {'repository_id': 101, 'pr_number': pr['number'], 'pr_id': pr['id'], 'author_id': pr['user']['id'],
            'disposition': 'unrelated', 'match_reason': reason, 'pr_state': pr['state'], 'draft': pr['draft'],
            'head_repository_id': pr['head']['repo']['id'], 'head_sha': pr['head']['sha'],
            'updated_at': pr['updated_at'], 'content_sha256': content_hash(pr),
            'comparison': {'base_tip_sha': tip, 'base_sha': MERGE_BASE, 'head_sha': pr['head']['sha'],
                           'material_sha256': 'f' * 64},
            'rationale': 'Reviewed the full comparison: a renderer refactor, unrelated to the bounds check'}


def record_for(task, context, entries):
    record = {'id': 'fixture-disposition-1', 'nonce': 'fixture-disposition-nonce-0001',
              'issued_at': (NOW - dt.timedelta(minutes=30)).isoformat(),
              'expires_at': (NOW + dt.timedelta(hours=1)).isoformat(),
              'contract_sha256': core.canonical_hash(task), 'mandate_sha256': core.canonical_hash(context['mandate']),
              'credential_actor_id': 7, 'dispositions': entries,
              'event': {'kind': 'human', 'reference': 'fixture://disposition-event', 'text_sha256': 'a' * 64,
                        'binding_sha256': '0' * 64}}
    record['event']['binding_sha256'] = event_binding(record)
    return record


class WaiverGitHub(test_lifecycle.IntegratedGitHub):
    """Adds base-branch refs and failing or missing PR details; every read is recorded."""

    def __init__(self):
        super().__init__()
        self.tips = {'main': TIP}
        self.on_detail = None

    def request(self, endpoint):
        if endpoint.startswith('repos/acme/photos/git/ref/heads/'):
            self.calls.append(endpoint)
            if endpoint in self.failed:
                raise core.ProtocolError('api_error', 'Synthetic base ref failure')
            ref = endpoint.rsplit('/heads/', 1)[1]
            return {'ref': 'refs/heads/' + ref, 'object': {'type': 'commit', 'sha': self.tips[ref]}}
        if endpoint.startswith('repos/acme/photos/pulls/'):
            number = int(endpoint.rsplit('/', 1)[1])
            if endpoint in self.failed or number not in self.details:
                self.calls.append(endpoint)
                raise core.ProtocolError('api_error', 'Synthetic PR detail failure')
            if self.on_detail:
                self.on_detail(number)
        return super().request(endpoint)


class WaiverFixture(unittest.TestCase):
    def setUp(self):
        test_lifecycle.IntegratedLifecycleTests.setUp(self)
        commit = self.client.commit
        self.client = WaiverGitHub()
        self.client.commit = commit
        self.pr = pr_detail()
        self.show(self.pr)
        self.base_context = copy.deepcopy(self.context)
        self.dispose([entry_for(self.pr)])

    verify = test_lifecycle.IntegratedLifecycleTests.verify

    def show(self, *prs, details=None):
        """The open-PR list shows these PRs; details default to the same objects."""
        self.client.prs = [copy.deepcopy(pr) for pr in prs]
        self.client.details = {pr['number']: copy.deepcopy(pr) for pr in (details if details is not None else prs)}

    def dispose(self, entries, **changes):
        record = record_for(self.task, self.base_context, entries)
        record.update(changes)
        record['event']['binding_sha256'] = event_binding(record)
        self.context = dict(copy.deepcopy(self.base_context), schema_version='0.2', overlap_dispositions=record)
        return record

    def detail_changed(self, **changes):
        pr = copy.deepcopy(self.pr)
        for key, value in changes.items():
            if '.' in key:
                outer, inner = key.split('.')
                pr[outer] = dict(pr[outer], **{inner: value})
            else:
                pr[key] = value
        self.client.details[self.pr['number']] = pr
        return pr

    def assert_blocked(self, result, message=None):
        self.assertFalse(result['implementation_ready'])
        self.assertIn(OVERLAP, result['stage_blockers']['implementation'])
        self.assertEqual(result['overlap_dispositions']['waived'], [])
        self.assertEqual(result['waived_duplicates'], [])
        if message:
            self.assertIn(message, result['overlap_dispositions']['errors'])

    def assert_waived(self, result, numbers=(31,)):
        self.assertTrue(result['implementation_ready'], result['stage_blockers']['implementation'])
        self.assertEqual([item['number'] for item in result['overlap_dispositions']['waived']], list(numbers))
        self.assertEqual(result['waived_duplicates'], result['overlap_dispositions']['waived'])


class HappyPathTests(WaiverFixture):
    def test_topical_overlap_is_waived_and_still_listed(self):
        result = self.verify(evidence=False)
        self.assert_waived(result)
        self.assertEqual(result['overlap_dispositions']['status'], 'evaluated')
        self.assertEqual([item['number'] for item in result['duplicates']], [31])  # never hidden
        self.assertEqual(result['blocking_duplicates'], [])
        waived = result['overlap_dispositions']['waived'][0]
        self.assertEqual((waived['pr_id'], waived['head_sha'], waived['base_tip_sha'], waived['reason']),
                         (self.pr['id'], HEAD, TIP, TOPICAL))
        self.assertIn('renderer refactor', waived['untrusted_rationale'])
        self.assertEqual(result['overlap_dispositions']['sha256'],
                         core.canonical_hash(self.context['overlap_dispositions']))

    def test_without_the_record_the_same_overlap_blocks(self):
        self.context = dict(copy.deepcopy(self.base_context), schema_version='0.2')
        result = self.verify(evidence=False)
        self.assertIn(OVERLAP, result['stage_blockers']['implementation'])
        self.assertEqual(result['overlap_dispositions']['status'], 'absent')

    def test_completion_after_publication_is_not_blocked_by_the_waived_pr(self):
        test_lifecycle.IntegratedLifecycleTests.publish(self)
        own = self.client.prs[0]
        self.show(own, self.pr, details=[own, self.pr])
        self.client.history = [copy.deepcopy(own)]
        self.context['final_signoff'] = test_lifecycle.signoff(self.task, self.context, self.evidence)
        result = self.verify()
        self.assertTrue(result['publication']['verified'], result['publication']['stage_errors'])
        self.assertTrue(result['completion_ready'], result['stage_blockers']['completion'])
        self.assertEqual([item['number'] for item in result['duplicates']], [30, 31])
        self.assertEqual(result['blocking_duplicates'], [])

    def test_waiver_never_removes_any_other_blocker(self):
        self.context['mandate']['actions'] = ['create_draft']
        self.context['mandate']['event']['binding_sha256'] = event_binding(self.context['mandate'])
        self.base_context = copy.deepcopy(self.context)
        del self.base_context['overlap_dispositions']
        self.base_context['schema_version'] = '0.1'
        self.dispose([entry_for(self.pr)])
        result = self.verify(evidence=False)
        self.assertEqual([item['number'] for item in result['overlap_dispositions']['waived']], [31])
        self.assertNotIn(OVERLAP, result['stage_blockers']['implementation'])
        self.assertIn('Current implement action is not authorized', result['stage_blockers']['implementation'])
        self.assertFalse(result['implementation_ready'])


class BoundFieldTests(WaiverFixture):
    def test_each_bound_observation_change_reblocks(self):
        cases = {
            'content': dict(body='Now about something else'),
            'head': {'head.sha': 'd' * 40},
            'head repository': {'head.repo': {'id': 909, 'full_name': 'fork/photos'}},
            'draft': dict(draft=True),  # updated_at deliberately unchanged
            'updated_at': dict(updated_at='2029-12-31T00:00:01Z'),
            'state': dict(state='closed'),
            'author': dict(user={'id': 9, 'login': 'x', 'type': 'User'}),
            'pr_id': dict(id=999),
            'url': dict(html_url='https://github.com/acme/photos/pull/31/'),
            'repository': {'base.repo': {'id': 202, 'full_name': SOURCE}},
        }
        for field, change in cases.items():
            with self.subTest(field=field):
                self.show(self.pr)
                self.detail_changed(**change)
                self.assert_blocked(self.verify(evidence=False), f'Overlap disposition stale for PR #31: {field}')

    def test_null_head_repository_is_not_waivable(self):
        self.detail_changed(**{'head.repo': None})
        self.assert_blocked(self.verify(evidence=False), 'Overlap disposition stale for PR #31: head repository')

    def test_title_and_head_ref_are_bound_through_the_content_hash(self):
        for change in (dict(title='Thumbnail bounds renderer refactor RFC-12A'),
                       dict(head=dict(self.pr['head'], ref='other-branch'))):
            with self.subTest(change=sorted(change)):
                changed = dict(self.pr, **change)
                self.show(changed)
                self.assert_blocked(self.verify(evidence=False), 'Overlap disposition stale for PR #31: content')

    def test_base_ref_change_reblocks(self):
        self.client.tips['release'] = TIP
        self.detail_changed(**{'base.ref': 'release'})
        self.assert_blocked(self.verify(evidence=False), 'Overlap disposition stale for PR #31: content')

    def test_restored_observations_are_waived_again(self):
        # The guarantee is equality of the enumerated observations now, not a history of past events (RO-02).
        self.detail_changed(draft=True)
        self.assert_blocked(self.verify(evidence=False))
        self.detail_changed(draft=False)
        self.assert_waived(self.verify(evidence=False))


class DirectReferenceTests(WaiverFixture):
    def test_direct_references_are_never_waivable(self):
        for name, change in [('local', dict(body='fixes #12')), ('qualified', dict(body='acme/photos#12')),
                             ('url', dict(body='https://github.com/acme/photos/issues/12')),
                             ('gh', dict(body='GH-12')),
                             ('branch', {'head': dict(self.pr['head'], ref='12-fix')})]:
            with self.subTest(reference=name):
                pr = dict(copy.deepcopy(self.pr), **change)
                self.show(pr)
                self.dispose([entry_for(pr)])
                result = self.verify(evidence=False)
                self.assert_blocked(result)
                self.assertIn(DIRECT, [item['reason'] for item in result['duplicates']])

    def test_a_record_claiming_the_direct_reason_waives_nothing(self):
        pr = dict(copy.deepcopy(self.pr), body='fixes #12')
        self.show(pr)
        self.dispose([entry_for(pr, reason=DIRECT)])
        self.assert_blocked(self.verify(evidence=False))

    def test_a_pr_that_becomes_direct_only_in_the_detail_read_blocks(self):
        self.detail_changed(body='Also fixes #12')
        result = self.verify(evidence=False)
        self.assert_blocked(result, 'Overlap disposition read found an explicit reference: PR #31')
        observed = {'number': 31, 'url': self.pr['html_url'], 'reason': DIRECT, 'repository': SOURCE,
                    'observed_in': 'disposition_read'}
        self.assertIn(observed, result['blocking_duplicates'])
        self.assertEqual(result['duplicates'][-1], observed)
        self.assertEqual(result['duplicates'][0]['reason'], TOPICAL)  # the list observation stays too


class MatchAndScopeTests(WaiverFixture):
    def test_prepared_reason_differing_from_the_live_reason_reblocks(self):
        self.task['discovery']['duplicate_prs'] = [{'number': 31, 'url': self.pr['html_url'], 'repository': SOURCE,
                                                    'reason': 'Potential title/checklist overlap; review manually (shared title words: bounds, thumbnail, x)'}]
        test_lifecycle.IntegratedLifecycleTests.rebind(self)
        self.base_context = copy.deepcopy(self.context)
        self.dispose([entry_for(self.pr)])
        self.assert_blocked(self.verify(evidence=False), 'Overlap disposition stale for PR #31: reason')

    def test_matching_prepared_entry_is_waived_with_the_live_one(self):
        self.task['discovery']['duplicate_prs'] = [{'number': 31, 'url': self.pr['html_url'], 'repository': SOURCE,
                                                    'reason': TOPICAL}]
        test_lifecycle.IntegratedLifecycleTests.rebind(self)
        self.base_context = copy.deepcopy(self.context)
        self.dispose([entry_for(self.pr)])
        self.client.calls.clear()
        self.assert_waived(self.verify(evidence=False))
        self.assertEqual(self.client.calls.count('repos/acme/photos/pulls/31'), 1)

    def test_a_same_numbered_entry_from_another_repository_still_blocks(self):
        other = {'number': 31, 'url': 'https://github.com/other/photos/pull/31', 'repository': 'other/photos',
                 'reason': TOPICAL}
        self.task['discovery']['duplicate_prs'] = [other]
        test_lifecycle.IntegratedLifecycleTests.rebind(self)
        self.base_context = copy.deepcopy(self.context)
        self.dispose([entry_for(self.pr)])
        result = self.verify(evidence=False)
        self.assertEqual([item['number'] for item in result['overlap_dispositions']['waived']], [31])
        self.assertIn(OVERLAP, result['stage_blockers']['implementation'])
        self.assertFalse(result['implementation_ready'])

    def test_other_overlaps_still_block(self):
        second = pr_detail(32, title='Thumbnail bounds cache')
        self.show(self.pr, second)
        result = self.verify(evidence=False)
        self.assertEqual([item['number'] for item in result['overlap_dispositions']['waived']], [31])
        self.assertIn(OVERLAP, result['stage_blockers']['implementation'])
        self.assertEqual([item['number'] for item in result['blocking_duplicates']], [32])


class ReconciliationTests(WaiverFixture):
    def test_absent_from_the_list_but_direct_in_the_detail_blocks(self):
        self.show(details=[dict(self.pr, body='fixes #12')])
        result = self.verify(evidence=False)
        self.assert_blocked(result, 'Overlap disposition read found an explicit reference: PR #31')
        self.assertEqual(result['duplicates'], [{'number': 31, 'url': self.pr['html_url'], 'reason': DIRECT,
                                                 'repository': SOURCE, 'observed_in': 'disposition_read'}])

    def test_absent_from_the_list_but_topical_in_the_detail_blocks(self):
        self.show(details=[self.pr])
        self.assert_blocked(self.verify(evidence=False), 'Overlap scan and disposition read disagree for PR #31')

    def test_topical_in_the_list_but_no_match_in_the_detail_blocks(self):
        self.detail_changed(title='Unrelated renderer work')
        self.assert_blocked(self.verify(evidence=False), 'Overlap scan and disposition read disagree for PR #31')

    def test_a_failed_read_for_an_unused_entry_blocks(self):
        self.show()
        result = self.verify(evidence=False)
        self.assert_blocked(result, 'Overlap disposition read failed for PR #31')
        self.assertEqual(result['duplicates'], [])  # an unknown is a blocker, never a claimed overlap

    def test_missing_head_repository_key_is_a_structured_blocker(self):
        head = dict(self.pr['head'])
        del head['repo']  # omitted, not an explicit null (deleted fork)
        self.detail_changed(head=head)
        result = self.verify(evidence=False)
        self.assert_blocked(result, 'Overlap disposition read failed for PR #31')

    def test_malformed_detail_blocks(self):
        self.detail_changed(head={'ref': 'renderer', 'repo': {'id': 101}})
        self.assert_blocked(self.verify(evidence=False), 'Overlap disposition read failed for PR #31')

    def test_unused_entry_is_informational(self):
        self.show(details=[dict(self.pr, title='Unrelated renderer work')])
        result = self.verify(evidence=False)
        self.assertTrue(result['implementation_ready'], result['stage_blockers']['implementation'])
        self.assertEqual(result['overlap_dispositions']['unused'], [31])
        self.assertEqual(result['overlap_dispositions']['errors'], [])

    def test_prepared_entry_without_a_current_match_stays_blocking(self):
        self.task['discovery']['duplicate_prs'] = [{'number': 31, 'url': self.pr['html_url'], 'repository': SOURCE,
                                                    'reason': TOPICAL}]
        test_lifecycle.IntegratedLifecycleTests.rebind(self)
        self.base_context = copy.deepcopy(self.context)
        self.dispose([entry_for(self.pr)])
        self.show(details=[dict(self.pr, state='closed', title='Unrelated renderer work')])
        result = self.verify(evidence=False)
        self.assert_blocked(result, 'Overlap disposition cannot clear prepared PR #31 that no longer matches')
        self.assertEqual(result['overlap_dispositions']['unused'], [])


class OwnWorkTests(WaiverFixture):
    def test_a_pr_by_the_credential_actor_is_never_waivable(self):
        own = pr_detail(user={'id': 7, 'login': 'human', 'type': 'User'})
        self.show(own)
        self.dispose([entry_for(own)])
        result = self.verify(evidence=False)
        self.assertEqual(result['overlap_dispositions']['status'], 'invalid')
        self.assert_blocked(result, 'Overlap disposition names a PR by the credential actor: #31')
        lying = entry_for(own)
        lying['author_id'] = 8
        self.dispose([lying])
        self.assert_blocked(self.verify(evidence=False), 'Overlap disposition stale for PR #31: author')


class ExpiryTests(WaiverFixture):
    def test_expiry_during_the_reads_waives_nothing(self):
        record = self.dispose([entry_for(self.pr)], expires_at=(NOW + dt.timedelta(seconds=5)).isoformat())
        later = NOW + dt.timedelta(minutes=1)

        class Advancing(dt.datetime):
            moved = False

            @classmethod
            def now(cls, tz=None):
                return (later if cls.moved else NOW).astimezone(tz)

        def advance(number):
            Advancing.moved = True
        self.client.on_detail = advance
        with patch.object(core.dt, 'datetime', Advancing):
            result = self.verify(evidence=False)
        self.assertEqual(record['expires_at'], self.context['overlap_dispositions']['expires_at'])
        self.assertFalse(result['implementation_ready'])
        self.assertFalse(result['draft_create_ready'])
        self.assertEqual(result['next_action'], 'resolve_blockers')
        for stage in ('implementation', 'draft', 'completion'):
            self.assertIn('Overlap disposition record expired', result['stage_blockers'][stage])
        self.assertEqual(result['overlap_dispositions']['waived'], [])
        self.assertEqual([item['number'] for item in result['blocking_duplicates']], [31])
        self.assertEqual(result['overlap_dispositions']['status'], 'invalid')

    def test_already_expired_record_waives_nothing(self):
        self.dispose([entry_for(self.pr)], issued_at=(NOW - dt.timedelta(hours=3)).isoformat(),
                     expires_at=(NOW - dt.timedelta(minutes=1)).isoformat())
        self.assert_blocked(self.verify(evidence=False), 'Overlap disposition record expired')


class UnknownTests(WaiverFixture):
    def test_incomplete_open_pr_scan_waives_nothing_and_reads_no_details(self):
        self.client.failed = {'repos/acme/photos/pulls?state=open'}
        self.client.calls.clear()
        result = self.verify(evidence=False)
        self.assertEqual(result['overlap_dispositions']['waived'], [])
        self.assertIn('Overlap disposition needs a complete open-PR scan', result['overlap_dispositions']['errors'])
        self.assertNotIn('repos/acme/photos/pulls/31', self.client.calls)
        self.assertFalse(result['implementation_ready'])


class BindingTests(WaiverFixture):
    def test_invalid_records_waive_nothing_and_read_nothing(self):
        cases = {
            'Overlap disposition contract hash differs': dict(contract_sha256='0' * 64),
            'Overlap disposition mandate hash differs': dict(mandate_sha256='0' * 64),
            'Overlap disposition credential actor differs': dict(credential_actor_id=99),
            'Overlap disposition reuses the mandate event identity': dict(nonce='fixture-only-random-nonce-000001'),
            'Invalid human event interval (future, reversed or over 24 hours)':
                dict(issued_at=(NOW + dt.timedelta(minutes=5)).isoformat()),
        }
        for message, changes in cases.items():
            with self.subTest(message=message):
                self.dispose([entry_for(self.pr)], **changes)
                self.client.calls.clear()
                result = self.verify(evidence=False)
                self.assert_blocked(result, message)
                self.assertEqual(result['overlap_dispositions']['status'], 'invalid')
                self.assertNotIn('repos/acme/photos/pulls/31', self.client.calls)
        repeated = self.dispose([entry_for(self.pr), entry_for(self.pr)])
        self.assertEqual(len(repeated['dispositions']), 2)
        self.assert_blocked(self.verify(evidence=False), 'Overlap disposition repeats a PR: #31')
        other = entry_for(self.pr)
        other['repository_id'] = 202
        self.dispose([other])
        self.assert_blocked(self.verify(evidence=False), 'Overlap disposition names another repository: #31')
        record = self.dispose([entry_for(self.pr)])
        record['event']['binding_sha256'] = '1' * 64
        self.assert_blocked(self.verify(evidence=False), 'Overlap disposition event binding hash differs')

    def test_record_needs_a_valid_mandate(self):
        self.base_context['mandate']['credential_actor_id'] = 99
        self.base_context['mandate']['event']['binding_sha256'] = event_binding(self.base_context['mandate'])
        self.dispose([entry_for(self.pr)])
        self.assert_blocked(self.verify(evidence=False), 'Overlap disposition requires a valid mandate')


class BaseTipTests(WaiverFixture):
    def test_an_advancing_base_reblocks_even_with_everything_else_equal(self):
        # A -> B -> H: the head is fixed, but the base tip moved, so the merge base and patch can change (RO-07).
        self.client.tips['main'] = '2' * 40
        self.assert_blocked(self.verify(evidence=False), 'Overlap disposition stale for PR #31: base tip')

    def test_the_tip_comes_from_the_ref_not_the_pr_base_sha(self):
        self.detail_changed(**{'base.sha': '9' * 40})
        self.show(self.client.details[31])
        self.assert_waived(self.verify(evidence=False))
        self.show(self.pr)
        self.client.tips['main'] = '3' * 40  # PR base.sha still equals the bound tip
        self.assert_blocked(self.verify(evidence=False), 'Overlap disposition stale for PR #31: base tip')

    def test_malformed_base_ref_blocks(self):
        original = self.client.request
        for name, value in [('tag object', {'ref': 'refs/heads/main', 'object': {'type': 'tag', 'sha': TIP}}),
                            ('other ref', {'ref': 'refs/heads/mainline', 'object': {'type': 'commit', 'sha': TIP}}),
                            ('short sha', {'ref': 'refs/heads/main', 'object': {'type': 'commit', 'sha': '1' * 39}}),
                            ('list', [{'ref': 'refs/heads/main', 'object': {'type': 'commit', 'sha': TIP}}])]:
            with self.subTest(case=name):
                self.client.request = lambda endpoint, value=value: (
                    copy.deepcopy(value) if endpoint == TIP_ENDPOINT else original(endpoint))
                self.assert_blocked(self.verify(evidence=False), 'Overlap disposition base tip read failed for PR #31')
        self.client.request = original

    def test_unreadable_tip_blocks(self):
        self.client.failed = {TIP_ENDPOINT}
        self.assert_blocked(self.verify(evidence=False), 'Overlap disposition base tip read failed for PR #31')

    def test_a_failed_shared_base_ref_read_happens_once(self):
        second = pr_detail(32, title='Thumbnail bounds cache')
        self.show(self.pr, second)
        self.dispose([entry_for(self.pr), entry_for(second)])
        self.client.failed = {TIP_ENDPOINT}
        self.client.calls.clear()
        result = self.verify(evidence=False)
        self.assertEqual(self.client.calls.count(TIP_ENDPOINT), 1)
        for number in (31, 32):
            self.assertIn(f'Overlap disposition base tip read failed for PR #{number}',
                          result['overlap_dispositions']['errors'])
        self.assertEqual(result['overlap_dispositions']['waived'], [])
        self.assertFalse(result['implementation_ready'])

    def test_reads_are_bounded_and_deduplicated(self):
        second = pr_detail(32, title='Thumbnail bounds cache')
        self.show(self.pr, second)
        self.dispose([entry_for(self.pr), entry_for(second)])
        self.client.calls.clear()
        self.assert_waived(self.verify(evidence=False), numbers=(31, 32))
        extra = [call for call in self.client.calls if '/pulls/3' in call or '/git/ref/' in call]
        self.assertEqual(sorted(extra), ['repos/acme/photos/git/ref/heads/main', 'repos/acme/photos/pulls/31',
                                         'repos/acme/photos/pulls/32'])

    def test_without_a_record_no_extra_reads_happen(self):
        self.context = copy.deepcopy(self.base_context)
        self.client.calls.clear()
        self.verify(evidence=False)
        self.assertFalse([call for call in self.client.calls if '/pulls/31' in call or '/git/ref/' in call])


class TextOutputTests(WaiverFixture):
    def test_text_output_discloses_the_waiver(self):
        result = self.verify(evidence=False)
        text = textfmt.render('verify', result, stage=('implementation', True))
        self.assertIn('Overlap dispositions (host-asserted): evaluated', text)
        self.assertIn('Overlaps waived by host disposition: 1 - PR #31; see JSON overlap_dispositions', text)
        self.context = dict(copy.deepcopy(self.base_context), schema_version='0.1')
        self.assertNotIn('Overlap dispositions', textfmt.render('verify', self.verify(evidence=False)))

    def test_text_output_shows_disposition_errors(self):
        self.client.tips['main'] = '2' * 40
        text = textfmt.render('verify', self.verify(evidence=False))
        self.assertIn('Disposition errors (1):', text)
        self.assertIn('Overlap disposition stale for PR #31: base tip', text)

    def test_cli_exit_code_follows_the_waiver(self):
        output = io.StringIO()
        with patch.object(core, 'read_json', return_value=self.task), \
                patch('agent_contribute.cli.read_host_context_stdin', return_value=self.context), \
                patch.object(core, 'GitHub', return_value=self.client), contextlib.redirect_stdout(output):
            code = cli.main(['verify', 'task.json', '--stage', 'implementation', '--host-context-stdin'])
        self.assertEqual(code, 0, output.getvalue())


if __name__ == '__main__':
    unittest.main()
