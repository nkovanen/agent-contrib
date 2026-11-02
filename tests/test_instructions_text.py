"""`--format text instructions` prints the workflow Markdown; JSON stays the default."""
import contextlib
import importlib.resources
import io
import json
import unittest

from agent_contribute import cli, __version__


def resource(path):
    return importlib.resources.files('agent_contribute').joinpath(path).read_text('utf-8')


def invoke(*args):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = cli.main(list(args))
    return code, output.getvalue()


class TextInstructionsTests(unittest.TestCase):
    def test_text_format_prints_the_workflow_markdown_unchanged(self):
        code, output = invoke('--format', 'text', 'instructions')
        self.assertEqual(code, 0)
        markdown = resource('instructions.md')
        header, body = output.split('\n', 1)
        self.assertIn(__version__, header)
        self.assertIn('0.1, 0.2', header)
        self.assertEqual(body, '\n' + markdown)
        self.assertNotIn('summary; JSON output is canonical', output)

    def test_json_default_is_unchanged(self):
        code, output = invoke('instructions')
        self.assertEqual(code, 0)
        result = json.loads(output)
        self.assertEqual(result['workflow_markdown'], resource('instructions.md'))
        self.assertEqual(set(result), {'cli_version', 'supported_schema_versions', 'supported_host_context_versions',
                                       'host_authorization', 'workflow_markdown', 'resources', 'automatic_updates',
                                       'output_schema_version'})

if __name__ == '__main__':
    unittest.main()
