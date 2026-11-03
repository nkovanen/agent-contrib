"""Exercise static-site trust boundaries with Node's dependency-free test runner."""
from pathlib import Path
import json
import shutil
import subprocess
import unittest


class WebModelTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node required for static web model tests')
    def test_snapshot_and_manifest_boundaries(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(['node', str(root / 'tests/web/model.test.cjs')],
                                cwd=root, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'Node required for static web model tests')
    def test_export_accepted_by_canonical_manifest_parser(self):
        from agent_contribute.tipjar import parse_manifest
        root = Path(__file__).resolve().parents[1]
        script = "process.stdout.write(JSON.stringify(require('./web/model').makeManifest('closed','Docs\\nTests','Ask first'),null,2))"
        result = subprocess.run(['node', '-e', script], cwd=root,
                                capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(parse_manifest(result.stdout), {
            'schema_version': '0.1', 'status': 'closed',
            'wanted': ['Docs', 'Tests'], 'boundaries': ['Ask first']})

    @unittest.skipUnless(shutil.which('node'), 'Node required for static web model tests')
    def test_unicode_boundaries_match_canonical_parser(self):
        from agent_contribute import core
        from agent_contribute.tipjar import parse_manifest
        root = Path(__file__).resolve().parents[1]
        values = ['\u0085', '\ufeff', '\u0020', '\u00a0', '\u1680', '\u2000',
                  '\u2028', '\u2029', '\u202f', '\u205f', '\u3000',
                  '\tDocs', 'Docs\t', '\x00', '\x1f', '\x7f', '  Docs  ',
                  '\ufeffDocs\ufeff', '😀' * 500, '😀' * 501]
        script = """const m=require('./web/model'), fs=require('node:fs');
const values=JSON.parse(fs.readFileSync(0,'utf8'));
process.stdout.write(JSON.stringify(values.map(value=>{
  try { return m.makeManifest('welcome',value,''); } catch { return null; }
})));"""
        result = subprocess.run(['node', '-e', script], cwd=root,
                                input=json.dumps(values), capture_output=True,
                                text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = json.loads(result.stdout)
        self.assertEqual(len(observed), len(values))
        for value, actual in zip(values, observed):
            with self.subTest(value=repr(value[:30])):
                expected = {'schema_version': '0.1', 'status': 'welcome',
                            'wanted': [value], 'boundaries': []}
                try:
                    parse_manifest(json.dumps(expected, ensure_ascii=False).encode())
                except core.ProtocolError:
                    self.assertIsNone(actual)
                else:
                    self.assertEqual(actual, expected)

    @unittest.skipUnless(shutil.which('node'), 'Node required for static web model tests')
    def test_real_find_nullable_diagnostics_keep_identifiable_repositories(self):
        from agent_contribute.find import find_jars
        from tests.test_find import Fake, hit, page
        root = Path(__file__).resolve().parents[1]
        private = hit('hidden/private', 7, 8)
        private['repository']['private'] = True
        for extra, complete in ((None, False), (private, True)):
            with self.subTest(private=extra is not None):
                report = find_jars(Fake(search=page([hit(), extra])))
                script = """const fs=require('node:fs'), m=require('./web/model');
const result=m.parseSnapshot(fs.readFileSync(0,'utf8'));
process.stdout.write(JSON.stringify({repositories:result.reports.map(x=>x.repository),
  complete:result.complete, skipped:result.skippedUnidentifiable, errors:result.errors}));"""
                result = subprocess.run(['node', '-e', script], cwd=root,
                                        input=json.dumps(report), capture_output=True,
                                        text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), {
                    'repositories': ['acme/project'], 'complete': complete,
                    'skipped': 1, 'errors': []})
