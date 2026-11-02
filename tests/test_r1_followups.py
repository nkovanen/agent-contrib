"""Round 3a reviewer follow-ups: bounded parsing, report identity and single name parsing."""
import base64
import contextlib
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


if __name__ == '__main__':
    unittest.main()
