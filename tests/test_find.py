"""Bounded search identities and independently verified public invitations."""
import copy
import json
import unittest
from unittest.mock import patch

from agent_contribute import core
from tests.test_tipjar import responses, COMMIT


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


if __name__ == '__main__':
    unittest.main()
