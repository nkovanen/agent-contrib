"""Untrusted manifest bytes and single-attempt pinned GitHub reads."""
import base64
import copy
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch, Mock

from agent_contribute import cache, core, tipjar

COMMIT = 'a' * 40
TREE = 'b' * 40
RAW = b'{"schema_version":"0.1","status":"welcome"}'


def responses(raw=RAW, entries=None):
    blob = cache.blob_sha(raw)
    return {
        'repos/acme/project': {'full_name': 'acme/project', 'default_branch': 'main',
                              'fork': True, 'has_issues': False, 'parent': {'full_name': 'other/parent'},
                              'private': False, 'visibility': 'public'},
        'repos/acme/project/commits/main': {'sha': COMMIT, 'commit': {'tree': {'sha': TREE}}},
        f'repos/acme/project/commits/{COMMIT}': {'sha': COMMIT, 'commit': {'tree': {'sha': TREE}}},
        f'repos/acme/project/git/trees/{TREE}?recursive=1': {
            'sha': TREE, 'truncated': False, 'tree': entries if entries is not None else [
                {'path': '.tipjar.json', 'type': 'blob', 'mode': '100644', 'sha': blob}]},
        f'repos/acme/project/contents/.tipjar.json?ref={COMMIT}': {
            'type': 'file', 'encoding': 'base64', 'path': '.tipjar.json', 'sha': blob,
            'size': len(raw), 'content': base64.b64encode(raw).decode()}}


class Fake:
    def __init__(self, data=None):
        self.data = responses() if data is None else data
        self.calls = []

    def request(self, endpoint):
        self.calls.append(endpoint)
        value = self.data[endpoint]
        if isinstance(value, Exception):
            raise value
        return copy.deepcopy(value)


class ManifestTests(unittest.TestCase):
    def test_valid_objects_preserve_source_omissions_and_text(self):
        for status in ('welcome', 'closed'):
            value = {'schema_version': '0.1', 'status': status}
            self.assertEqual(tipjar.parse_manifest(json.dumps(value).encode()), value)
        value.update(wanted=['$(touch /tmp/never-run)', 'λ' * 500], boundaries=[str(i) for i in range(16)])
        with patch('subprocess.run', side_effect=AssertionError('manifest executed')):
            self.assertEqual(tipjar.parse_manifest(json.dumps(value).encode()), value)
        self.assertEqual(tipjar.parse_manifest(RAW + b' ' * (16384 - len(RAW)))['status'], 'welcome')

    def test_required_parity_dependencies_cannot_skip(self):
        for missing in ('node', 'ajv'):
            with self.subTest(missing=missing), patch.dict(os.environ, {
                    'TIPJAR_PARITY_AJV': '/required/ajv/dist/2020'}), patch(
                    'shutil.which', return_value=None if missing == 'node' else '/node'), patch(
                    'subprocess.run', return_value=types.SimpleNamespace(returncode=1)):
                try:
                    with self.assertRaises(AssertionError):
                        self.test_manifest_schema_matches_independent_ecmascript_validator()
                except unittest.SkipTest:
                    self.fail('Required CI parity check silently skipped')

    def test_manifest_schema_matches_independent_ecmascript_validator(self):
        module = os.environ.get('TIPJAR_PARITY_AJV', 'ajv/dist/2020')
        required = 'TIPJAR_PARITY_AJV' in os.environ
        node = shutil.which('node')
        if node is None:
            if required:
                self.fail('Required independent parity check requires Node')
            self.skipTest('Optional independent parity check requires Node and Ajv 2020')
        probe = subprocess.run([node, '-e', 'require(process.argv[1])', module], capture_output=True, timeout=15)
        if probe.returncode:
            if required:
                self.fail('Required independent parity check cannot load configured Ajv 2020')
            self.skipTest('Optional independent parity check requires Ajv 2020')
        schema = json.loads(pathlib.Path(tipjar.__file__).with_name('tipjar.schema.json').read_text('utf-8'))
        # Unicode White_Space, explicitly fixed by the manifest contract, not either runtime's shorthand.
        whitespace = [*range(9, 14), 0x20, 0x85, 0xa0, 0x1680, *range(0x2000, 0x200b),
                      0x2028, 0x2029, 0x202f, 0x205f, 0x3000]
        texts = [('', False), (' ', False), ('\ufeff', True), ('\u0085', False),
                 (' \u0085x ', True), ('😀' * 500, True), ('😀' * 501, False),
                 ('\x1cx', False), ('\x7fx', False)]
        texts += [(chr(point), False) for point in whitespace]
        texts += [(chr(point) + 'x', point >= 32) for point in whitespace]
        texts += [(chr(point) + '\ufeff', point >= 32) for point in whitespace]
        cases = [(dict(schema_version='0.1', status='welcome', **{field: [text]}), expected)
                 for field in ('wanted', 'boundaries') for text, expected in texts]
        script = """
const fs = require('fs');
const Ajv = require(process.argv[1]);
const {schema, cases} = JSON.parse(fs.readFileSync(0, 'utf8'));
const validate = new Ajv({strict: true}).compile(schema);
process.stdout.write(JSON.stringify(cases.map(value => validate(value))));
"""
        result = subprocess.run([node, '-e', script, module], input=json.dumps({
            'schema': schema, 'cases': [value for value, _ in cases]}), text=True,
            capture_output=True, check=True, timeout=15)
        for (value, expected), independent in zip(cases, json.loads(result.stdout), strict=True):
            with self.subTest(value=value):
                try:
                    tipjar.parse_manifest(json.dumps(value).encode())
                    parsed = True
                except core.ProtocolError:
                    parsed = False
                self.assertEqual((parsed, independent), (expected, expected))

    def test_invalid_bytes_and_shapes_fail_closed(self):
        invalid = [b'null', b'[]', b'{}', bytes([255]), RAW + b' ' * (16385 - len(RAW)),
                   b'{"schema_version":"0.1","status":"closed","status":"welcome"}',
                   b'{"schema_version":"0.1","status":NaN}', b'{' * 2000]
        values = [dict(schema_version='0.1', status=status) for status in ('WELCOME', None, 1, [])]
        values += [dict(schema_version='0.1', status='welcome', extra=True)]
        for field in ('wanted', 'boundaries'):
            for items in (None, 'text', [None], [''], [' \u2003'], ['same', 'same'], ['x' * 501],
                          list(map(str, range(17))), [chr(0)], [chr(31)], [chr(127)], [chr(0xd800)]):
                values.append(dict(schema_version='0.1', status='welcome', **{field: items}))
        invalid += [json.dumps(v).encode() for v in values]
        for raw in invalid:
            with self.subTest(raw=repr(raw[:90])), self.assertRaises(core.ProtocolError) as raised:
                tipjar.parse_manifest(raw)
            self.assertEqual(raised.exception.code, 'invalid_tipjar')
            self.assertLess(len(str(raised.exception)), 300)
        for version in ('999', None, 1):
            with self.subTest(version=version), self.assertRaises(core.ProtocolError) as raised:
                tipjar.parse_manifest(json.dumps(dict(schema_version=version, status='welcome')).encode())
            self.assertEqual(raised.exception.code, 'unsupported_tipjar_schema')


