"""Cheap documentation checks: the documented surface matches the installed parser and links resolve."""
import argparse
import pathlib
import re
import unittest

from tests.test_cli_help import built_parser

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = [ROOT / 'README.md', ROOT / 'CHANGELOG.md', ROOT / 'CONTRIBUTING.md', ROOT / 'SECURITY.md',
        *sorted((ROOT / 'docs').glob('*.md'))]


def commands():
    names = []
    for action in built_parser()._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in action.choices.items():
                nested = [a for a in sub._actions if isinstance(a, argparse._SubParsersAction)]
                names += [name + ' ' + child for a in nested for child in a.choices] if nested else [name]
    return names


class DocsConsistencyTests(unittest.TestCase):
    def test_readme_and_command_reference_name_every_command(self):
        readme = (ROOT / 'README.md').read_text('utf-8')
        reference = (ROOT / 'docs' / 'cli.md').read_text('utf-8')
        for name in commands():
            with self.subTest(command=name):
                self.assertIn('`' + name, readme)
                self.assertIn('agent-contrib ' + name, reference)

    def test_no_document_installs_a_nonexistent_release_tag(self):
        for path in DOCS:
            with self.subTest(path=path.name):
                self.assertNotRegex(path.read_text('utf-8'), r'@v0\.3\.0')
        self.assertIn('agent-contrib.git@v0.2.0', (ROOT / 'README.md').read_text('utf-8'))

    def test_relative_links_resolve(self):
        for path in DOCS:
            for target in re.findall(r'\]\(([^)#\s]+)(?:#[^)]*)?\)', path.read_text('utf-8')):
                if '://' in target or target.startswith('mailto:'):
                    continue
                with self.subTest(path=path.name, target=target):
                    self.assertTrue((path.parent / target).exists())

    def test_product_map_covers_every_tracked_issue(self):
        text = (ROOT / 'docs' / 'product-map.md').read_text('utf-8')
        for number in [n for n in range(1, 29) if n != 2]:  # #2 is a pull request, not an issue
            with self.subTest(issue=number):
                self.assertRegex(text, rf'issues/{number}\)')


if __name__ == '__main__':
    unittest.main()
