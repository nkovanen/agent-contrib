"""Explicit bounded npm installation metadata, with no execution or network."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent_contribute import core
from tests.test_dependencies import FIXTURES, invoke


class InstalledDependenciesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def manifest(self, dependencies, **groups):
        (self.root / 'package.json').write_text(json.dumps({'dependencies': dependencies, **groups}))

    def installed(self, name, metadata=None):
        path = self.root / 'node_modules' / name / 'package.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(metadata or {'name': name, 'version': '1.2.3',
                                               'repository': 'https://github.com/example/library.git'}))
        return path

    def report(self):
        code, text = invoke('dependencies', str(self.root), '--installed')
        self.assertEqual(code, 0, text)
        return json.loads(text)

    def test_common_registry_packages_resolve_only_with_explicit_opt_in(self):
        self.manifest({'express': '^5', 'react': '^19', 'lodash': '^4'})
        for name in ('express', 'react', 'lodash'):
            path = self.installed(name)
            path.write_bytes((FIXTURES / f'installed-{name}.json').read_bytes())
        with patch.object(core, 'GitHub', side_effect=AssertionError('offline')):
            code, text = invoke('dependencies', str(self.root))
            self.assertEqual(code, 0, text)
            self.assertEqual(json.loads(text)['repositories'], [])
            result = self.report()
        self.assertEqual(result['repositories'], ['expressjs/express', 'facebook/react', 'lodash/lodash'])
        self.assertTrue(result['resolution_complete'])
        self.assertTrue(result['installed']['complete'])
        self.assertEqual(result['installed']['examined'], 3)
        react = result['dependencies'][1]
        self.assertEqual((react['source_file'], react['field'], react['subdirectory']),
                         ('package.json', 'dependencies.react', 'packages/react'))
        meta = react['installed']
        self.assertEqual((meta['source_file'], meta['name'], meta['version'], meta['field']),
                         ('node_modules/react/package.json', 'react', '19.1.0', 'repository.url'))
        self.assertEqual(len(meta['sha256']), 64)

    def test_scoped_direct_groups_dedup_and_project_candidates_precede_lock_candidates(self):
        self.manifest({'@scope/pkg': '^1'}, devDependencies={'@scope/pkg': '^1'})
        self.installed('@scope/pkg')
        (self.root / 'package-lock.json').write_text(json.dumps({'lockfileVersion': 3, 'packages': {
            'node_modules/transitive': {'resolved': 'https://github.com/other/transitive.git'}}}))
        result = self.report()
        self.assertEqual(result['repositories'], ['example/library', 'other/transitive'])
        self.assertEqual(result['installed']['examined'], 1)
        self.assertEqual(result['dependencies'][0]['installed']['name'], '@scope/pkg')

    def test_missing_and_ambiguous_metadata_stay_unresolved(self):
        self.manifest({name: '*' for name in ('missing', 'wrong', 'homepage', 'conflict', 'non-github')})
        self.installed('wrong', {'name': 'different', 'version': '1.0.0', 'repository': 'https://github.com/a/b'})
        self.installed('homepage', {'name': 'homepage', 'version': '1.0.0', 'homepage': 'https://github.com/a/b'})
        self.installed('conflict', {'name': 'conflict', 'version': '1.0.0', 'repository': {
            'url': 'https://github.com/a/b#subdirectory=one', 'directory': 'two'}})
        self.installed('non-github', {'name': 'non-github', 'version': '1.0.0',
                                      'repository': 'https://gitlab.com/a/b'})
        result = self.report()
        self.assertEqual(result['repositories'], [])
        self.assertFalse(result['installed']['complete'])
        self.assertFalse(result['resolution_complete'])
        self.assertEqual([d['installed']['reason'] for d in result['dependencies']],
                         ['missing_installed_metadata', 'installed_name_mismatch', 'missing_repository_metadata',
                          'ambiguous_repository_directory', 'non_github_or_unsafe_repository'])

    def test_symlinked_pnpm_and_nonregular_or_oversized_metadata_are_not_followed(self):
        self.manifest({'linked': '*', 'fifo': '*', 'large': '*'})
        target = self.root / 'outside'
        target.mkdir()
        (target / 'package.json').write_text('{"name":"linked","version":"1.0.0","repository":"https://github.com/a/b"}')
        (self.root / 'node_modules').mkdir()
        (self.root / 'node_modules' / 'linked').symlink_to(target, target_is_directory=True)
        fifo = self.installed('fifo')
        fifo.unlink()
        os.mkfifo(fifo)
        self.installed('large').write_text(' ' * (64 * 1024 + 1))
        result = self.report()
        self.assertEqual(result['repositories'], [])
        self.assertTrue(all(d['installed']['status'] == 'unsupported' for d in result['dependencies']))
        self.assertEqual(json.loads(invoke('dependencies', str(self.root))[1])['repositories'], [])

    def test_malicious_package_names_cannot_escape_and_aliases_are_not_guessed(self):
        self.manifest({'../escape': '*', '@scope/../../escape': '*', 'alias': 'npm:express@5',
                       'local': 'file:../private', 'shorthand': 'owner/repo'})
        result = self.report()
        self.assertEqual(result['repositories'], [])
        self.assertEqual(result['installed']['examined'], 2)
        self.assertTrue(all(d['installed']['reason'] == 'unsafe_package_name'
                            for d in result['dependencies'][:2]))
        self.assertTrue(all('installed' not in d for d in result['dependencies'][2:]))

    def test_duplicate_keys_and_bad_identity_version_metadata_never_resolve(self):
        self.manifest({'duplicate': '*', 'version': '*', 'credentials': '*'})
        self.installed('duplicate').write_text('{"name":"duplicate","name":"duplicate","version":"1.0.0"}')
        self.installed('version', {'name': 'version', 'version': 1, 'repository': 'https://github.com/a/b'})
        self.installed('credentials', {'name': 'credentials', 'version': '1.0.0',
                                       'repository': 'https://secret@github.com/a/b'})
        result = self.report()
        self.assertEqual(result['repositories'], [])
        self.assertNotIn('secret', json.dumps(result))

    def test_text_surfaces_unsupported_symlinks_and_observed_versions(self):
        self.manifest({'express': '^5', 'linked': '*'})
        self.installed('express', {'name': 'express', 'version': '5.1.0',
                                   'repository': 'https://github.com/expressjs/express.git'})
        (self.root / 'node_modules' / 'linked').symlink_to(self.root, target_is_directory=True)
        code, text = invoke('--format', 'text', 'dependencies', str(self.root), '--installed')
        self.assertEqual(code, 0, text)
        self.assertIn('express@5.1.0', text)
        self.assertIn('unsafe_or_unreadable_installed_metadata', text)

    def test_package_cap_and_explicit_path_scope(self):
        self.manifest({'p' + str(n): '*' for n in range(101)})
        code, text = invoke('dependencies', str(self.root), '--installed')
        self.assertEqual(code, 1, text)
        self.assertEqual(set(json.loads(text)), {'error'})
        requirements = self.root / 'requirements.txt'
        requirements.write_text('requests>=2\n')
        code, text = invoke('dependencies', str(requirements), '--installed')
        self.assertEqual(code, 2, text)
        self.manifest({'express': '^5'})
        self.installed('express')
        code, text = invoke('dependencies', str(self.root / 'package.json'), '--installed')
        self.assertEqual(code, 0, text)
        self.assertEqual(json.loads(text)['repositories'], ['example/library'])


if __name__ == '__main__':
    unittest.main()