class PinnedReadTests(unittest.TestCase):
    def test_pin_and_no_tracker_resolution_or_owner_inheritance(self):
        client = Fake()
        result = tipjar.read_jar('acme/project', client)
        self.assertEqual(result['state'], 'welcome')
        self.assertTrue(result['complete'])
        self.assertEqual(result['commit'], COMMIT)
        self.assertEqual(result['sha256'], hashlib.sha256(RAW).hexdigest())
        self.assertEqual(result['blob_sha'], cache.blob_sha(RAW))
        self.assertEqual(len(client.calls), 4)
        self.assertEqual(client.calls[-1], f'repos/acme/project/contents/.tipjar.json?ref={COMMIT}')
        self.assertEqual(tipjar.inspect_jar, tipjar.read_jar)

    def test_absent_only_from_complete_tree_and_exact_root_case(self):
        for entries in ([], [{'path': '.TIPJAR.json', 'type': 'blob', 'mode': '100644', 'sha': 'c' * 40}],
                        [{'path': 'nested/.tipjar.json', 'type': 'blob', 'mode': '100644', 'sha': 'c' * 40}]):
            client = Fake(responses(entries=entries))
            result = tipjar.read_jar('acme/project', client)
            self.assertEqual(result['state'], 'undeclared')
            self.assertTrue(result['complete'])
            self.assertIsNone(result['sha256'])
            self.assertEqual(len(client.calls), 3)

    def test_malformed_tree_cannot_prove_absence(self):
        bad_entries = [[{}], [{'path': 'README', 'type': 'blob', 'mode': '100644', 'sha': 'bad'}],
                       [{'path': 'README', 'type': 'blob', 'sha': 'c' * 40}] * 2]
        for entries in bad_entries:
            self.assert_unknown(responses(entries=entries))
        for field, value in [('truncated', True), ('truncated', None), ('tree', None), ('sha', 'bad')]:
            data = responses(entries=[])
            data[f'repos/acme/project/git/trees/{TREE}?recursive=1'][field] = value
            self.assert_unknown(data)

    def assert_unknown(self, data):
        result = tipjar.read_jar('acme/project', Fake(data))
        self.assertEqual(result['state'], 'unknown')
        self.assertFalse(result['complete'])
        self.assertIsNone(result['manifest'])
        self.assertTrue(result['errors'])
        return result

    def test_wrong_jar_kind_mode_identity_and_content(self):
        for kind, mode in [('blob', '120000'), ('tree', '040000'), ('commit', '160000'), ('blob', None)]:
            self.assert_unknown(responses(entries=[{'path': '.tipjar.json', 'type': kind, 'mode': mode, 'sha': 'c' * 40}]))
        key = f'repos/acme/project/contents/.tipjar.json?ref={COMMIT}'
        for field, value in [('sha', 'c' * 40), ('type', 'symlink'), ('encoding', 'utf-8'),
                             ('content', '!'), ('size', True), ('size', 999), ('path', 'other')]:
            data = responses()
            data[key][field] = value
            self.assert_unknown(data)
        data = responses()
        data[key]['content'] = base64.b64encode(b'wrong bytes').decode()
        result = self.assert_unknown(data)
        self.assertEqual(result['sha256'], hashlib.sha256(b'wrong bytes').hexdigest())
        data[key] = core.ProtocolError('api_error', 'HTTP 404')
        self.assert_unknown(data)
        result = self.assert_unknown(responses(b'{"schema_version":"999","status":"welcome"}'))
        self.assertIsNotNone(result['sha256'])

    def test_metadata_commit_and_historical_validation(self):
        for field, value in [('full_name', 'other/repo'), ('default_branch', ''), ('default_branch', None)]:
            data = responses()
            data['repos/acme/project'][field] = value
            self.assert_unknown(data)
        data = responses()
        data['repos/acme/project/commits/main']['sha'] = 'bad'
        self.assert_unknown(data)
        client = Fake()
        result = tipjar.read_jar('acme/project', client, commit=COMMIT,
                                metadata=client.data['repos/acme/project'])
        self.assertEqual(result['state'], 'welcome')
        self.assertEqual(len(client.calls), 3)
        result = tipjar.read_jar('acme/project', Fake(), commit='main')
        self.assertFalse(result['complete'])

    def test_request_once_failure_never_falls_back_to_request(self):
        client = Fake()
        client.request_once = Mock(side_effect=core.ProtocolError('api_error', 'fail'))
        result = tipjar.read_jar('acme/project', client)
        self.assertFalse(result['complete'])
        self.assertEqual(client.calls, [])
        client.request_once.assert_called_once()
        self.assertIsNone(result['commit'])
        self.assertIsNone(result['default_branch'])

    def test_transient_failures_never_retry_jar_reads(self):
        data = responses()
        for fail_at in (None, 1, 2, 3, 4):
            calls = []
            def transport(argv, **kwargs):
                calls.append(argv)
                self.assertEqual(argv[:6], ['gh', 'api', '--hostname', 'github.com', '--method', 'GET'])
                if len(calls) == fail_at:
                    kwargs['stderr'].write(b'HTTP 503')
                    return types.SimpleNamespace(returncode=1)
                kwargs['stdout'].write(json.dumps(data[argv[-1]]).encode())
                return types.SimpleNamespace(returncode=0)
            with self.subTest(fail_at=fail_at), patch('subprocess.run', side_effect=transport), patch(
                    'time.sleep', side_effect=AssertionError('retried')), patch.object(cache, 'active', return_value=None):
                result = tipjar.read_jar('acme/project', core.GitHub())
            self.assertEqual(result['complete'], fail_at is None)
            self.assertEqual(len(calls), fail_at or 4)

    def test_same_declaration_compares_identity_state_and_exact_bytes(self):
        before = tipjar.read_jar('acme/project', Fake())
        self.assertTrue(tipjar.same_declaration(before, dict(before, commit='d' * 40)))
        for changes in ({'repository': 'other/repo'}, {'state': 'closed'}, {'sha256': '0' * 64}, {'complete': False}):
            self.assertFalse(tipjar.same_declaration(before, dict(before, **changes)))
        self.assertFalse(tipjar.same_declaration({}, {}))
        after = tipjar.read_jar('acme/project', Fake(responses(RAW + b' ')))
        self.assertFalse(tipjar.same_declaration(before, after))


