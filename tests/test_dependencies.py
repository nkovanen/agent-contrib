"""Offline dependency provenance and hostile-input regressions."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from agent_contribute import cli, core, dependencies

FIXTURES = Path(__file__).parent / 'fixtures' / 'dependencies'


def invoke(*args):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = cli.main(list(args))
    return code, output.getvalue()


class DependenciesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, name, data):
        path = self.root / name
        path.write_text(data, encoding='utf-8')
        return path

    def report(self, path=None):
        code, text = invoke('dependencies', str(path or self.root))
        self.assertEqual(code, 0, text)
        return json.loads(text)

    def test_real_formats_preserve_provenance_and_deduplicate(self):
        for file in FIXTURES.iterdir():
            shutil.copyfile(file, self.root / file.name)
        with patch.object(core, 'GitHub', side_effect=AssertionError('offline')):
            result = self.report()
        self.assertEqual(result['repositories'], ['Example/Parser', 'example/Other', 'example/Helper'])
        self.assertTrue(result['complete'])
        self.assertFalse(result['resolution_complete'])
        self.assertEqual(len(result['sources']), 3)
        self.assertTrue(all(len(s['sha256']) == 64 for s in result['sources']))
        ref = next(d for d in result['dependencies'] if d['field'] == 'line:2')
        self.assertEqual((ref['package'], ref['repository'], ref['revision'], ref['subdirectory']),
                         ('Parser[fast]', 'EXAMPLE/parser', 'release/2', 'python'))
        self.assertEqual(ref['source_file'], 'requirements.txt')
        locked = next(d for d in result['dependencies'] if d['field'] == 'packages.node_modules/parser.resolved')
        self.assertEqual(locked['revision'], 'abc123')
        self.assertEqual({d['status'] for d in result['dependencies']}, {'github', 'unresolved', 'unsupported'})

    def test_v1_lock_nested_git_dependencies(self):
        self.write('package-lock.json', json.dumps({'lockfileVersion': 1, 'dependencies': {
            'one': {'version': 'git+https://github.com/team/one.git#v1', 'dependencies': {
                'two': {'version': '2.0', 'resolved': 'git+https://github.com/team/two.git#abc'}}}}}))
        result = self.report()
        self.assertEqual(result['repositories'], ['team/one', 'team/two'])
        self.assertTrue(result['resolution_complete'])

    def test_only_recognized_github_urls_produce_candidates(self):
        valid = {'https://github.com/Owner/repo.git#v1': ('Owner/repo', 'v1', None),
                 'git+https://github.com/Owner/repo.git@feature/x#subdirectory=src/pkg':
                     ('Owner/repo', 'feature/x', 'src/pkg'),
                 'git@github.com:Owner/repo.git#sha': ('Owner/repo', 'sha', None)}
        invalid = ['https://github.com.evil/a/b', 'https://token@github.com/a/b',
                   'https://github.com:443/a/b', 'https://github.com/a/b/extra',
                   'https://github.com/a/../b', 'https://github.com/a/%2e%2e',
                   'https://github.com/a/b?token=secret', 'https://github.com/a/b#subdirectory=../bad',
                   'git@evil.com:a/b', 'github:a/b', 'a/b', 'https://github.com/a/b#x%0aforged',
                   'https://github.com/a/b@ref#subdirectory=/abs']
        values = list(valid) + invalid
        self.write('package.json', json.dumps({'dependencies': {str(i): v for i, v in enumerate(values)}}))
        result = self.report()
        self.assertEqual(result['repositories'], ['Owner/repo'])
        for record, expected in zip(result['dependencies'], valid.values()):
            self.assertEqual((record['repository'], record['revision'], record['subdirectory']), expected)
        self.assertTrue(all(d['repository'] is None for d in result['dependencies'][len(valid):]))
        self.assertNotIn('token@', json.dumps(result))
        self.assertNotIn('token=secret', json.dumps(result))

    def test_malformed_or_ambiguous_manifests_fail_closed(self):
        for name, data in [('package.json', '{"dependencies":{},"dependencies":{}}'),
                           ('package.json', '{'), ('package.json', '[]'),
                           ('package.json', '{"dependencies":{"x":42}}'),
                           ('package.json', '{"dependencies":[]}'),
                           ('package.json', json.dumps({'dependencies': {'x': 'https://github.com/a/b#x\nforged'}})),
                           ('package-lock.json', '{"lockfileVersion":99,"packages":{}}'),
                           ('package-lock.json', '{"lockfileVersion":3,"packages":[]}')]:
            with self.subTest(data=data):
                path = self.write(name, data)
                code, text = invoke('dependencies', str(path))
                self.assertEqual(code, 1)
                self.assertIn('error', json.loads(text))
                path.unlink()

    def test_refuses_symlinks_nonregular_files_and_oversized_inputs(self):
        path = self.write('package.json', '{}')
        link = self.root / 'alias'
        link.symlink_to(self.root, target_is_directory=True)
        code, text = invoke('dependencies', str(link / 'package.json'))
        self.assertEqual(code, 1, text)
        path.unlink()
        path.symlink_to(FIXTURES / 'package.json')
        self.assertEqual(invoke('dependencies', str(self.root))[0], 1)
        path.unlink()
        if hasattr(os, 'mkfifo'):
            os.mkfifo(path)
            self.assertEqual(invoke('dependencies', str(self.root))[0], 1)
            path.unlink()
        self.write('package.json', ' ' * (8 * 1024 * 1024 + 1))
        self.assertEqual(invoke('dependencies', str(self.root))[0], 1)

    def test_unsupported_files_are_visible_and_no_recursive_scan(self):
        self.write('Cargo.toml', '[dependencies]\n')
        self.write('pyproject.toml', '[project]\n')
        (self.root / 'nested').mkdir()
        (self.root / 'nested' / 'package.json').write_text('{"dependencies":{"x":"https://github.com/a/b"}}')
        result = self.report()
        self.assertFalse(result['complete'])
        self.assertEqual(result['unsupported_files'], ['Cargo.toml', 'pyproject.toml'])
        self.assertEqual(result['repositories'], [])
        self.assertEqual(invoke('dependencies', str(self.root / 'missing'))[0], 1)

    def test_requirements_registry_entries_stay_unresolved_and_includes_are_not_followed(self):
        self.write('requirements.txt', 'requests>=2\n-r private.txt\n')
        self.write('private.txt', 'should-not-be-read @ https://github.com/hidden/private\n')
        result = self.report()
        self.assertEqual(result['repositories'], [])
        self.assertEqual([(d['package'], d['status'], d['reason']) for d in result['dependencies']],
                         [('requests', 'unresolved', 'registry_or_nonexplicit_source'),
                          ('(unparsed line 2)', 'unsupported', 'unsupported_requirement_syntax')])

    def test_entry_bound_fails_closed_without_partial_candidates(self):
        self.write('package.json', json.dumps({'dependencies': {
            'p' + str(i): 'https://github.com/example/repo' for i in range(10001)}}))
        code, text = invoke('dependencies', str(self.root))
        self.assertEqual(code, 1, text)
        self.assertEqual(set(json.loads(text)), {'error'})

    def test_requirements_comment_lexer_preserves_quoted_hashes_and_url_fragments(self):
        values = {
            'pkg @ https://github.com/o/r#egg=pkg # note': 'pkg @ https://github.com/o/r#egg=pkg',
            'pkg @ URL#subdirectory=src # note': 'pkg @ URL#subdirectory=src',
            'pkg ; value == " # text" # note': 'pkg ; value == " # text"',
            "pkg ; value == ' # text' # note": "pkg ; value == ' # text'",
            'pkg ; value == " # text"': 'pkg ; value == " # text"',
        }
        for value, expected in values.items():
            with self.subTest(value=value):
                self.assertEqual(dependencies._without_requirement_comment(value), expected)

    def test_requirements_trailing_comments_keep_url_fragments_and_markers(self):
        self.write('requirements.txt',
                   'foo @ git+https://github.com/o/r.git@v1 # pinned upstream\n'
                   'bar @ git+https://github.com/o/s.git@v2#subdirectory=python # monorepo\n'
                   'baz @ https://github.com/o/t.git@v3 ; platform_release == " # literal" # note\n')
        result = self.report()
        self.assertEqual(result['repositories'], ['o/r', 'o/s', 'o/t'])
        self.assertEqual([(d['revision'], d['subdirectory']) for d in result['dependencies']],
                         [('v1', None), ('v2', 'python'), ('v3', None)])
        self.assertTrue(result['resolution_complete'])

    def test_exclusive_output_text_and_offline_options(self):
        self.write('package.json', '{"dependencies":{"x":"https://github.com/a/b"}}')
        dest = self.root / 'report.json'
        code, text = invoke('dependencies', str(self.root), '--output', str(dest))
        self.assertEqual(code, 0, text)
        self.assertEqual(json.loads(dest.read_text()), json.loads(text))
        self.assertEqual(invoke('dependencies', str(self.root), '--output', str(dest))[0], 1)
        code, text = invoke('--format', 'text', 'dependencies', str(self.root))
        self.assertEqual(code, 0, text)
        self.assertIn('a/b', text)
        self.assertIn('grants no approval', text)
        for option in ('--cache', '--report-budget'):
            self.assertEqual(invoke(option, 'dependencies', str(self.root))[0], 2)


if __name__ == '__main__':
    unittest.main()
