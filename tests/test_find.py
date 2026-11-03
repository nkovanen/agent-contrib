"""Bounded search identities and independently verified public invitations."""
import copy
import json
import pathlib
import unittest
from unittest.mock import patch

from agent_contribute import core
from tests.test_tipjar import responses, COMMIT, TREE


def hit(name='acme/project', repo_id=1, owner_id=2):
    return {'name': '.tipjar.json', 'path': '.tipjar.json', 'sha': 'c' * 40,
            'repository': {'id': repo_id, 'full_name': name, 'private': False,
                           'owner': {'id': owner_id, 'login': name.split('/')[0]}}}


def page(items=None, **kw):
    items = [hit()] if items is None else items
    return dict(total_count=len(items), incomplete_results=False, items=items, **kw)


class Fake:
    def __init__(self, search=None, data=None):
        self.search = page() if search is None else search
        self.data = responses() if data is None else data
        self.data['repos/acme/project'].update(id=1, owner={'id': 2, 'login': 'acme'},
                                               archived=False, disabled=False)
        self.calls = []

    def request_once(self, endpoint):
        self.calls.append(endpoint)
        value = self.search if endpoint.startswith('search/code?') else self.data[endpoint]
        if not endpoint.startswith('search/code?') and isinstance(value, list):
            value = value.pop(0)
        if isinstance(value, Exception):
            raise value
        return copy.deepcopy(value)

    def request(self, endpoint):
        raise AssertionError('retrying request used')


class SearchTests(unittest.TestCase):
    def find(self, client=None, **kw):
        from agent_contribute.find import find_jars
        return find_jars(client or Fake(), **kw)

    def test_fixed_query_and_owner_scope(self):
        c = Fake(search=page([]))
        r = self.find(c, owner='Acme')
        self.assertEqual(c.calls, ['search/code?q=filename%3A.tipjar.json+path%3A%2F+user%3AAcme&per_page=10&page=1'])
        self.assertEqual(r['search']['query'], 'filename:.tipjar.json path:/ user:Acme')
        self.assertTrue(r['complete'])
        self.assertFalse(r['coverage']['exhaustive'])

    def test_invalid_owner_has_zero_reads(self):
        for owner in ('', 'a b', 'a/repo', 'a user:x', 'é', 'a'*40, '-a', True):
            c = Fake()
            with self.subTest(owner=owner), self.assertRaises(core.ProtocolError) as e:
                self.find(c, owner=owner)
            self.assertEqual(e.exception.code, 'usage')
            self.assertEqual(c.calls, [])

    def test_malformed_envelopes_never_inspect(self):
        bad = [[], {}, dict(page(), total_count=True), dict(page(), total_count=-1),
               dict(page(), incomplete_results=0), dict(page(), items={}),
               dict(page(), total_count=0), dict(page(), items=[hit()]*11, total_count=11)]
        for field in ('total_count', 'incomplete_results', 'items'):
            value = page(); del value[field]; bad.append(value)
        for value in bad:
            c = Fake(search=value)
            r = self.find(c)
            self.assertFalse(r['complete'])
            self.assertEqual(r['observations'], [])
            self.assertIsNone(r['search']['total_count'])
            self.assertIsNone(r['search']['truncated'])
            self.assertEqual(len(c.calls), 1)

    def test_short_page_and_server_incomplete_keep_verified_findings(self):
        for changes in ({'total_count': 5}, {'incomplete_results': True}):
            r = self.find(Fake(search=dict(page(), **changes)))
            self.assertFalse(r['complete'])
            self.assertEqual(r['observations'][0]['disposition'], 'welcome')

    def test_strict_hit_shapes_never_welcome(self):
        bad = []
        for key, value in [('id', True), ('id', 0), ('full_name', 'bad/name/extra'),
                           ('private', None), ('owner', {}), ('owner', {'id': 2, 'login': 'other'})]:
            h = hit(); h['repository'][key] = value; bad.append(h)
        for key, value in [('sha', 'bad'), ('sha', True), ('repository', None)]:
            h = hit(); h[key] = value; bad.append(h)
        bad += [None, 'text']
        for h in bad:
            c = Fake(search=page([h])); r = self.find(c)
            self.assertFalse(r['complete'])
            self.assertEqual(r['observations'][0]['disposition'], 'unknown')
            self.assertIsNone(r['observations'][0]['repository'])
            self.assertEqual(len(c.calls), 1)

    def test_root_case_and_private_and_owner_filter_are_exclusions(self):
        for change in ({'path': 'dir/.tipjar.json'}, {'name': '.TIPJAR.json'}):
            r = self.find(Fake(search=page([dict(hit(), **change)])))
            self.assertTrue(r['complete']); self.assertEqual(r['observations'][0]['disposition'], 'excluded')
        h = hit(); h['repository']['private'] = True
        c = Fake(search=page([h])); r = self.find(c)
        self.assertIsNone(r['observations'][0]['repository'])
        self.assertNotIn('acme/project', json.dumps(r)); self.assertEqual(len(c.calls), 1)
        c = Fake(); r = self.find(c, owner='other')
        self.assertEqual(r['observations'][0]['disposition'], 'excluded'); self.assertEqual(len(c.calls), 1)

    def test_duplicate_conflicts_invalidate_entire_page_before_reads(self):
        for field, value in [('sha', 'd'*40), ('id', 3), ('full_name', 'acme/renamed'), ('owner_id', 8)]:
            h = hit()
            if field == 'sha': h[field] = value
            elif field == 'owner_id': h['repository']['owner']['id'] = value
            else: h['repository'][field] = value
            c = Fake(search=page([hit(), copy.deepcopy(hit()), h]))
            r = self.find(c)
            self.assertFalse(r['complete'])
            self.assertTrue(all(o['disposition'] == 'unknown' for o in r['observations']))
            self.assertEqual(len(c.calls), 1)
        c = Fake(search=page([hit(), hit()])); r = self.find(c)
        self.assertEqual(len(r['observations']), 1); self.assertEqual(len(c.calls), 6)