class CanonicalTreeTests(unittest.TestCase):
    def client(self):
        data = responses()
        commit_endpoint = f'repos/acme/project/commits/{COMMIT}'
        data[commit_endpoint] = copy.deepcopy(data['repos/acme/project/commits/main'])
        commit_tree = f'repos/acme/project/git/trees/{COMMIT}?recursive=1'
        canonical_tree = f'repos/acme/project/git/trees/{TREE}?recursive=1'
        data[commit_tree] = copy.deepcopy(data[canonical_tree])
        # GitHub accepts a commit parameter here but echoes that parameter as sha.
        data[commit_tree]['sha'] = COMMIT
        return Fake(data)

    def test_default_and_historical_reads_query_the_commit_objects_canonical_tree(self):
        for historical, supplied_metadata in ((False, False), (True, False), (True, True)):
            client = self.client()
            options = {'commit': COMMIT} if historical else {}
            if supplied_metadata:
                options['metadata'] = client.data['repos/acme/project']
            with self.subTest(historical=historical, supplied_metadata=supplied_metadata):
                result = tipjar.read_jar('acme/project', client, **options)
                self.assertEqual((result['state'], result['complete']), ('welcome', True))
                expected = ([] if supplied_metadata else ['repos/acme/project']) + [
                    'repos/acme/project/commits/' + (COMMIT if historical else 'main'),
                    f'repos/acme/project/git/trees/{TREE}?recursive=1',
                    f'repos/acme/project/contents/.tipjar.json?ref={COMMIT}']
                self.assertEqual(client.calls, expected)
                self.assertLessEqual(len(client.calls), 4)

    def test_historical_commit_identity_mismatch_stops_before_tree(self):
        client = self.client()
        client.data[f'repos/acme/project/commits/{COMMIT}']['sha'] = 'd' * 40
        result = tipjar.read_jar('acme/project', client, commit=COMMIT)
        self.assertEqual((result['state'], result['complete']), ('unknown', False))
        self.assertFalse(any('/git/trees/' in call for call in client.calls))

    def test_canonical_tree_must_be_complete_and_match_exact_identity(self):
        for field, value in [('sha', None), ('sha', COMMIT), ('sha', 'd' * 40),
                             ('truncated', None), ('truncated', True), ('tree', None)]:
            client = self.client()
            client.data[f'repos/acme/project/git/trees/{TREE}?recursive=1'][field] = value
            with self.subTest(field=field, value=value):
                result = tipjar.read_jar('acme/project', client, commit=COMMIT)
                self.assertEqual((result['state'], result['complete']), ('unknown', False))
                self.assertFalse(any('/contents/' in call for call in client.calls))


