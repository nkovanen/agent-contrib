"""AI-policy excerpts: located signals from loaded instructions, opt-in, never a verdict."""
import base64
import contextlib
import io
import json
import unittest
from unittest.mock import patch

from agent_contribute import aipolicy, cli, core
from tests.regex_shape import nested_repeats
from tests.test_protocol import FakeGitHub

CONTRIBUTING = ('# Contributing\n\nThanks!\nWe do not accept AI-generated pull requests.\n'
                'Please disclose any use of\x1b[2K ChatGPT or Copilot.\nUnrelated line about email.\n')


class PolicyGitHub(FakeGitHub):
    def __init__(self, text=CONTRIBUTING, **kwargs):
        super().__init__(**kwargs)
        self.text = text

    def request(self, endpoint):
        if '/contents/CONTRIBUTING.md' in endpoint:
            self.calls.append(endpoint)
            return {'encoding': 'base64', 'content': base64.b64encode(self.text.encode()).decode()}
        return super().request(endpoint)


class AIPolicyTests(unittest.TestCase):
    def test_hits_are_located_hashed_and_sanitized(self):
        inspected = core.inspect_issue('acme/photos#12', PolicyGitHub())
        result = aipolicy.ai_policy_excerpts(inspected)
        self.assertEqual(result['ai_policy_review'], 'required')
        self.assertEqual(result['coverage'], 'complete')
        hits = [(e['path'], e['line'], e['patterns']) for e in result['excerpts']]
        self.assertEqual(hits, [('CONTRIBUTING.md', 4, ['AI-generated']),
                                ('CONTRIBUTING.md', 5, ['Copilot', 'ChatGPT'])])
        contributing = next(i for i in inspected['instructions'] if i['path'] == 'CONTRIBUTING.md')
        self.assertEqual(result['excerpts'][0]['instruction_sha256'], contributing['sha256'])
        self.assertNotIn('\x1b', json.dumps(result))
        self.assertIn('not a verdict', result['notice'])

    def test_zero_hits_are_not_permission_and_incomplete_reads_are_flagged(self):
        result = aipolicy.ai_policy_excerpts(core.inspect_issue('acme/photos#12', PolicyGitHub('No policy here.')))
        self.assertEqual((result['excerpts'], result['coverage']), ([], 'complete'))
        self.assertIn('Zero hits do not mean AI contributions are permitted', result['notice'])
        client = PolicyGitHub()
        client.failed.add('/contents/README.md')
        result = aipolicy.ai_policy_excerpts(core.inspect_issue('acme/photos#12', client))
        self.assertEqual(result['coverage'], 'incomplete')

    def test_bounded_and_linear(self):
        # Deterministic, not wall-clock: no nested quantifiers (a nesting check, not a linearity proof), and each
        # search sees at most LINE_LIMIT characters.
        for _, pattern in aipolicy.COMPILED:
            self.assertFalse(nested_repeats(pattern), pattern.pattern)
        longest = []

        class Recording:
            def __init__(self, pattern):
                self.pattern = pattern

            def search(self, line):
                longest.append(len(line))
                return self.pattern.search(line)

        text = ('LLM ' * 1000 + '\n') * 500 + 'a' * 150000
        with patch.object(aipolicy, 'COMPILED', [(label, Recording(p)) for label, p in aipolicy.COMPILED]):
            result = aipolicy.ai_policy_excerpts({'complete': True, 'instructions': [
                {'path': 'x', 'sha256': '0' * 64, 'untrusted_text': text}]})
        self.assertEqual(max(longest), aipolicy.LINE_LIMIT)
        self.assertEqual(len(result['excerpts']), aipolicy.MAX_EXCERPTS)
        self.assertTrue(result['excerpts_capped'])
        self.assertEqual(result['coverage'], 'incomplete')
        self.assertTrue(all(len(e['untrusted_excerpt']) <= 300 for e in result['excerpts']))

    def test_long_line_past_scan_bound_makes_coverage_incomplete(self):
        text = 'x' * 2500 + ' No AI contributions are accepted.'
        result = aipolicy.ai_policy_excerpts({'complete': True, 'instructions': [
            {'path': 'CONTRIBUTING.md', 'sha256': '0' * 64, 'untrusted_text': text}]})
        self.assertEqual(result['excerpts'], [])
        self.assertEqual(result['lines_partially_scanned'], 1)
        self.assertEqual(result['coverage'], 'incomplete')
        self.assertFalse(result['excerpts_capped'])
        long_hit = aipolicy.ai_policy_excerpts({'complete': True, 'instructions': [
            {'path': 'C', 'sha256': '0' * 64, 'untrusted_text': 'No AI contributions. ' + 'y' * 400}]})
        self.assertEqual(long_hit['coverage'], 'complete')
        self.assertTrue(long_hit['excerpts'][0]['excerpt_truncated'])

    def test_cli_opt_in_never_changes_approval(self):
        def run(*argv):
            output = io.StringIO()
            with patch.object(core, 'GitHub', return_value=PolicyGitHub()), contextlib.redirect_stdout(output):
                code = cli.main(list(argv))
            return code, json.loads(output.getvalue())
        code, plain = run('inspect', 'acme/photos#12')
        self.assertNotIn('ai_policy', plain)
        code, result = run('inspect', 'acme/photos#12', '--ai-policy')
        self.assertEqual(code, 0)
        self.assertEqual(len(result['ai_policy']['excerpts']), 2)
        self.assertEqual(result['approval'], plain['approval'])
        self.assertEqual({k: v for k, v in result.items() if k not in ('ai_policy', 'source', 'resolution_provenance')},
                         {k: v for k, v in plain.items() if k not in ('source', 'resolution_provenance')})


if __name__ == '__main__':
    unittest.main()