class VerificationTests(unittest.TestCase):
    find = SearchTests.find

    def test_stale_index_is_only_candidate_not_freshness_gate(self):
        for raw, entries, expected in [(b'{"schema_version":"0.1","status":"closed"}', None, 'closed'),
                                       (b'', [], 'undeclared')]:
            c = Fake(data=responses(raw, entries)); r = self.find(c)
            self.assertEqual(r['observations'][0]['disposition'], expected)
            self.assertTrue(r['complete']); self.assertEqual(len(c.calls), 4 if entries == [] else 5)
        r = self.find()
        self.assertEqual(r['observations'][0]['jar']['commit'], COMMIT)
        self.assertNotEqual(r['observations'][0]['jar']['blob_sha'], 'c'*40)

    def test_bad_jar_and_tree_never_select(self):
        fixtures = [responses(b'bad'), responses(b'{"schema_version":"999","status":"welcome"}'),
                    responses(entries=[{'path': '.tipjar.json', 'sha': 'd'*40, 'type': 'blob', 'mode': '120000'}])]
        for kind in ('truncated', 'hash', 'missing'):
            data = responses()
            if kind == 'truncated': data[f'repos/acme/project/git/trees/{TREE}?recursive=1']['truncated'] = True
            elif kind == 'hash': data[f'repos/acme/project/contents/.tipjar.json?ref={COMMIT}']['sha'] = 'f'*40
            else: data[f'repos/acme/project/contents/.tipjar.json?ref={COMMIT}'] = core.ProtocolError('api_error', 'PRIVATE SECRET')
            fixtures.append(data)
        for data in fixtures:
            r = self.find(Fake(data=data))
            self.assertFalse(r['complete']); self.assertEqual(r['observations'][0]['disposition'], 'unknown')
            self.assertNotIn('PRIVATE SECRET', json.dumps(r))

    def test_metadata_shapes_and_redirect_identity_changes_fail_closed(self):
        for field, value in [('id', True), ('id', 3), ('full_name', 'acme/moved'),
                             ('owner', {'id': 3, 'login': 'acme'}), ('owner', {'id': 2, 'login': 'moved'}),
                             ('private', None), ('archived', 0), ('disabled', None),
                             ('visibility', None), ('default_branch', '\n'), ('default_branch', None)]:
            c = Fake(); c.data['repos/acme/project'][field] = value
            r = self.find(c)
            self.assertEqual(r['observations'][0]['disposition'], 'unknown', (field, value, r))
            self.assertEqual(len(c.calls), 2)
        c = Fake(); del c.data['repos/acme/project']['visibility']
        self.assertFalse(self.find(c)['complete'])

    def test_initial_and_final_eligibility_and_private_suppression(self):
        for final in (False, True):
            for field, value, expected in [('private', True, 'private'), ('visibility', 'private', 'private'),
                                           ('archived', True, 'archived'), ('disabled', True, 'disabled')]:
                c = Fake(); before = copy.deepcopy(c.data['repos/acme/project'])
                after = dict(before, **{field: value})
                c.data['repos/acme/project'] = [before, after] if final else after
                r = self.find(c); obs = r['observations'][0]
                self.assertTrue(r['complete']); self.assertEqual(obs['reason'], expected)
                self.assertEqual(obs['disposition'], 'excluded'); self.assertIsNone(obs['jar'])
                if expected == 'private': self.assertNotIn('acme/project', json.dumps(r))

    def test_final_identity_branch_changes_or_failure_discard_welcome(self):
        for change in ({'id': 3}, {'full_name': 'acme/new'}, {'owner': {'id': 3, 'login': 'acme'}},
                       {'default_branch': 'new'}, core.ProtocolError('api_error', 'secret')):
            c = Fake(); before = copy.deepcopy(c.data['repos/acme/project'])
            c.data['repos/acme/project'] = [before, change if isinstance(change, Exception) else dict(before, **change)]
            r = self.find(c)
            self.assertFalse(r['complete']); self.assertIsNone(r['observations'][0]['jar'])
            self.assertEqual(r['observations'][0]['disposition'], 'unknown')


