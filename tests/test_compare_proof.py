"""A GitHub comparison counts as a history proof only when its commits and counters agree with its status (FR1-01)."""
import tempfile
import unittest

from agent_contribute import core
from tests import test_lifecycle
from tests.test_protocol import comparison, evidence_checkout

BASE, HEAD, OTHER = 'a' * 40, 'b' * 40, 'f' * 40
INCONSISTENT = 'Inconsistent or partial GitHub commit comparison'


class Responding:
    def __init__(self, value):
        self.value = value

    def request(self, endpoint):
        return self.value


class RelationTests(unittest.TestCase):
    def test_consistent_responses_return_their_status(self):
        for status in ('identical', 'ahead', 'behind', 'diverged'):
            with self.subTest(status=status):
                head = BASE if status == 'identical' else HEAD
                self.assertEqual(core.compare_relation(Responding(comparison(BASE, head, status)), 'o/r', BASE, head),
                                 status)

    def test_partial_or_contradictory_responses_fail_closed(self):
        good = comparison(BASE, HEAD, 'behind')
        cases = {
            'status only': {'status': 'behind'},
            'unknown status': dict(good, status='weird'),
            'missing counters': {k: v for k, v in good.items() if k != 'behind_by'},
            'negative counter': dict(good, behind_by=-1),
            'boolean counter': dict(good, ahead_by=False),
            'wrong base echo': dict(good, base_commit={'sha': OTHER}),
            'wrong merge base': dict(good, merge_base_commit={'sha': OTHER}),
            'identical with counters': dict(comparison(BASE, BASE, 'identical'), ahead_by=4),
            'behind but ahead_by': dict(good, ahead_by=1, total_commits=1),
            'behind with zero behind_by': dict(good, behind_by=0),
            'total_commits disagrees': dict(good, total_commits=3),
            'malformed merge base': dict(good, merge_base_commit={'sha': 'x'}),
            'not an object': ['behind'],
            'identical for different commits': comparison(BASE, HEAD, 'identical'),
            'diverged at an endpoint': dict(comparison(BASE, HEAD, 'diverged'), merge_base_commit={'sha': BASE}),
        }
        for name, value in cases.items():
            with self.subTest(case=name), self.assertRaises(core.ProtocolError) as caught:
                core.compare_relation(Responding(value), 'o/r', BASE, HEAD)
            self.assertIn(caught.exception.code, ('api_shape',))


class RawCompare:
    """Wraps a fake client: every comparison returns the given raw response instead of a consistent one."""
    def __init__(self, client, value):
        self.client, self.value = client, value

    def __getattr__(self, name):
        return getattr(self.client, name)

    def request(self, endpoint):
        return dict(self.value) if '/compare/' in endpoint else self.client.request(endpoint)


ATTACKS = {'status only': {'status': 'behind'},
           'contradictory identical': {'status': 'identical', 'ahead_by': 4, 'behind_by': 0, 'total_commits': 4,
                                       'base_commit': {'sha': OTHER}, 'merge_base_commit': {'sha': 'e' * 40}}}


class LegacyEvidenceTests(unittest.TestCase):
    def test_partial_comparison_cannot_authenticate_the_evidence_base(self):
        for name, value in ATTACKS.items():
            with self.subTest(attack=name), tempfile.TemporaryDirectory() as root:
                task, client, evidence, _ = evidence_checkout(root)
                self.assertTrue(core.verify(task, evidence, root, client)['evidence_valid'])
                result = core.verify(task, evidence, root, RawCompare(client, value))
                self.assertFalse(result['upstream_submission_ready'])
                self.assertTrue(any(error.startswith('Could not authenticate evidence base against source default-branch '
                                                     'history') and error.endswith(INCONSISTENT)
                                    for error in result['evidence_errors']), result['evidence_errors'])


class CandidateTests(unittest.TestCase):
    setUp = test_lifecycle.IntegratedLifecycleTests.setUp
    verify = test_lifecycle.IntegratedLifecycleTests.verify
    publish = test_lifecycle.IntegratedLifecycleTests.publish

    def test_partial_comparisons_cannot_pass_any_gate(self):
        for name, value in ATTACKS.items():
            with self.subTest(attack=name):
                honest = self.client
                self.client = RawCompare(honest, value)
                try:
                    result = self.verify()
                finally:
                    self.client = honest
                self.assertFalse(result['implementation_ready'])
                self.assertFalse(result['draft_create_ready'])
                self.assertTrue(any(INCONSISTENT in error for error in result['errors']), result['errors'])


if __name__ == '__main__':
    unittest.main()
