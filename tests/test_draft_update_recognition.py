"""Draft-update recognition after the one host push (#21 slice 2): every fact of I(P) and T(E) is required.

Only external GETs and the clock are fake: the real lifecycle, PR identity and Git reads run against a temporary
repository whose branch moves from the creation head A (= the round's from_head F) to the evidence head E.
"""
import copy
import datetime as dt
import pathlib
import unittest

from agent_contribute import core
from tests import test_lifecycle
from tests.test_authorization import NOW, event_binding
from tests.test_draft_update_v02 import update_for

FORBIDDEN = ('head_ref_force_pushed', 'head_ref_deleted', 'head_ref_restored', 'closed', 'reopened', 'merged',
             'ready_for_review', 'convert_to_draft')


class UpdateGitHub(test_lifecycle.IntegratedGitHub):
    """Adds exact compare statuses, a paginated timeline and an optional sequence of PR detail reads."""
    def __init__(self):
        super().__init__()
        self.compares, self.timeline, self.detail_sequence = {}, [], []

    def request(self, endpoint):
        path = endpoint.split('?')[0]
        if path in self.compares:
            self.calls.append(endpoint)
            value = self.compares[path]
            if isinstance(value, Exception):
                raise value
            return value if isinstance(value, dict) else {'status': value}
        if path == 'repos/acme/photos/issues/30/timeline':
            self.calls.append(endpoint)
            page = int(endpoint.rsplit('page=', 1)[1])
            if callable(self.timeline):
                return self.timeline(page)
            return copy.deepcopy(self.timeline[(page - 1) * 100:page * 100])
        if path == 'repos/acme/photos/pulls/30' and self.detail_sequence:
            self.calls.append(endpoint)
            return copy.deepcopy(self.detail_sequence.pop(0))
        return super().request(endpoint)


