"""Pre-release checklist: every place that states the package version agrees (tools/release_check.py, #26)."""
import contextlib
import importlib.util
import io
import pathlib
import re
import shutil
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load():
    spec = importlib.util.spec_from_file_location('release_check', ROOT / 'tools' / 'release_check.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release_check = load()


class VersionAgreementTests(unittest.TestCase):
    def copy(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = pathlib.Path(tmp.name)
        for relative in release_check.SOURCES:
            (root / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, root / relative)
        return root

    def edit(self, root, relative, old, new):
        path = root / relative
        text = path.read_text('utf-8')
        self.assertIn(old, text)
        path.write_text(text.replace(old, new, 1), 'utf-8')

    def test_every_known_version_statement_is_checked(self):
        self.assertEqual(sorted(release_check.SOURCES), sorted([
            'pyproject.toml', 'agent_contribute/__init__.py', 'CHANGELOG.md', 'agent_contribute/instructions.md',
            'tools/check_install.py', 'tests/test_protocol.py']))
        self.assertEqual(len(release_check.SOURCES['agent_contribute/instructions.md']), 2)

    def test_the_checkout_agrees(self):
        self.assertEqual(release_check.problems(ROOT), [])
        version = release_check.version(ROOT)
        self.assertRegex(version, r'\A[0-9]+\.[0-9]+\.[0-9]+\Z')

    def test_each_source_disagreeing_is_reported(self):
        version = release_check.version(ROOT)
        for relative in release_check.SOURCES:
            if relative == 'pyproject.toml':
                continue
            with self.subTest(source=relative):
                root = self.copy()
                self.edit(root, relative, version, '9.9.9')
                problems = release_check.problems(root)
                self.assertTrue(any(relative in problem for problem in problems), problems)

    def test_a_vanished_statement_is_reported_not_ignored(self):
        root = self.copy()
        self.edit(root, 'agent_contribute/instructions.md', 'CLI/library version is', 'CLI version:')
        self.assertTrue(release_check.problems(root))

    def set_heading(self, root, state):
        """Give the copied CHANGELOG an explicit first-heading state, whatever the checkout's is (REL-01)."""
        path = root / 'CHANGELOG.md'
        text = path.read_text('utf-8')
        heading = re.search(r'(?m)^## .*$', text)
        path.write_text(text[:heading.start()] + f'## {release_check.version(root)} — {state}' + text[heading.end():],
                        'utf-8')

    def test_changelog_heading_and_release_mode(self):
        root = self.copy()
        self.set_heading(root, 'unreleased')
        self.assertEqual(release_check.problems(root), [])
        self.assertTrue(any('dated' in problem for problem in release_check.problems(root, release=True)))
        self.set_heading(root, '2026-11-03')
        self.assertEqual(release_check.problems(root, release=True), [])
        for state in ('soon', '2026-99-99', '0000-00-00', '2026-02-30', '26-11-03'):
            with self.subTest(state=state):
                self.set_heading(root, state)
                self.assertTrue(release_check.problems(root))

    def test_a_dated_release_checkout_passes_every_check(self):
        root = self.copy()
        self.set_heading(root, '2026-11-03')
        version = release_check.version(root)
        self.assertEqual(release_check.problems(root), [])
        self.assertEqual(release_check.problems(root, release=True, tag='v' + version), [])

    def test_tag_must_name_the_version(self):
        version = release_check.version(ROOT)
        self.assertEqual(release_check.problems(ROOT, tag='v' + version), [])
        for tag in (version, 'v' + version + '-rc1', 'v9.9.9', 'v' + version + '\n', ''):
            with self.subTest(tag=tag):
                self.assertTrue(release_check.problems(ROOT, tag=tag))

    def test_command_line_exit_status(self):
        root = self.copy()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(release_check.main(['--root', str(root)]), 0)
        self.edit(root, 'agent_contribute/__init__.py', release_check.version(root), '9.9.9')
        with contextlib.redirect_stdout(out):
            self.assertEqual(release_check.main(['--root', str(root)]), 1)
        self.assertIn('agent_contribute/__init__.py', out.getvalue())


class RunbookTests(unittest.TestCase):
    def test_runbook_names_the_checks_the_workflow_and_rollback(self):
        text = (ROOT / 'docs' / 'releasing.md').read_text('utf-8')
        for phrase in ('python tools/release_check.py --release', '--tag vX.Y.Z', 'examples/release-pypi.yml',
                       'gh attestation verify', 'pending* publisher', 'environment `pypi`', 'Never reuse',
                       'a version number', 'Yank it', 'Never move a published tag'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)
        self.assertIn('docs/releasing.md', (ROOT / 'CONTRIBUTING.md').read_text('utf-8'))


if __name__ == '__main__':
    unittest.main()
