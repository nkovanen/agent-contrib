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

    def test_candidate_install_selects_the_candidate_before_the_skill_is_exported(self):
        path_entry = 'export PATH="$HOME/.local/share/agent-contrib-candidate/bin:$PATH"'
        for name in ('README.md', 'docs/installation.md'):
            with self.subTest(doc=name):
                text = (ROOT / name).read_text('utf-8')
                self.assertIn(path_entry, text)
                after = text[text.index(path_entry):]
                self.assertIn('agent-contrib --version', after)
                self.assertIn('PUSHED_FULL_COMMIT_SHA', text)
                self.assertNotIn('/tmp/agent-contrib-candidate', text)
        readme = (ROOT / 'README.md').read_text('utf-8')
        self.assertLess(readme.index(path_entry), readme.index('agent-contrib skill --output'))

    def test_ranking_and_compatibility_claims_are_qualified(self):
        readme = (ROOT / 'README.md').read_text('utf-8')
        changelog = (ROOT / 'CHANGELOG.md').read_text('utf-8')
        for text in (readme, changelog):
            self.assertNotRegex(text, r'never change a gate, approval or\s+ordering')
            self.assertNotRegex(text, r'change no gate, approval or ordering')
            self.assertRegex(text, r'`--signals`\s+re-ranks')
        for name in ('README.md', 'docs/architecture.md'):
            self.assertIn('CHANGELOG.md#compatibility-notes', (ROOT / name).read_text('utf-8'))
        self.assertNotIn('Default `discover` output and read order are frozen by goldens and unchanged', changelog)

    def test_relative_links_resolve(self):
        for path in DOCS:
            for target in re.findall(r'\]\(([^)#\s]+)(?:#[^)]*)?\)', path.read_text('utf-8')):
                if '://' in target or target.startswith('mailto:'):
                    continue
                with self.subTest(path=path.name, target=target):
                    self.assertTrue((path.parent / target).exists())

    def test_markdown_anchors_resolve(self):
        # The regrouped docs/cli.md relies on heading anchors; a renamed heading must not leave a dead link.
        def anchors(path):
            seen, found, fenced = {}, set(), False
            for text_line in path.read_text('utf-8').split('\n'):
                if text_line.startswith('```'):
                    fenced = not fenced
                heading = None if fenced else re.match(r'#{1,6} (.+)', text_line)
                if heading:
                    slug = re.sub(r'[^\w\- ]', '', heading.group(1).strip().lower()).replace(' ', '-')
                    found.add(slug if slug not in seen else f'{slug}-{seen[slug]}')
                    seen[slug] = seen.get(slug, 0) + 1
            return found
        for path in DOCS:
            for target, fragment in re.findall(r'\]\(([^)#\s]*)#([^)\s]+)\)', path.read_text('utf-8')):
                if '://' in target:
                    continue
                destination = path.parent / target if target else path
                if destination.suffix != '.md':
                    continue
                with self.subTest(path=path.name, link=target + '#' + fragment):
                    self.assertIn(fragment, anchors(destination))
        self.assertIn('command-index', anchors(ROOT / 'docs' / 'cli.md'))

    def test_product_map_lists_shipped_output_schemas_as_implemented(self):
        # Dogfood 3 F45: the map still listed the shipped output schemas as missing.
        from agent_contribute import outputs
        text = (ROOT / 'docs' / 'product-map.md').read_text('utf-8')
        implemented = text.split('### Implemented')[1].split('### Partly implemented')[0]
        self.assertTrue(outputs.SCHEMAS)
        self.assertIn('G1 ', implemented)
        self.assertNotIn('Missing: output JSON Schemas', text)
        self.assertNotIn('G1 output schemas', text)

    def test_product_map_covers_every_tracked_issue(self):
        text = (ROOT / 'docs' / 'product-map.md').read_text('utf-8')
        for number in [n for n in range(1, 29) if n != 2]:  # #2 is a pull request, not an issue
            with self.subTest(issue=number):
                self.assertRegex(text, rf'issues/{number}\)')

    def test_product_map_does_not_list_shipped_output_schemas_as_missing(self):
        # F45: G1 kept saying "Missing: output JSON Schemas" after schemas/output/1 and `schema` shipped.
        text = (ROOT / 'docs' / 'product-map.md').read_text('utf-8')
        self.assertTrue((ROOT / 'agent_contribute' / 'schemas' / 'output' / '1' / 'verify.schema.json').exists())
        missing = [line for line in text.splitlines() if 'Missing:' in line]
        self.assertFalse([line for line in missing if re.search(r'(?i)output (json )?schemas?|output-schema version', line)])


    def test_label_approval_docs_state_what_is_and_is_not_verified(self):
        # #9: policy 0.1 checks label presence only; no document may imply a verified or maintainer-applied label.
        flat = lambda path: ' '.join((ROOT / path).read_text('utf-8').split())
        texts = {path: flat(path) for path in ('README.md', 'SECURITY.md', 'docs/maintainers.md',
                                               'agent_contribute/instructions.md')}
        for path, text in texts.items():
            with self.subTest(path=path):
                self.assertIn('does not verify who applied it', text)
                self.assertNotIn('maintainer-approved', text)
        maintainers = texts['docs/maintainers.md']
        self.assertIn('suitable only if every principal who can label issues is trusted to approve agent work',
                      maintainers)
        self.assertIn('A dedicated label name restricts nothing', maintainers)
        self.assertIn('do not opt in under this policy', maintainers)
        # R9-07/R9-08: events name an actor; what is unverifiable is its authority and label binding.
        for path in ('README.md', 'SECURITY.md', 'agent_contribute/instructions.md'):
            with self.subTest(path=path):
                self.assertNotIn('cannot tell the CLI who', texts[path])
                self.assertRegex(texts[path], r'Public (issue )?events name an? (event |labeling )?actor')
        self.assertIn('configured label is currently present on the issue under the default-branch policy',
                      maintainers)
        self.assertIn('triage, write and higher roles, custom roles or grants that allow labelling', maintainers)
        self.assertIn('use the schema 0.2 mandate route', maintainers)
        design = flat('docs/design/2026-11-02-actor-verified-approval.md')
        self.assertIn('R9-05', design)
        self.assertIn('R9-06', design)
        self.assertIn('documented limitation; labeling-actor authority cannot be verified from public REST data',
                      flat('docs/product-map.md'))

if __name__ == '__main__':
    unittest.main()