class TransportTests(unittest.TestCase):
    def run_transport(self, callback, *, owner=None, client=None):
        from agent_contribute.find import find_jars
        endpoints = []
        def run(argv, **kwargs):
            self.assertEqual(argv[:6], ['gh', 'api', '--hostname', 'github.com', '--method', 'GET'])
            self.assertEqual(kwargs['timeout'], 30); self.assertFalse(kwargs['shell'])
            endpoint = argv[-1]; endpoints.append(endpoint)
            value = callback(endpoint, len(endpoints))
            if isinstance(value, Exception):
                kwargs['stderr'].write(b'HTTP 503 SECRET'); return type('Result', (), {'returncode': 1})()
            kwargs['stdout'].write(json.dumps(value).encode())
            return type('Result', (), {'returncode': 0})()
        with patch('subprocess.run', side_effect=run), patch('time.sleep', side_effect=AssertionError('retry')):
            result = find_jars(client, owner=owner)
        return result, endpoints

    @staticmethod
    def batch():
        items, data = [], {}
        for i in range(10):
            name = f'acme/r{i}'
            items.append(hit(name, i+1))
            fixture = responses()
            fixture['repos/acme/project'].update(id=i+1, owner={'id': 2, 'login': 'acme'}, archived=False, disabled=False,
                                                   full_name=name)
            data.update({endpoint.replace('acme/project', name): value for endpoint, value in fixture.items()})
        return page(items), data

    def test_ten_welcomes_are_51_gh_invocations(self):
        search, data = self.batch()
        r, calls = self.run_transport(lambda e, _: search if e.startswith('search/code?') else data[e])
        self.assertEqual(len(calls), 51); self.assertEqual(r['requests'], {'search': 1, 'core': 50})
        self.assertTrue(r['complete']); self.assertEqual(len(r['observations']), 10)
        self.assertTrue(all(o['disposition'] == 'welcome' for o in r['observations']))
        self.assertTrue(all('/issues' not in e and '/pulls' not in e and 'parent' not in e for e in calls))

    def test_errors_at_every_read_position_never_retry_or_backfill(self):
        search, data = self.batch()
        for position in range(1, 7):
            r, calls = self.run_transport(lambda e, n: core.ProtocolError('api_error', 'secret') if n == position else
                                         search if e.startswith('search/code?') else data[e])
            self.assertFalse(r['complete']); self.assertLessEqual(len(calls), 51)
            self.assertEqual(sum(r['requests'].values()), len(calls))
            self.assertNotIn('SECRET', json.dumps(r))

    def test_uncached_library_reads_ignore_seeded_valid_and_forged_cache(self):
        import tempfile
        from agent_contribute import cache
        search, data = self.batch()
        with tempfile.TemporaryDirectory() as directory:
            cache.configure(True, directory)
            store = cache.active()
            try:
                for endpoint, value in data.items(): store.observe(endpoint, value)
                # A seeded blob must not mask a failing live contents read.
                r, calls = self.run_transport(lambda e, _: core.ProtocolError('api_error', 'no contents') if '/contents/' in e else
                                             search if e.startswith('search/code?') else data[e])
                self.assertFalse(r['complete']); self.assertEqual(sum('/contents/' in e for e in calls), 10)
                self.assertEqual(r['requests'], {'search': 1, 'core': 40})
                self.assertIs(cache.active(), store)
                # Neither valid nor forged disk bytes may satisfy this command.
                for path in pathlib.Path(directory).glob('blob-*'):
                    path.write_bytes(b'forged welcome')
                client = core.GitHub()
                with patch.object(store, 'lookup', side_effect=AssertionError('cache consulted')):
                    r, calls = self.run_transport(lambda e, _: search if e.startswith('search/code?') else data[e],
                                                 client=client)
                self.assertTrue(r['complete']); self.assertEqual(len(calls), 51)
                self.assertTrue(client.use_cache)
            finally: cache.configure(False)

