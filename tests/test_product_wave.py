"""Cross-feature journeys preserve snapshots without creating authority."""
import contextlib
import io
import hashlib
import xml.etree.ElementTree as ET
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from agent_contribute import cli, core, find, outputs
from tests.test_find import Fake
from tests.test_receipts import ReceiptGitHub
from tests.test_tipjar_discovery import SourcesGitHub

ROOT = Path(__file__).resolve().parents[1]


def invoke(*args):
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream):
        code = cli.main(list(map(str, args)))
    return code, json.loads(stream.getvalue())


class ProductWaveTests(unittest.TestCase):
    def test_welcomed_limited_discovery_roundtrips_through_session(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = [Path(directory) / name for name in ('discover.json', 'session.json')]
            with patch.object(core, 'GitHub', return_value=SourcesGitHub({'acme/photos': 'welcome'})):
                code, discovered = invoke('discover', 'acme/photos', 'person/photos', '--welcomed-only', '--limit', '1')
            self.assertEqual(code, 0)
            source.write_text(json.dumps(discovered), encoding='utf-8')
            with patch.object(core, 'GitHub', side_effect=AssertionError('offline')):
                code, planned = invoke('session', source, '--max-tasks', '2', '--minutes', '60', '--output', target)
            self.assertEqual(code, 0)
            self.assertEqual(planned['source_report'], discovered)
            self.assertEqual(planned['source_report']['display']['requested_limit'], 1)
            self.assertEqual([task['reference'] for task in planned['tasks']], ['acme/photos#12'])
            self.assertFalse(planned['actions_authorized'])
            self.assertEqual(core.schema_errors(planned, outputs.output_schema('session')), [])
            self.assertEqual(json.loads(target.read_text()), planned)

    @unittest.skipUnless(shutil.which('node'), 'Node required for canonical UI importer')
    def test_canonical_finder_snapshot_is_accepted_by_ui_importer(self):
        found = find.find_jars(Fake())
        self.assertEqual(core.schema_errors(found, outputs.output_schema('find')), [])
        result = subprocess.run(['node', '-e',
            "const fs=require('node:fs'),m=require('./web/model.js');"
            "const s=m.parseSnapshot(fs.readFileSync(0,'utf8'));"
            "process.stdout.write(JSON.stringify(s));"], cwd=ROOT,
            input=json.dumps(found), capture_output=True, text=True, check=True)
        imported = json.loads(result.stdout)
        self.assertEqual(imported['reports'][0]['repository'], found['observations'][0]['repository'])
        self.assertEqual(imported['reports'][0]['state'], 'welcome')
        self.assertEqual(imported['reports'][0]['manifest'], found['observations'][0]['jar']['manifest'])

    def test_init_file_is_accepted_by_jar_check_without_network(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(core, 'GitHub', side_effect=AssertionError('offline')):
            subprocess.run(['git', 'init', '--quiet', directory], check=True)
            path = Path(directory) / '.tipjar.json'
            code, created = invoke('init', '--status', 'closed', '--output', path)
            self.assertEqual(code, 0)
            code, checked = invoke('jar-check', path)
            self.assertEqual(code, 0)
            self.assertEqual(checked['state'], 'closed')
            self.assertEqual(checked['sha256'], created['sha256'])
            self.assertTrue(checked['valid'])
            status = subprocess.check_output(['git', '-C', directory, 'status', '--porcelain'], text=True)
            self.assertEqual(status.strip(), '?? .tipjar.json')

    def test_receipt_file_is_deduplicated_by_offline_impact(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'receipt.json'
            with patch.object(core, 'GitHub', return_value=ReceiptGitHub()):
                code, captured = invoke('receipt', 'acme/photos#30', '--output', path)
            self.assertEqual(code, 0)
            with patch.object(core, 'GitHub', side_effect=AssertionError('offline')):
                code, impact = invoke('impact', path, path)
            self.assertEqual(code, 0)
            self.assertEqual(impact['receipts'], [captured['receipt']])
            self.assertEqual(impact['unique_prs'], 1)
            self.assertEqual(impact['repositories_represented'], 1)
            self.assertNotIn('repositories_helped', impact)
            self.assertEqual(impact['trust'], 'self-reported recorded observations')

    def test_integrated_receipt_roundtrips_to_card_and_rejects_bad_input_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            path, svg = [Path(directory) / name for name in ('receipt.json', 'gift.svg')]
            with patch.object(core, 'GitHub', return_value=ReceiptGitHub()):
                code, captured = invoke('receipt', 'acme/photos#30', '--output', path)
            self.assertEqual(code, 0)
            self.assertEqual(core.schema_errors(captured, outputs.output_schema('receipt')), [])
            with patch.object(core, 'GitHub', side_effect=AssertionError('offline')):
                code, card = invoke('card', path, '--output', svg)
                self.assertEqual(code, 0)
                self.assertEqual(core.schema_errors(card, outputs.output_schema('card')), [])
                self.assertEqual(card['sha256'], hashlib.sha256(svg.read_bytes()).hexdigest())
                self.assertEqual(card['url'], captured['receipt']['pull_request']['url'])
                self.assertEqual(card['observed_at'], captured['receipt']['observed_at'])
                self.assertEqual(card['state'], 'draft')
                ET.fromstring(svg.read_bytes())
                code, impact = invoke('impact', path, path)
                self.assertEqual(code, 0)
                self.assertEqual(impact['receipts'], [captured['receipt']])
                self.assertEqual(core.schema_errors(impact, outputs.output_schema('impact')), [])
                broken = captured['receipt']
                broken['pull_request']['url'] += '?unsafe=1'
                path.write_text(json.dumps(broken), encoding='utf-8')
                target = Path(directory) / 'bad.svg'
                for args in [('impact', path), ('card', path, '--output', target)]:
                    code, result = invoke(*args)
                    self.assertEqual(code, 1)
                    self.assertEqual(result['error']['code'], 'invalid_receipt')
                self.assertFalse(target.exists())

    def test_shared_reference_definitions_have_one_meaning(self):
        definitions = {}
        for name in outputs.SCHEMAS:
            for key, value in outputs.output_schema(name).get('$defs', {}).items():
                with self.subTest(command=name, definition=key):
                    if key in definitions:
                        self.assertEqual(value, definitions[key])
                    definitions[key] = value
