"""Offline cards preserve observation semantics and never activate untrusted SVG."""
import contextlib
import copy
import hashlib
import io
import importlib.resources
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from agent_contribute import cli, core, outputs, receipts
from tests.test_receipts import ReceiptGitHub, invoke

SVG = '{http://www.w3.org/2000/svg}'


class CardTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.receipt = receipts.observe('acme/photos#30', ReceiptGitHub())
        self.receipt['observed_at'] = '2026-01-02T03:04:05Z'

    def save(self, receipt=None):
        path = self.root / 'receipt.json'
        path.write_text(json.dumps(receipt or self.receipt), encoding='utf-8')
        return path

    def card(self, path=None, name='card.svg'):
        return invoke('card', str(path or self.save()), '--output', str(self.root / name))

    def test_card_response_contract_starts_at_output2(self):
        self.assertEqual(outputs.output_schema('card')['$id'], 'urn:agent-contrib:output:2:card')
        resources = importlib.resources.files('agent_contribute')
        self.assertFalse(resources.joinpath('schemas/output/1/card.schema.json').is_file())

    def test_card_is_offline_exclusive_and_digest_matches_artifact(self):
        path = self.save()
        with patch.object(core.GitHub, 'request', side_effect=AssertionError('network')):
            code, result = self.card(path)
        self.assertEqual(code, 0, result)
        data = (self.root / 'card.svg').read_bytes()
        self.assertEqual(result['sha256'], hashlib.sha256(data).hexdigest())
        self.assertEqual(core.schema_errors(result, outputs.output_schema('card')), [])
        self.assertEqual(self.card(path)[0], 1)
        self.assertEqual((self.root / 'card.svg').read_bytes(), data)
        (self.root / 'link.svg').symlink_to(self.root / 'card.svg')
        self.assertEqual(self.card(path, 'link.svg')[0], 1)
        self.assertEqual((self.root / 'card.svg').read_bytes(), data)
        for flag in ('--cache', '--report-budget'):
            self.assertEqual(invoke(flag, 'card', str(path), '--output', str(self.root / 'bad.svg'))[0], 2)

    def test_accessible_svg_is_deterministic_and_has_only_canonical_link(self):
        path = self.save()
        self.assertEqual(self.card(path)[0], 0)
        self.assertEqual(self.card(path, 'other.svg')[0], 0)
        data = (self.root / 'card.svg').read_bytes()
        self.assertEqual(data, (self.root / 'other.svg').read_bytes())
        svg = ET.fromstring(data)
        self.assertEqual(svg.attrib['role'], 'img')
        self.assertTrue(svg.find(SVG + 'title').text)
        self.assertTrue(svg.find(SVG + 'desc').text)
        self.assertEqual([e.attrib['href'] for e in svg.iter(SVG + 'a')], ['https://github.com/acme/photos/pull/30'])
        # Content must paint after the opaque panel, rather than being hidden underneath it.
        children = list(svg)
        panel = next(e for e in children if e.attrib.get('fill') == '#fffcf4')
        content = next(e for e in children if e.find(SVG + 'text') is not None)
        self.assertGreater(children.index(content), children.index(panel))
        text = ' '.join(svg.itertext())
        for fact in ('acme/photos', '#30', 'Observed draft', '2026-01-02', 'Agent work', 'editable', 'not authenticated'):
            self.assertIn(fact, text)
        for element in svg.iter():
            self.assertIn(element.tag.removeprefix(SVG), {'svg', 'title', 'desc', 'rect', 'path', 'circle', 'g', 'text', 'a'})
            self.assertFalse(any(key.lower().startswith('on') for key in element.attrib))

    def test_rejects_invalid_receipts_before_creation(self):
        for mutate in (lambda r: r.update(schema_version='99'),
                       lambda r: r['pull_request'].update(url='javascript:alert(1)'),
                       lambda r: r['pull_request'].update(state='merged'),
                       lambda r: r['repository'].update(private=True)):
            receipt = copy.deepcopy(self.receipt)
            mutate(receipt)
            self.assertEqual(self.card(self.save(receipt))[0], 1)
            self.assertFalse((self.root / 'card.svg').exists())
        path = self.save()
        link = self.root / 'link.json'
        link.symlink_to(path)
        self.assertEqual(self.card(link)[0], 1)
        path.write_text(' ' * 65537)
        self.assertEqual(self.card(path)[0], 1)
        self.assertEqual(self.card(self.root)[0], 1)

    def test_text_summary_explains_manual_sharing(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(['--format', 'text', 'card', str(self.save()), '--output', str(self.root / 'card.svg')])
        self.assertEqual(code, 0)
        self.assertIn('Share manually', out.getvalue())

    def test_caption_xml_injection_is_text_and_full_caption_is_accessible(self):
        caption = '</text><script>alert("x")</script>& "gift" 日本語 🚀'
        code, result = invoke('card', str(self.save()), '--caption', caption, '--output', str(self.root / 'card.svg'))
        self.assertEqual(code, 0, result)
        svg = ET.fromstring((self.root / 'card.svg').read_bytes())
        self.assertIn(caption, svg.find(SVG + 'title').text)
        self.assertIn(caption, svg.find(SVG + 'desc').text)
        self.assertIn('Personal caption', ' '.join(svg.itertext()))
        self.assertEqual(list(svg.iter(SVG + 'script')), [])
        self.assertNotIn('<script>', (self.root / 'card.svg').read_text())

    def test_long_unicode_and_controls_produce_bounded_valid_xml(self):
        from agent_contribute import cards
        caption = '日' * 300 + '\u202e\x00\ud800' + '👩\u200d💻' * 300
        data, _ = cards.render(self.save(), caption=caption)
        svg = ET.fromstring(data)
        accessible = svg.find(SVG + 'title').text
        self.assertIn('日' * 300, accessible)
        self.assertNotIn('\u202e', accessible)
        self.assertNotIn('\ud800', accessible)
        visible = [e.text or '' for e in svg.iter(SVG + 'text')]
        self.assertTrue(any('…' in line for line in visible))
        self.assertLess(max(map(len, visible)), 100)
        combining, _ = cards.render(self.save(), caption='a' + '\u0301' * 3000)
        texts = [e.text or '' for e in ET.fromstring(combining).iter(SVG + 'text')]
        self.assertLess(max(map(len, texts)), 100)
        for caption in ('', ' ', 'x' * 4097, '\x00\u202e', 7):
            with self.assertRaises(core.ProtocolError):
                cards.render(self.save(), caption=caption)

    def test_exact_states(self):
        for state in ('draft', 'open', 'closed', 'merged'):
            value = copy.deepcopy(self.receipt)
            pr = value['pull_request']
            pr.update(state=state, draft=state == 'draft')
            if state in ('closed', 'merged'):
                pr['merge']['closed_at'] = '2026-01-01T00:00:00Z'
            if state == 'merged':
                pr['merge'].update(merged=True, merged_at='2026-01-01T00:00:00Z',
                                   commit_sha='c' * 40, merged_by={'id': 8, 'login': 'maintainer', 'type': 'User'})
            self.assertEqual(self.card(self.save(value), state + '.svg')[0], 0)
            svg = ET.fromstring((self.root / (state + '.svg')).read_bytes())
            self.assertIn('Observed ' + state, ' '.join(svg.itertext()))

    def test_untrusted_title_extension_is_rejected(self):
        self.receipt['pull_request']['title'] = '</text><script/>'
        self.assertEqual(self.card(self.save())[0], 1)
        self.assertFalse((self.root / 'card.svg').exists())