class BoundaryReviewTests(unittest.TestCase):
    find = SearchTests.find

    def test_malformed_duplicate_identity_cannot_leave_a_selectable_sibling(self):
        for change in ({'owner': {'id': False, 'login': 'acme'}}, {'id': True}, {'full_name': None}):
            bad = hit(); bad['repository'].update(change)
            c = Fake(search=page([hit(), bad]))
            r = self.find(c)
            self.assertFalse(r['complete'])
            self.assertFalse(any(o['disposition'] == 'welcome' for o in r['observations']))
            self.assertEqual(len(c.calls), 1)

    def test_owner_login_is_ascii_identity_not_unicode_casefold_alias(self):
        h = hit('s/project'); h['repository']['owner']['login'] = '\u017f'
        c = Fake(search=page([h]))
        r = self.find(c)
        self.assertEqual(r['observations'][0]['disposition'], 'unknown')
        self.assertIsNone(r['observations'][0]['repository']); self.assertEqual(len(c.calls), 1)

    def test_failed_search_provenance_is_null_not_a_fabricated_empty_page(self):
        r = self.find(Fake(search={}))
        for field in ('total_count', 'incomplete_results', 'returned_count', 'truncated', 'short_page'):
            self.assertIsNone(r['search'][field])

    def test_unusable_branch_refs_never_reach_reader(self):
        for branch in ('a b', 'a..b', 'a.lock', '.hidden', 'a/', 'a//b', '@', 'a@{b', 'a?b', 'a\\b'):
            c = Fake(); c.data['repos/acme/project']['default_branch'] = branch
            r = self.find(c)
            self.assertEqual(r['observations'][0]['disposition'], 'unknown')
            self.assertEqual(len(c.calls), 2)

    def test_returned_urls_and_parent_never_become_endpoints(self):
        h = hit(); h.update(url='https://evil.invalid/run', html_url='https://evil.invalid/',
                            text_matches=[{'fragment': 'welcome'}])
        h['repository'].update(url='https://evil.invalid/repo')
        c = Fake(search=page([h])); r = self.find(c)
        self.assertEqual(r['observations'][0]['disposition'], 'welcome')
        self.assertTrue(all(e.startswith(('search/code?', 'repos/acme/project')) for e in c.calls))
        self.assertNotIn('evil.invalid', json.dumps(r))

    def test_other_verified_findings_survive_unknowns_in_partial_batch(self):
        r = self.find(Fake(search=page([hit(), None])))
        self.assertFalse(r['complete'])
        self.assertEqual([o['disposition'] for o in r['observations']], ['welcome', 'unknown'])


if __name__ == '__main__':
    unittest.main()
