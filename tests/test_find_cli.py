"""Public finder output, usage ordering and budget instrumentation composition."""
import contextlib
import io
import json
import unittest
from unittest.mock import patch

from agent_contribute import cli, core, outputs
from tests import test_find as fixtures
from tests.test_find import Fake, hit, page


def invoke(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out): code = cli.main(list(args))
    return code, out.getvalue()


class FindCliTests(unittest.TestCase):
    def test_invalid_owner_precedes_budget_and_cache_reads(self):
        with patch.object(core, 'GitHub', side_effect=AssertionError('no reads')):
            code, out = invoke('--report-budget', '--cache', 'find', '--owner', 'a user:bad')
        self.assertEqual(code, 2); self.assertEqual(json.loads(out)['error']['code'], 'usage')

    def test_schema_exits_and_closed_shapes(self):
        for search, expected in [(page([]), 0), (dict(page(), total_count=20), 1),
                                 (dict(page(), incomplete_results=True), 1), ({}, 1), (page(), 0)]:
            with patch.object(core, 'GitHub', return_value=Fake(search)):
                code, out = invoke('find')
            self.assertEqual(code, expected)
            result = json.loads(out)
            self.assertEqual(result['format'], 'find-jars-report/1')
            schema = outputs.output_schema('find')
            self.assertEqual(core.schema_errors(result, schema), [])
            result['approval'] = True
            self.assertTrue(core.schema_errors(result, schema))
        with patch.object(core, 'GitHub', return_value=Fake(page([hit()]*10))):
            code, out = invoke('find')
        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads(out)['observations']), 1)
        with patch.object(core, 'GitHub', return_value=Fake(dict(page(), total_count=20, items=[hit()]*10))):
            code, out = invoke('find')
        self.assertEqual(code, 0); self.assertTrue(json.loads(out)['search']['truncated'])

    def test_all_dispositions_validate_with_unchanged_jar_shape(self):
        from tests.test_tipjar import responses
        fixtures = [Fake(data=responses(b'{"schema_version":"0.1","status":"closed"}')),
                    Fake(data=responses(entries=[])), Fake(data=responses(b'bad'))]
        h = hit(); h['repository']['private'] = True; fixtures.append(Fake(page([h])))
        fixtures.append(Fake())
        seen = set()
        for fake in fixtures:
            with patch.object(core, 'GitHub', return_value=fake): code, out = invoke('find')
            result = json.loads(out)
            self.assertEqual(core.schema_errors(result, outputs.output_schema('find')), [])
            for obs in result['observations']:
                seen.add(obs['disposition'])
                if obs['jar'] is not None:
                    self.assertEqual(core.schema_errors(obs['jar'], outputs.output_schema('jar')), [])
        self.assertEqual(seen, {'closed', 'undeclared', 'unknown', 'excluded', 'welcome'})

    def test_text_empty_coverage_and_terminal_neutralization(self):
        with patch.object(core, 'GitHub', return_value=Fake(page([]))): code, out = invoke('--format', 'text', 'find')
        self.assertEqual(code, 0)
        self.assertIn('No verified welcoming repositories in this batch', out)
        self.assertIn('not exhaustive', out)
        from tests.test_tipjar import responses
        data = responses(json.dumps({'schema_version': '0.1', 'status': 'welcome', 'wanted': ['\u202euntrusted']}).encode())
        with patch.object(core, 'GitHub', return_value=Fake(data=data)):
            code, out = invoke('--format', 'text', 'find')
        self.assertEqual(code, 0); self.assertNotIn('\u202e', out)
        self.assertIn('https://github.com/acme/project', out); self.assertIn('untrusted', out)


class BudgetCompositionTests(unittest.TestCase):
    batch = staticmethod(fixtures.TransportTests.batch)

    def run_cli_transport(self, retry=False):
        search, data = self.batch(); calls = []; rate_calls = 0
        def run(argv, **kw):
            nonlocal rate_calls
            endpoint = argv[-1]; calls.append(endpoint)
            self.assertEqual(argv[:6], ['gh', 'api', '--hostname', 'github.com', '--method', 'GET'])
            self.assertEqual(kw['timeout'], 30)
            if endpoint == 'rate_limit':
                rate_calls += 1
                if retry and rate_calls in (1, 2, 4, 5):
                    kw['stderr'].write(b'HTTP 503'); return type('Result', (), {'returncode': 1})()
                value = {'resources': {'core': {'limit': 5000, 'remaining': 4000, 'used': 1000, 'reset': 50}}}
            else: value = search if endpoint.startswith('search/code?') else data[endpoint]
            kw['stdout'].write(json.dumps(value).encode()); return type('Result', (), {'returncode': 0})()
        with patch('subprocess.run', side_effect=run), patch('time.sleep'):
            code, out = invoke('--cache', '--report-budget', '--min-remaining', '1', 'find')
        return code, json.loads(out), calls

    def test_maximum_work_with_snapshots_is_53_or_57_invocations(self):
        for retry, expected in [(False, 53), (True, 57)]:
            code, result, calls = self.run_cli_transport(retry)
            self.assertEqual(code, 0); self.assertEqual(len(calls), expected)
            self.assertEqual(result['requests'], {'search': 1, 'core': 50})
            self.assertIn('Core REST', result['api_budget']['note'])
            self.assertEqual(core.schema_errors(result, outputs.output_schema('find')), [])