class RecognitionTests(unittest.TestCase):
    verify = test_lifecycle.IntegratedLifecycleTests.verify
    publish = test_lifecycle.IntegratedLifecycleTests.publish

    def setUp(self):
        test_lifecycle.IntegratedLifecycleTests.setUp(self)
        commit = self.client.commit
        self.client = UpdateGitHub()
        self.client.commit = commit
        self.creation = self.evidence['git_head']
        self.pr = self.publish()
        self.record = update_for(self.task, self.context, self.evidence)  # from_head == creation head A
        self.context = dict(self.context, schema_version='0.2', draft_update=self.record)
        self.update_head = self.push_update()

    def compare(self, base, head):
        return f'repos/acme/photos/compare/{base}...{head}'

    def push_update(self, path='src/fix.rs'):
        """One fast-forward commit F..E, fresh evidence and review at E, and the live PR head at E."""
        pathlib.Path(self.directory.name, path).write_text('reviewed fix')
        self.git('add', path)
        self.git('commit', '-q', '-m', 'address review')
        head = self.git('rev-parse', 'HEAD')
        self.evidence.update(git_head=head, git_tree=self.git('rev-parse', 'HEAD^{tree}'))
        for validation in self.evidence['validations']:
            validation['git_head'] = head
        self.evidence['independent_review']['git_head'] = head
        for record in [self.client.history[0], self.client.details[30]] + self.client.prs[:1]:
            if 'head' in record and isinstance(record['head'], dict) and 'sha' in record['head']:
                record['head']['sha'] = head
        self.client.compares.update({self.compare(self.creation, self.creation): 'identical',
                                     self.compare(self.creation, head): 'ahead'})
        return head

    def report(self, result):
        return result['draft_update']

    def assert_blocked(self, result, message=None):
        report = self.report(result)
        self.assertEqual(report['status'], 'blocked', report)
        self.assertIsNone(report['candidate_head'])
        self.assertFalse(result['publication']['verified'])
        self.assertFalse(result['completion_ready'])
        self.assertEqual(result['next_action'], 'resolve_blockers')
        if message:
            self.assertIn(message, report['errors'])

    # State table

    def test_fresh_fast_forward_update_is_recognized_and_can_complete(self):
        result = self.verify()
        report = self.report(result)
        self.assertEqual((report['status'], report['candidate_head'], report['live_head'], report['errors']),
                         ('recognized', self.update_head, self.update_head, []), result)
        self.assertTrue(result['publication']['verified'])
        self.assertEqual(result['publication']['own_pr']['head_sha'], self.update_head)
        self.assertEqual(result['next_action'], 'none')
        self.assertFalse(result['draft_create_ready'])
        self.assertEqual(result['stage_blockers']['draft'], [])
        self.assertFalse(result['completion_ready'], 'completion needs a final sign-off for E')
        self.context['final_signoff'] = test_lifecycle.signoff(self.task, self.context, self.evidence)
        self.assertTrue(self.verify()['completion_ready'])

    def test_an_unchanged_draft_is_never_an_update(self):
        # A = F = P with evidence at E: the PR was not pushed, so nothing is recognized (DU-03).
        for record in [self.client.history[0], self.client.details[30]]:
            record['head']['sha'] = self.creation
        result = self.verify()
        self.assertEqual(self.report(result)['status'], 'not_evaluated')
        self.assertEqual(self.report(result)['live_head'], self.creation)
        self.assertFalse(result['publication']['verified'])
        self.assertFalse(result['completion_ready'])

    def test_a_live_head_other_than_the_evidence_head_blocks(self):
        for record in [self.client.history[0], self.client.details[30]]:
            record['head']['sha'] = 'd' * 40
        self.assert_blocked(self.verify(), 'Updated draft head differs from the exact validated evidence HEAD')

    # History

    def test_from_live_must_be_a_strict_fast_forward(self):
        for status in ('identical', 'behind', 'diverged'):
            with self.subTest(status=status):
                self.client.compares[self.compare(self.creation, self.update_head)] = status
                self.assert_blocked(self.verify())

    def test_the_creation_head_must_precede_from_head_and_the_live_head(self):
        later = 'e' * 40
        self.record = update_for(self.task, self.context, self.evidence, from_head=later)
        self.context['draft_update'] = self.record
        self.client.compares.update({self.compare(self.creation, later): 'diverged',
                                     self.compare(later, self.update_head): 'ahead'})
        self.assert_blocked(self.verify(), 'Draft update from_head does not descend from the creation head')
        self.client.compares[self.compare(self.creation, later)] = 'ahead'
        self.client.compares[self.compare(self.creation, self.update_head)] = 'behind'
        self.assert_blocked(self.verify(), 'Updated draft head does not descend from the creation head')

    def test_malformed_or_failed_comparisons_block(self):
        for value in ({'status': 'unknown'}, {}, [], core.ProtocolError('api_error', 'Synthetic compare failure')):
            with self.subTest(value=value):
                self.client.compares[self.compare(self.creation, self.update_head)] = value
                self.assert_blocked(self.verify())

    def test_each_forbidden_timeline_event_blocks(self):
        for event in FORBIDDEN:
            with self.subTest(event=event):
                self.client.timeline = [{'id': 1, 'event': 'labeled'}, {'id': 2, 'event': event}]
                self.assert_blocked(self.verify(), 'Pull request timeline has a forbidden event: ' + event)
        self.client.timeline = [{'id': 1, 'event': 'labeled'}, {'event': 'committed', 'sha': self.update_head},
                                {'id': 3, 'event': 'some_future_event'}]
        self.assertEqual(self.report(self.verify())['status'], 'recognized', 'other event types are allowed')

    def test_incomplete_or_malformed_timelines_block(self):
        cases = {
            'pagination limit': lambda page: [{'id': page * 1000 + n, 'event': 'labeled'} for n in range(100)],
            'repeated identity': [{'id': 1, 'event': 'labeled'}, {'id': 1, 'event': 'labeled'}],
            'item without identity': [{'event': 'labeled'}],
            'committed without a SHA': [{'event': 'committed'}],
            'event not a string': [{'id': 1, 'event': 7}],
            'not an object': ['labeled'],
        }
        for name, timeline in cases.items():
            with self.subTest(case=name):
                self.client.timeline = timeline
                self.assert_blocked(self.verify())

    # Final re-read (DU-07)

    def detail(self, **changes):
        record = copy.deepcopy(self.client.details[30])
        for key, value in changes.items():
            if '.' in key:
                outer, inner = key.split('.')
                record[outer][inner] = value
            else:
                record[key] = value
        return record

    def test_any_change_visible_to_the_final_read_blocks(self):
        cases = {'head move': self.detail(**{'head.sha': 'd' * 40}),
                 'base retarget': self.detail(**{'base.ref': 'release'}),
                 'merged flag': self.detail(merged=True),
                 # A fact no other check covers: still inside the mandate interval, same route and author.
                 'creation time': self.detail(created_at=(NOW - dt.timedelta(minutes=29)).isoformat()),
                 'ready for review': self.detail(draft=False),
                 'malformed': {'id': 'x'}}
        for name, final in cases.items():
            with self.subTest(case=name):
                self.client.detail_sequence = [copy.deepcopy(self.client.details[30]), final]
                self.assert_blocked(self.verify())

    # Evidence and review at E (T(E))

    def test_stale_or_unbound_evidence_at_the_updated_head_blocks(self):
        changes = {
            'evidence for the creation head': lambda e: e.update(git_head=self.creation),
            'review bound to the creation head': lambda e: e['independent_review'].update(git_head=self.creation),
            'review before the validations': lambda e: e['independent_review'].update(
                reviewed_at=(NOW - dt.timedelta(minutes=30)).isoformat()),
        }
        for name, change in changes.items():
            with self.subTest(case=name):
                original = copy.deepcopy(self.evidence)
                change(self.evidence)
                self.assert_blocked(self.verify())
                self.evidence = original

    def test_validations_must_start_inside_the_round(self):
        self.context['draft_update'] = update_for(self.task, self.context, {'git_head': self.creation},
                                                  issued_at=(NOW - dt.timedelta(minutes=15)).isoformat())
        self.assert_blocked(self.verify(), 'Every validation must start after the draft update round was issued')

    def test_a_newer_authenticated_base_blocks_only_the_update_path(self):
        newer = self.git('rev-parse', 'HEAD~1')  # the creation head: authenticated, and descends from source.commit
        self.assertNotEqual(newer, self.task['source']['commit'])
        self.evidence['base_commit'] = newer
        result = self.verify()
        self.assertIn('A draft update requires evidence based on the reviewed source commit exactly',
                      self.report(result)['errors'])
        self.assertEqual(self.report(result)['status'], 'blocked')

    def rebind_all(self):
        digest = core.canonical_hash(self.task)
        self.context = test_lifecycle.host_context(self.task)
        test_lifecycle.own_publication(self.task, self.context, {'git_head': self.creation})
        self.evidence['contract_sha256'] = digest
        self.evidence['independent_review']['contract_sha256'] = digest
        self.context = dict(self.context, schema_version='0.2',
                            draft_update=update_for(self.task, self.context, {'git_head': self.creation}))

    def test_a_merge_commit_in_the_round_blocks_even_with_allowed_paths(self):
        self.git('checkout', '-q', '-b', 'side', self.creation)
        pathlib.Path(self.directory.name, 'src', 'side.rs').write_text('allowed path')
        self.git('add', 'src/side.rs')
        self.git('commit', '-q', '-m', 'side')
        self.git('checkout', '-q', 'agent/bounds')
        self.git('merge', '-q', '--no-ff', '-m', 'merge side', 'side')
        head = self.git('rev-parse', 'HEAD')
        self.evidence.update(git_head=head, git_tree=self.git('rev-parse', 'HEAD^{tree}'))
        for validation in self.evidence['validations']:
            validation['git_head'] = head
        self.evidence['independent_review']['git_head'] = head
        for record in [self.client.history[0], self.client.details[30]]:
            record['head']['sha'] = head
        self.client.compares.update({self.compare(self.creation, head): 'ahead'})
        self.assert_blocked(self.verify(), 'A draft update round must not contain merge commits')

    # Overlaps and authority

    def test_only_the_own_draft_is_exempt_from_overlaps(self):
        self.assertEqual(self.report(self.verify())['status'], 'recognized')
        self.client.prs.append({'id': 3101, 'number': 31, 'title': 'Separate', 'body': 'Fixes #12', 'head': None,
                                'html_url': 'https://github.com/acme/photos/pull/31'})
        self.assert_blocked(self.verify(), 'Unresolved overlapping PRs remain')
        self.client.prs.pop()
        self.task['discovery']['duplicate_prs'] = [{'number': 44, 'url': 'https://github.com/acme/photos/pull/44',
                                                    'reason': 'Explicit reference to this issue',
                                                    'repository': 'acme/photos'}]
        self.rebind_all()
        self.assert_blocked(self.verify(), 'Unresolved overlapping PRs remain')

    def test_mandate_and_record_expiry_after_the_push_do_not_block_recognition(self):
        self.record = update_for(self.task, self.context, {'git_head': self.creation},
                                 issued_at=(NOW - dt.timedelta(hours=1)).isoformat(),
                                 expires_at=(NOW - dt.timedelta(minutes=1)).isoformat())
        for validation in self.evidence['validations']:
            validation['started_at'] = (NOW - dt.timedelta(minutes=50)).isoformat()
        self.context['draft_update'] = self.record
        result = self.verify()
        self.assertEqual(self.report(result)['status'], 'recognized', result)
        self.assertFalse(self.report(result)['current'])

    def test_the_mandate_must_still_be_historically_valid(self):
        self.context['mandate']['event']['binding_sha256'] = '1' * 64
        result = self.verify()
        self.assertEqual(self.report(result)['status'], 'invalid')
        self.assertFalse(result['publication']['verified'])

    def test_without_a_record_an_updated_head_is_never_recognized(self):
        del self.context['draft_update']
        result = self.verify()
        self.assertNotIn('draft_update', result)
        self.assertFalse(result['publication']['verified'])
        self.assertIn('Publication claim requires the exact validated evidence HEAD', result['publication']['errors'])

    # Final sign-off ordering

    def test_final_signoff_must_bind_the_updated_head_and_follow_the_round(self):
        stale = copy.deepcopy(self.evidence)
        stale['git_head'] = self.creation
        self.context['final_signoff'] = test_lifecycle.signoff(self.task, self.context, stale)
        self.assertFalse(self.verify()['completion_ready'], 'a sign-off for A is stale')
        # Every other ordering rule holds at equal times; only "after the round" can fail.
        moment = self.record['issued_at']
        for validation in self.evidence['validations']:
            validation.update(started_at=moment, finished_at=moment)
        self.evidence['independent_review']['reviewed_at'] = moment
        early = test_lifecycle.signoff(self.task, self.context, self.evidence)
        early['issued_at'] = moment
        early['event']['binding_sha256'] = event_binding(early)
        self.context['final_signoff'] = early
        result = self.verify()
        self.assertEqual(self.report(result)['status'], 'recognized', 'the ordering rule alone must fail')
        self.assertFalse(result['completion_ready'])
        self.assertIn('Final signoff must follow the draft update round', result['human_signoff']['errors'])


if __name__ == '__main__':
    unittest.main()
