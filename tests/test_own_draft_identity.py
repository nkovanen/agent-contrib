"""The own-draft exemption needs one consistent numeric PR identity across the open scan and history (FR1-02)."""
import copy
import unittest

from tests import test_lifecycle

CONFLICT = 'Open-PR scan and exact-head history disagree on the draft pull request identity; repeat the complete read'


class OwnDraftIdentityTests(unittest.TestCase):
    setUp = test_lifecycle.IntegratedLifecycleTests.setUp
    verify = test_lifecycle.IntegratedLifecycleTests.verify
    publish = test_lifecycle.IntegratedLifecycleTests.publish

    def complete(self):
        self.publish()
        self.context['final_signoff'] = test_lifecycle.signoff(self.task, self.context, self.evidence)

    def test_consistent_identity_completes(self):
        self.complete()
        self.assertTrue(self.verify()['completion_ready'])

    def test_a_conflicting_or_missing_scan_identity_is_not_exempted(self):
        def boolean_one(pr):
            # PR ID 1 everywhere else; the scan's JSON true must not pass as 1.
            for record in (self.client.history[0], self.client.details[30]):
                record['id'] = 1
            self.context['publication']['pr_id'] = 1
            pr['id'] = True

        for name, change in {'other numeric id': lambda pr: pr.update(id=98765),
                             'id missing': lambda pr: pr.pop('id'),
                             'boolean id': boolean_one}.items():
            with self.subTest(case=name):
                self.complete()
                change(self.client.prs[0])
                result = self.verify()
                self.assertFalse(result['publication']['verified'])
                self.assertFalse(result['completion_ready'])
                self.assertIn(CONFLICT, result['stage_blockers']['completion'])
                if name != 'boolean id':  # a boolean ID already makes the open scan incomplete
                    self.assertTrue(result['blocking_duplicates'], 'the unreconciled scan entry still blocks')

    def test_a_repeated_scan_number_is_a_conflict_in_either_order(self):
        # FR1-05: two open-scan entries for #30 must not resolve to whichever came last.
        def other(pr):
            return dict(copy.deepcopy(pr), id=98765)

        def missing(pr):
            entry = copy.deepcopy(pr)
            entry.pop('id')
            return entry
        for name, extra in {'other id': other, 'missing id': missing}.items():
            for order in ('extra first', 'extra last'):
                with self.subTest(case=name, order=order):
                    self.complete()
                    own = self.client.prs[0]
                    self.client.prs = [extra(own), own] if order == 'extra first' else [own, extra(own)]
                    result = self.verify()
                    self.assertFalse(result['publication']['verified'])
                    self.assertFalse(result['completion_ready'])
                    self.assertIn(CONFLICT, result['stage_blockers']['completion'])
                    self.assertEqual(len(result['blocking_duplicates']), 2, result['blocking_duplicates'])


if __name__ == '__main__':
    unittest.main()
