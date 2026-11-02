"""Field-shape fuzz: every consumed remote field rejects wrong types without crashing or claiming completeness."""
import unittest
from unittest.mock import patch

from agent_contribute import core, feedback, ownership
from tests import test_lifecycle
from tests.test_authorization import candidate_task, host_context
from tests.test_feedback import PRGitHub
from tests.test_ownership import NOW, TimelineGitHub

COMMON = [[], {}, True, -1]
BAD = {'text': COMMON + [None], 'text?': COMMON, 'enum': COMMON + [None, 'zz'], 'enum?': COMMON + ['zz'],
       'sha': COMMON + [None, 'zz'], 'sha?': COMMON + ['zz'], 'positive': COMMON + [None, 0, 'zz'],
       'positive?': COMMON + [0, 'zz'], 'bool': [[], {}, None, 1, 'zz'], 'user?': [[], {}, True, -1, 'zz'],
       'object': [None, [], 'zz', True], 'object?': [[], 'zz', True, -1], 'url': COMMON + [None, 'https://github.com/evil/repo/pull/999']}

FEEDBACK_FIELDS = [
    ('pr', ['number'], 'positive'), ('pr', ['html_url'], 'url'), ('pr', ['state'], 'enum'), ('pr', ['draft'], 'bool'),
    ('pr', ['head', 'ref'], 'text'), ('pr', ['base', 'ref'], 'text'), ('pr', ['base', 'repo'], 'object'),
    ('pr', ['base', 'repo', 'id'], 'positive'),
    ('reviews', [0, 'user'], 'user?'), ('reviews', [0, 'user', 'id'], 'positive'), ('reviews', [0, 'user', 'login'], 'text'),
    ('reviews', [0, 'author_association'], 'enum'), ('reviews', [0, 'state'], 'enum'),
    ('reviews', [0, 'commit_id'], 'sha?'), ('reviews', [0, 'submitted_at'], 'text?'), ('reviews', [0, 'body'], 'text?'),
    ('review_comments', [0, 'user'], 'user?'), ('review_comments', [0, 'author_association'], 'enum'),
    ('review_comments', [0, 'path'], 'text'), ('review_comments', [0, 'line'], 'positive?'),
    ('review_comments', [0, 'position'], 'positive?'), ('review_comments', [0, 'commit_id'], 'sha'),
    ('review_comments', [0, 'body'], 'text?'),
    ('issue_comments', [0, 'user'], 'user?'), ('issue_comments', [0, 'author_association'], 'enum'),
    ('issue_comments', [0, 'body'], 'text?'), ('issue_comments', [0, 'created_at'], 'text'),
    ('pages', [1, 0, 'id'], 'positive'), ('pages', [1, 0, 'name'], 'text'), ('pages', [1, 0, 'app'], 'object'),
    ('pages', [1, 0, 'app', 'id'], 'positive'), ('pages', [1, 0, 'app', 'slug'], 'text'),
    ('pages', [1, 0, 'head_sha'], 'sha'), ('pages', [1, 0, 'status'], 'enum'), ('pages', [1, 0, 'conclusion'], 'enum'),
    ('pages', [1, 0, 'html_url'], 'text?')]

OWNERSHIP_FIELDS = [
    ('timeline', [0, 'event'], 'text'), ('timeline', [0, 'source'], 'object'), ('timeline', [0, 'source', 'issue'], 'object'),
    ('timeline', [0, 'source', 'issue', 'number'], 'positive'),
    ('timeline', [0, 'source', 'issue', 'pull_request'], 'object?'),
    ('timeline', [0, 'source', 'issue', 'repository'], 'object'),
    ('timeline', [0, 'source', 'issue', 'repository', 'full_name'], 'enum'),
    ('timeline', [0, 'source', 'issue', 'repository', 'id'], 'positive'),
    ('timeline', [5, 'assignee'], 'user?'), ('timeline', [5, 'actor'], 'user?'), ('timeline', [5, 'created_at'], 'text'),
    ('timeline', [6, 'actor'], 'user?'), ('timeline', [6, 'created_at'], 'text'),
    ('timeline', [7, 'commit_id'], 'sha?'), ('timeline', [7, 'commit_url'], 'text?'),
    ('comments', [0, 'body'], 'text?'), ('comments', [0, 'user'], 'user?'), ('comments', [0, 'user', 'id'], 'positive'),
    ('comments', [0, 'author_association'], 'enum'), ('comments', [0, 'created_at'], 'text'),
    ('pulls', ['acme/photos/31', 'number'], 'positive'), ('pulls', ['acme/photos/31', 'html_url'], 'url'),
    ('pulls', ['acme/photos/31', 'state'], 'enum'), ('pulls', ['acme/photos/31', 'merged'], 'bool'),
    ('pulls', ['acme/photos/31', 'merged_at'], 'text'), ('pulls', ['acme/photos/31', 'closed_at'], 'text'),
    ('pulls', ['acme/photos/31', 'draft'], 'bool'), ('pulls', ['acme/photos/31', 'base', 'repo'], 'object'),
    ('pulls', ['acme/photos/31', 'base', 'repo', 'full_name'], 'enum'),
    ('pulls', ['acme/photos/31', 'base', 'repo', 'id'], 'positive')]


