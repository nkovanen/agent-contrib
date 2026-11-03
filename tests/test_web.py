"""Exercise static-site trust boundaries with Node's dependency-free test runner."""
from pathlib import Path
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
