"""CI observations: exact head, strict shapes, opt-in, never a readiness input."""
import contextlib
import copy
import io
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from agent_contribute import ci, cli, core
from tests.test_feedback import run
from tests.test_protocol import ready_contract

HEAD = 'a' * 40


class CIGitHub:
    def __init__(self, base):
        self.base, self.calls, self.failed = base, [], set()
        self.runs = [run(1, 'tests'), run(2, 'lint', status='queued', conclusion=None), run(3, 'old', head='b' * 40)]
        self.status = {'sha': HEAD, 'state': 'pending', 'total_count': 1,
                       'statuses': [{'id': 9, 'context': 'ci/legacy', 'state': 'pending', 'target_url': None}]}

    def request(self, endpoint):
        if '/check-runs' in endpoint or endpoint.split('?')[0].endswith('/status'):
            self.calls.append(endpoint)
            if any(key in endpoint for key in self.failed):
                raise core.ProtocolError('api_error', 'GitHub read failed')
            if '/check-runs' in endpoint:
                return {'total_count': len(self.runs), 'check_runs': copy.deepcopy(self.runs)}
            return copy.deepcopy(self.status)
        return self.base.request(endpoint)


class CIObservationTests(unittest.TestCase):
    def test_exact_head_runs_and_combined_status(self):
        task, client = ready_contract()
        client = CIGitHub(client)
        result = ci.observe(task, {'git_head': HEAD}, client)
        self.assertTrue(result['complete'], result['errors'])
        self.assertEqual([r['name'] for r in result['check_runs']], ['tests', 'lint'])
        self.assertEqual(result['other_head_runs'], 1)
        self.assertEqual(result['combined_status']['state'], 'pending')
        self.assertIn('repos/acme/photos/commits/' + HEAD + '/check-runs?per_page=100&page=1', client.calls)
        self.assertIn('never changes readiness', result['notice'])

    def test_malformed_failed_or_missing_head_is_incomplete(self):
        task, base = ready_contract()
        for change in [lambda c: c.failed.add('/status'), lambda c: c.failed.add('/check-runs'),
                       lambda c: c.status.update(sha='b' * 40), lambda c: c.status.update(state='green'),
                       lambda c: c.status['statuses'][0].update(id=-1), lambda c: c.runs[0].update(conclusion='ok')]:
            client = CIGitHub(base)
            change(client)
            result = ci.observe(task, {'git_head': HEAD}, client)
            self.assertFalse(result['complete'])
            self.assertTrue(result['errors'])
        for evidence in [None, {}, {'git_head': 'HEAD'}, ['x']]:
            self.assertFalse(ci.observe(task, evidence, CIGitHub(base))['complete'])

    def test_cli_opt_in_does_not_change_exit_or_gates(self):
        task, base = ready_contract()
        with tempfile.TemporaryDirectory() as tmp:
            contract = pathlib.Path(tmp, 'task.json')
            contract.write_text(json.dumps(task))
            evidence = pathlib.Path(tmp, 'e.json')
            evidence.write_text(json.dumps({'git_head': HEAD}))
            outputs = {}
            for flag in ([], ['--observe-ci']):
                output = io.StringIO()
                client = CIGitHub(base)
                with patch.object(core, 'GitHub', return_value=client), contextlib.redirect_stdout(output):
                    code = cli.main(['verify', str(contract), '--evidence', str(evidence), *flag])
                outputs[bool(flag)] = (code, json.loads(output.getvalue()))
            (plain_code, plain), (ci_code, observed) = outputs[False], outputs[True]
            self.assertEqual(plain_code, ci_code)
            self.assertNotIn('ci_observation', plain)
            self.assertTrue(observed['ci_observation']['complete'])
            for key in ('execution_ready', 'evidence_valid', 'upstream_submission_ready', 'errors', 'evidence_errors'):
                self.assertEqual(plain[key], observed[key])


if __name__ == '__main__':
    unittest.main()
