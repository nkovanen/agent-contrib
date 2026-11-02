"""Round 3a reviewer follow-ups: bounded parsing, report identity and single name parsing."""
import base64
import contextlib
import copy
import io
import json
import unittest
from unittest.mock import patch

from agent_contribute import cli, core
from tests.test_protocol import FakeGitHub


class NonfiniteJSONTests(unittest.TestCase):
    def test_exponent_overflow_is_rejected_like_literal_nonfinite_values(self):
        for text in ('1e999', '-1e999', '[1E400]', '{"a": -9.9e9999}', 'NaN', 'Infinity', '-Infinity'):
            with self.subTest(text=text):
                with self.assertRaises(core.ProtocolError) as caught:
                    core.strict_json(text)
                self.assertEqual(caught.exception.code, 'invalid_json')

    def test_finite_numbers_are_unchanged(self):
        self.assertEqual(core.strict_json('[1e308, -2.5, 0.0, 12345678901234567890, 1E-400]'),
                         [1e308, -2.5, 0.0, 12345678901234567890, 0.0])

    def test_overflowing_policy_gives_structured_unknown_incomplete_inspect(self):
        policy = ('{"schema_version":"0.1","agent_approved_labels":["agent-ok"],'
                  '"label_authority":"repository-label-permission","extra":1e999}')

        class OverflowPolicyGitHub(FakeGitHub):
            def request(self, endpoint):
                if '/contents/.agent-contrib.json?' in endpoint:
                    self.calls.append(endpoint)
                    return {'encoding': 'base64', 'content': base64.b64encode(policy.encode()).decode()}
                return super().request(endpoint)

        client = OverflowPolicyGitHub({'schema_version': '0.1', 'agent_approved_labels': ['agent-ok'],
                                       'label_authority': 'repository-label-permission'}, ['agent-ok'])
        output = io.StringIO()
        with patch.object(core, 'GitHub', return_value=client), contextlib.redirect_stdout(output):
            code = cli.main(['inspect', 'acme/photos#12'])
        result = json.loads(output.getvalue())
        self.assertEqual(code, 1)
        self.assertFalse(result['complete'])
        self.assertEqual(result['approval']['status'], 'unknown')
        self.assertIn('Could not read repository instruction: .agent-contrib.json', result['errors'])



class OwnershipIdentityTests(unittest.TestCase):
    def collision(self, second_id_offset):
        from agent_contribute import ownership
        from tests.test_ownership import NOW, TimelineGitHub, xref
        client = TimelineGitHub()
        first = xref('other/fork', 4)
        second = copy.deepcopy(first)
        second['created_at'] = '2030-01-01T00:05:00Z'  # a distinct event, not a repeated page item
        second['source']['issue']['repository']['id'] += second_id_offset
        client.timeline = [first, second]
        client.comments = []
        client.pulls['other/fork/4']['base']['repo']['id'] += second_id_offset
        return ownership.ownership_signals('acme/photos', 12, client, NOW)

    def test_conflicting_repository_ids_for_one_pr_leave_the_report_incomplete(self):
        result = self.collision(1000)
        self.assertFalse(result['complete'])
        self.assertTrue(any('other/fork#4' in error and 'repository ID' in error for error in result['errors']),
                        result['errors'])

    def test_identical_duplicate_references_still_deduplicate(self):
        result = self.collision(0)
        self.assertTrue(result['complete'], result['errors'])
        self.assertEqual(len(result['cross_referenced_prs']), 1)

if __name__ == '__main__':
    unittest.main()