def mutate(client, attribute, path, value):
    target = getattr(client, attribute)
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


class RemoteShapeTests(unittest.TestCase):
    def fuzz(self, fields, factory, run):
        for attribute, path, kind in fields:
            for value in BAD[kind]:
                with self.subTest(field='.'.join(map(str, [attribute] + path)), value=value):
                    client = factory()
                    mutate(client, attribute, path, value)
                    result = run(client)  # must not raise
                    self.assertFalse(result['complete'], 'malformed data reported as complete')
                    self.assertTrue(result['errors'])

    def test_feedback_fields(self):
        self.fuzz(FEEDBACK_FIELDS, PRGitHub, lambda c: feedback.feedback('acme/photos#30', c))

    def test_ownership_fields(self):
        self.fuzz(OWNERSHIP_FIELDS, TimelineGitHub, lambda c: ownership.ownership_signals('acme/photos', 12, c, NOW))

    def test_legitimate_nulls_stay_complete(self):
        for attribute, path in [('reviews', [0, 'user']), ('reviews', [0, 'body']), ('reviews', [0, 'commit_id']),
                                ('review_comments', [0, 'line']), ('issue_comments', [0, 'body'])]:
            with self.subTest(field=path):
                client = PRGitHub()
                mutate(client, attribute, path, None)
                self.assertTrue(feedback.feedback('acme/photos#30', client)['complete'])
        for attribute, path in [('comments', [0, 'user']), ('comments', [0, 'body']), ('timeline', [5, 'assignee']),
                                ('timeline', [7, 'commit_id'])]:
            with self.subTest(field=path):
                client = TimelineGitHub()
                mutate(client, attribute, path, None)
                self.assertTrue(ownership.ownership_signals('acme/photos', 12, client, NOW)['complete'])

    def test_substituted_pull_request_cannot_claim_a_fix(self):
        client = TimelineGitHub()
        client.pulls['acme/photos/31'].update(number=999, html_url='https://github.com/evil/repo/pull/999',
                                              base={'repo': {'full_name': 'evil/repo', 'id': 101}})
        result = ownership.ownership_signals('acme/photos', 12, client, NOW)
        self.assertFalse(result['complete'])
        self.assertEqual(result['resolution_signals']['possibly_already_fixed'], [])
        self.assertEqual(result['resolution_signals']['status'], 'unknown')
        client = TimelineGitHub()
        client.pulls['acme/photos/31']['base']['repo']['id'] = 555  # same name, different repository identity
        self.assertFalse(ownership.ownership_signals('acme/photos', 12, client, NOW)['complete'])


class OverlapScanShapeTests(unittest.TestCase):
    # Only null means "empty"; any other non-string must not be scanned as empty text (R1-02).
    def pr(self, **fields):
        return dict({'id': 3101, 'number': 31, 'title': 'Separate work', 'body': None,
                     'html_url': 'https://github.com/acme/photos/pull/31', 'head': {'ref': 'separate'}}, **fields)

    def verify(self, pr):
        task, _ = candidate_task()
        client = test_lifecycle.IntegratedGitHub()
        client.prs = [pr]
        with patch.object(core.dt, 'datetime', test_lifecycle.Clock):
            return core.verify(task, client=client, host_context=host_context(task))

    def test_null_body_head_and_ref_stay_complete(self):
        for pr in (self.pr(), self.pr(head=None), self.pr(head={'ref': None})):
            with self.subTest(pr=pr):
                result = self.verify(pr)
                self.assertTrue(result['live_complete'], result['errors'])
                self.assertTrue(result['implementation_ready'], result['errors'])

    def test_false_valued_malformed_fields_block_schema_02_readiness(self):
        cases = [('body', value, 'pull request body') for value in ([], {}, False, 0)]
        cases += [('head', value, 'pull request head') for value in ([], False, 0, '')]
        cases += [('ref', value, 'pull request branch') for value in ([], {}, False, 0)]
        for field, value, description in cases:
            with self.subTest(field=field, value=value):
                pr = self.pr(head={'ref': value}) if field == 'ref' else self.pr(**{field: value})
                result = self.verify(pr)
                self.assertIn('Invalid GitHub ' + description, result['errors'])
                self.assertFalse(result['live_complete'])
                self.assertFalse(result['implementation_ready'])

    def test_index_rejects_false_valued_malformed_fields(self):
        for pr in (self.pr(body=[]), self.pr(head=0), self.pr(head={'ref': False})):
            with self.subTest(pr=pr), self.assertRaises(core.ProtocolError):
                core.index_prs([pr])


if __name__ == '__main__':
    unittest.main()
