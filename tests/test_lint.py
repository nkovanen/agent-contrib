"""Offline contract lint (F17): schema and reviewed-contract checks with no GitHub or Git reads."""
import contextlib
import io
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from agent_contribute import cli, core
from tests.test_authorization import candidate_task
from tests.test_protocol import FakeGitHub, ready_contract


class LintTests(unittest.TestCase):
    def run_lint(self, task, *options, raw=None):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp, 'task.json')
            path.write_text(raw if raw is not None else json.dumps(task), encoding='utf-8')
            output = io.StringIO()
            with patch.object(core, 'GitHub', side_effect=AssertionError('lint must not read GitHub')), \
                    patch.object(core.subprocess, 'run', side_effect=AssertionError('lint runs nothing')), \
                    contextlib.redirect_stdout(output):
                code = cli.main([*options, 'lint', str(path)])
        return code, output.getvalue()

    def test_reviewed_contracts_pass_offline_for_both_schemas(self):
        for task in (ready_contract()[0], candidate_task()[0]):
            with self.subTest(version=task['schema_version']):
                code, output = self.run_lint(task)
                result = json.loads(output)
                self.assertEqual(code, 0)
                self.assertEqual(result, {'schema_version': task['schema_version'], 'schema_valid': True, 'schema_errors': [],
                                          'review_errors': [], 'reviewed': True,
                                          'contract_sha256': core.canonical_hash(task),
                                          'network': 'No GitHub or Git reads. Live source, approval, overlap, '
                                                     'authorization and evidence checks still need verify.'})

    def test_draft_contract_is_schema_valid_but_not_reviewed(self):
        draft = core.prepare(core.inspect_issue('acme/photos#12', FakeGitHub()))
        code, output = self.run_lint(draft)
        result = json.loads(output)
        self.assertEqual((code, result['schema_valid'], result['reviewed']), (1, True, False))
        self.assertIn('Contract is draft or has unanswered questions', result['review_errors'])
        self.assertIn('Reviewed contract requires allowed paths and explicit prohibited paths', result['review_errors'])
        task = ready_contract()[0]
        task['prerequisites'] = [{'id': 'P1', 'description': 'One', 'status': 'pending', 'evidence': ''}]
        self.assertEqual(json.loads(self.run_lint(task)[1])['review_errors'],
                         ['Prerequisites are not satisfied with evidence: P1 (pending)'])

    def test_review_rules_follow_the_contract_schema_version(self):
        # The two schema-specific rules: 0.2 rejects any backslash in scope; 0.1 blocks prepared duplicates.
        task = candidate_task()[0]
        task['scope']['allowed_paths'] = ['src\\x/**']
        self.assertEqual(json.loads(self.run_lint(task)[1])['review_errors'],
                         ['Scope patterns must be repository-relative without parent traversal'])
        task = ready_contract()[0]
        task['discovery']['duplicate_prs'] = [{'number': 30, 'url': 'u', 'reason': 'r'}]
        self.assertEqual(json.loads(self.run_lint(task)[1])['review_errors'],
                         ['Prepared discovery is incomplete or has unresolved duplicates'])

    def test_schema_invalid_or_unknown_versions_fail_closed(self):
        for task in ({'schema_version': '0.2'}, dict(ready_contract()[0], schema_version='999'), [], {'x': 1}):
            with self.subTest(task=str(task)[:40]):
                code, output = self.run_lint(task)
                result = json.loads(output)
                self.assertEqual((code, result['schema_valid'], result['reviewed']), (1, False, False))
                self.assertTrue(result['schema_errors'])
                self.assertEqual((result['review_errors'], result['contract_sha256']), ([], None))
        self.assertIn('$.status: missing', json.loads(self.run_lint({'schema_version': '0.2'})[1])['schema_errors'])
        self.assertIsNone(json.loads(self.run_lint([])[1])['schema_version'])

    def test_bad_input_usage_and_text_output(self):
        code, output = self.run_lint(None, raw='{"status":"draft","status":"reviewed"}')
        self.assertEqual((code, json.loads(output)['error']['code']), (1, 'invalid_json'))
        code, output = self.run_lint(ready_contract()[0], '--report-budget')
        self.assertEqual((code, json.loads(output)['error']['code']), (2, 'usage'))
        code, output = self.run_lint({'schema_version': '0.2'}, '--format', 'text')
        self.assertEqual(code, 1)
        self.assertIn('schema_valid: False\n', output)
        self.assertIn('Schema errors (16):\n  - $.status: missing\n', output)


if __name__ == '__main__':
    unittest.main()