class CacheTrustTests(unittest.TestCase):
    def test_cache_only_shortcuts_verified_content_and_rereads_live_tree(self):
        from tests.test_cache import gh, without_times
        with tempfile.TemporaryDirectory() as tmp:
            store = cache.Cache(str(pathlib.Path(tmp) / 'jar-cache'))
            self.addCleanup(store.close)
            fake, calls = Fake(), []
            with patch.object(cache, 'active', return_value=store), patch('subprocess.run', gh(fake, calls)):
                cold = tipjar.read_jar('acme/project', core.GitHub())
                self.assertEqual(len(calls), 4)
                calls.clear()
                warm = tipjar.read_jar('acme/project', core.GitHub())
                self.assertEqual(len(calls), 3)
                self.assertEqual(without_times(cold), without_times(warm))
                self.assertFalse(any('/contents/' in call for call in calls))
                # Corrupted bytes at the content-addressed path must be discarded.
                (pathlib.Path(tmp) / 'jar-cache' / ('blob-' + cache.blob_sha(RAW))).write_bytes(b'forged')
                calls.clear()
                self.assertTrue(tipjar.read_jar('acme/project', core.GitHub())['complete'])
                self.assertEqual(len(calls), 4)
                # An old verified cached jar cannot hide a live malformed tree.
                calls.clear()
                fake.data[f'repos/acme/project/git/trees/{TREE}?recursive=1']['truncated'] = True
                self.assertEqual(tipjar.read_jar('acme/project', core.GitHub())['state'], 'unknown')
                self.assertEqual(len(calls), 3)

    def test_malformed_or_mismatched_commit_cannot_enable_canonical_tree_cache_hit(self):
        for value in [None, {}, {'sha': COMMIT, 'commit': None},
                      {'sha': COMMIT, 'commit': {'tree': {'sha': None}}},
                      {'sha': 'd' * 40, 'commit': {'tree': {'sha': TREE}}}]:
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                store = cache.Cache(directory)
                self.addCleanup(store.close)
                data = responses()
                store.observe('repos/acme/project', data['repos/acme/project'])
                store.observe(f'repos/acme/project/commits/{COMMIT}', value)
                tree_endpoint = f'repos/acme/project/git/trees/{TREE}?recursive=1'
                store.observe(tree_endpoint, data[tree_endpoint])
                contents = f'repos/acme/project/contents/.tipjar.json?ref={COMMIT}'
                store.observe(contents, data[contents])
                self.assertIsNone(store.lookup(contents))

    def test_branch_advancement_after_pin_does_not_switch_content_ref(self):
        class Moving(Fake):
            def request(self, endpoint):
                value = super().request(endpoint)
                if '/commits/' in endpoint:
                    self.data[endpoint]['sha'] = 'd' * 40
                return value
        result = tipjar.read_jar('acme/project', Moving())
        self.assertEqual(result['commit'], COMMIT)
        self.assertEqual(result['state'], 'welcome')
