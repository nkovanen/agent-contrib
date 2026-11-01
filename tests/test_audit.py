"""Maintainer audit: same reads as discover, explicit unknowns, suggestions only."""
import contextlib
import io
import json
import unittest
from unittest.mock import patch

from agent_contribute import audit, cli, core
from tests.test_protocol import FakeGitHub

POLICY = {'schema_version': '0.1', 'agent_approved_labels': ['agent-ok'], 'label_authority': 'repository-label-permission'}


class AuditTests(unittest.TestCase):
    def test_no_policy_reports_candidate_state_and_suggests_template(self):
        client = FakeGitHub()
        report = audit.audit('acme/photos', client, print_policy=True)
        self.assertTrue(report['complete'])
        self.assertEqual(report['policy']['state'], 'missing')
        self.assertIsNone(report['policy']['valid'])
        self.assertEqual(report['issues']['approval'], {'candidate': 1})
        self.assertEqual(report['policy_template'], dict(POLICY, agent_approved_labels=['agent-approved']))
        templated = audit.audit('acme/photos', FakeGitHub(report['policy_template'], ['agent-approved']))
        self.assertTrue(templated['policy']['valid'], 'the printed template must itself be a valid policy')
        self.assertTrue(any('.agent-contrib.json' in s for s in report['suggestions']))
        self.assertTrue(any('pull request template' in s for s in report['suggestions']))
        self.assertEqual(report['instructions']['expected'], {'contributing': True, 'agent instructions': True,
                                                             'pull request template': False,
                                                             'architecture/spec index': True})
        discover_client = FakeGitHub()
        core.discover('acme/photos', discover_client)
        self.assertEqual(client.calls, discover_client.calls, 'audit must not add reads')
        self.assertTrue(all(call.startswith('repos/') for call in client.calls))

    def test_valid_policy_with_missing_label(self):
        report = audit.audit('acme/photos', FakeGitHub(POLICY, []))
        self.assertTrue(report['policy']['valid'])
        self.assertEqual(report['policy']['missing_labels'], ['agent-ok'])
        self.assertIn('Create the approval labels the policy names: agent-ok', report['suggestions'])

    def test_malformed_and_generic_policies_are_invalid_with_reason(self):
        for policy in [{'schema_version': '0.1', 'agent_approved_labels': ['bug'],
                        'label_authority': 'repository-label-permission'},
                       {'agent_approved_labels': 'agent-ok'}, ['not', 'an', 'object']]:
            with self.subTest(policy=policy):
                report = audit.audit('acme/photos', FakeGitHub(policy, ['agent-ok', 'bug']))
                self.assertFalse(report['policy']['valid'])
                self.assertTrue(report['policy']['reason'])
                self.assertFalse(report['complete'])
                if policy and isinstance(policy, dict) and isinstance(policy['agent_approved_labels'], list):
                    self.assertEqual(report['policy']['generic_approval_labels'], ['bug'])

    def test_truncated_tree_and_failed_reads_stay_unknown(self):
        client = FakeGitHub(POLICY, ['agent-ok'])
        original = client.request
        client.request = lambda e: dict(original(e), truncated=True) if '/git/trees/' in e else original(e)
        report = audit.audit('acme/photos', client)
        self.assertFalse(report['complete'])
        self.assertFalse(report['instructions']['tree_complete'])
        self.assertEqual(report['policy']['state'], 'unknown')
        self.assertIsNone(report['policy']['valid'])
        failed = FakeGitHub()
        failed.failed.add('repos/acme/photos')
        report = audit.audit('acme/photos', failed)
        self.assertFalse(report['complete'])
        self.assertNotIn('policy', report)

    def test_cli_exit_codes_and_untrusted_paths(self):
        for client, expected in [(FakeGitHub(), 0), (FakeGitHub(POLICY, []), 0)]:
            output = io.StringIO()
            with patch.object(core, 'GitHub', return_value=client), contextlib.redirect_stdout(output):
                self.assertEqual(cli.main(['audit', 'acme/photos', '--print-policy']), expected)
            self.assertIn('policy_template', json.loads(output.getvalue()))
        client = FakeGitHub()
        client.failed.add('/labels')
        output = io.StringIO()
        with patch.object(core, 'GitHub', return_value=client), contextlib.redirect_stdout(output):
            self.assertEqual(cli.main(['audit', 'acme/photos']), 1)


if __name__ == '__main__':
    unittest.main()
