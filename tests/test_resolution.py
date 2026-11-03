"""Behavior regressions for tracker resolution without execution authority."""
import copy
import io
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from agent_contribute import core
from agent_contribute.cli import main
from tests.test_protocol import FakeGitHub, ready_contract

POLICY = {'schema_version': '0.1', 'agent_approved_labels': ['agent-ok'],
          'label_authority': 'repository-label-permission'}


class RepositoryGitHub:
    """Replace only GitHub GETs, with distinct source and target fixtures."""
    def __init__(self):
        self.metadata = {
            'acme/photos': {'full_name': 'acme/photos', 'default_branch': 'main',
                            'fork': False, 'has_issues': True},
            'person/photos': {'full_name': 'person/photos', 'default_branch': 'main',
                              'fork': True, 'has_issues': False,
                              'parent': {'full_name': 'acme/photos'}}}
        self.repos = {'acme/photos': FakeGitHub(POLICY, ['agent-ok']),
                      'person/photos': FakeGitHub(None, ['agent-ok'])}
        self.failed = set()
        self.overrides = {}
        self.calls = []

    def request_once(self, endpoint):
        result = self.request(endpoint)
        if '/git/trees/' in endpoint and isinstance(result, dict):
            result = __import__('copy').deepcopy(result)
            result.setdefault('sha', 'c' * 40)
            for entry in result.get('tree', []):
                entry.setdefault('sha', 'b' * 40)
                entry.setdefault('mode', '100644')
        return result

    def request(self, endpoint):
        self.calls.append(endpoint)
        if endpoint in self.failed:
            raise core.ProtocolError('api_error', 'GitHub read failed')
        if endpoint in self.overrides:
            return copy.deepcopy(self.overrides[endpoint])
        parts = endpoint.split('/')
        repo = '/'.join(parts[1:3])
        if repo.split('?')[0] not in self.metadata:  # e.g. an owner .github repository read by the policy report
            missing = core.ProtocolError('api_error', 'GitHub GET found nothing (HTTP 404)')
            missing.http_status = 404
            raise missing
        if len(parts) == 3:
            return copy.deepcopy(self.metadata[repo])
        result = self.repos[repo].request(endpoint)
        if isinstance(result, dict) and 'html_url' in result:
            result['html_url'] = f'https://github.com/{repo}/issues/12'
        return result


def pr(repo, number, body, title='Unrelated work'):
    return {'number': number, 'title': title, 'body': body, 'draft': True,
            'html_url': f'https://github.com/{repo}/pull/{number}', 'head': {'ref': 'topic'}}


class ResolutionTests(unittest.TestCase):
    def assert_context(self, result, source='acme/photos', requested='person/photos'):
        self.assertEqual(result.get('requested_repository'), requested)
        self.assertEqual(result.get('issue_source_repository'), source)
        self.assertEqual(result.get('proposed_target_repository'), 'person/photos')
        self.assertTrue(result.get('resolution_provenance'))

    def test_disabled_fork_discover_inspect_prepare_keep_source_and_proposed_target(self):
        # Losing requested identity must break the reference and pending target checks.
        client = RepositoryGitHub()
        found = core.discover('person/photos', client)
        self.assert_context(found)
        self.assertTrue(found['complete'])
        self.assertEqual(found['issues'][0]['reference'], 'person/photos#12')
        self.assertEqual(found['issues'][0]['issue_url'], 'https://github.com/acme/photos/issues/12')
        inspected = core.inspect_issue(found['issues'][0]['reference'], client)
        self.assert_context(inspected)
        self.assertEqual(inspected['reference'], 'person/photos#12')
        self.assertEqual(inspected['source']['repository'], 'acme/photos')
        self.assertEqual(inspected['approval']['status'], 'approved')
        task = core.prepare(inspected)
        self.assertEqual(core.validate_contract(task), [])
        self.assertEqual(task['source']['repository'], 'acme/photos')
        self.assertEqual(task['execution'], {'mode': 'pending', 'target_repository': 'person/photos',
                                           'authorized_by': '', 'authorization_evidence': ''})
        checked = core.verify(task, client=client)
        self.assert_context(checked, requested=None)
        self.assertEqual(checked['approval']['status'], 'approved')
        self.assertFalse(checked['execution_ready'])
        self.assertFalse(checked['upstream_submission_ready'])

    def test_ordinary_and_enabled_issue_fork_use_own_tracker(self):
        for requested in ('acme/photos', 'person/photos'):
            with self.subTest(requested=requested):
                client = RepositoryGitHub()
                client.metadata['person/photos']['has_issues'] = True
                inspected = core.inspect_issue(requested + '#12', client)
                self.assertEqual(inspected.get('issue_source_repository'), requested)
                self.assertEqual(inspected['source']['repository'], requested)
                self.assertEqual(inspected['approval']['status'],
                                 'approved' if requested == 'acme/photos' else 'candidate')

    def test_source_policy_and_instructions_are_not_taken_from_fork(self):
        client = RepositoryGitHub()
        client.repos['acme/photos'].policy = None
        client.repos['person/photos'].policy = POLICY
        result = core.inspect_issue('person/photos#12', client)
        self.assertEqual(result['approval']['status'], 'candidate')
        self.assertTrue(any(x.startswith('repos/acme/photos/contents/') for x in client.calls))
        self.assertFalse(any(x.startswith('repos/person/photos/contents/') for x in client.calls))

    def test_bad_parent_or_metadata_never_guesses_a_source(self):
        for change in ({'parent': None}, {'parent': {}}, {'parent': {'full_name': '../bad'}},
                       {'parent': {'full_name': 'person/photos'}}, {'fork': None}, {'has_issues': None}):
            with self.subTest(change=change):
                client = RepositoryGitHub()
                client.metadata['person/photos'].update(change)
                for action in (core.discover, lambda repo, api: core.inspect_issue(repo + '#12', api)):
                    result = action('person/photos', client)
                    self.assert_context(result, source=None)
                    self.assertFalse(result['complete'])
                    self.assertTrue(result['errors'])

    def test_parent_without_issue_tracker_is_not_followed_again(self):
        client = RepositoryGitHub()
        client.metadata['acme/photos'].update(fork=True, has_issues=False,
                                             parent={'full_name': 'other/photos'})
        result = core.discover('person/photos', client)
        self.assert_context(result, source=None)
        self.assertFalse(result['complete'])
        self.assertFalse(any('other/photos' in x for x in client.calls))

    def test_requested_parent_and_issue_api_errors_preserve_context(self):
        for endpoint, source in [('repos/person/photos', None), ('repos/acme/photos', None),
                                 ('repos/acme/photos/issues/12', 'acme/photos'),
                                 ('repos/acme/photos/commits/main', 'acme/photos')]:
            with self.subTest(endpoint=endpoint):
                client = RepositoryGitHub()
                client.failed.add(endpoint)
                result = core.inspect_issue('person/photos#12', client)
                self.assert_context(result, source)
                self.assertFalse(result['complete'])
                self.assertTrue(result['errors'])

    def test_source_and_target_open_pr_overlaps_are_both_retained(self):
        client = RepositoryGitHub()
        client.repos['acme/photos'].prs = [pr('acme/photos', 30, 'Fixes #12')]
        client.repos['person/photos'].prs = [pr('person/photos', 2, 'Fixes acme/photos#12')]
        result = core.inspect_issue('person/photos#12', client)
        self.assertEqual({x['url'] for x in result['duplicates']},
                         {'https://github.com/acme/photos/pull/30', 'https://github.com/person/photos/pull/2'})
        task = core.prepare(result)
        self.assertEqual(core.validate_contract(task), [])
        self.assertEqual(len(task['discovery']['duplicate_prs']), 2)

    def test_bare_fork_pr_reference_is_relative_to_its_own_repository(self):
        for body, matches in [('Fixes #12', False), ('Fixes other/photos#12', False),
                              ('Fixes person/photos#12', False), ('Fixes acme/photos#12', True),
                              ('https://github.com/acme/photos/issues/12', True)]:
            with self.subTest(body=body):
                client = RepositoryGitHub()
                client.repos['person/photos'].prs = [pr('person/photos', 2, body)]
                result = core.inspect_issue('person/photos#12', client)
                self.assertEqual(bool(result['duplicates']), matches)

    def test_verify_rechecks_target_overlap_even_when_saved_discovery_is_clear(self):
        task, _ = ready_contract()
        task['execution'].update(mode='fork-experiment', target_repository='person/photos')
        client = RepositoryGitHub()
        client.repos['person/photos'].prs = [pr('person/photos', 2, 'Fixes acme/photos#12')]
        result = core.verify(task, client=client)
        self.assert_context(result, requested=None)
        self.assertFalse(result['execution_ready'])
        self.assertIn('https://github.com/person/photos/pull/2', [x['url'] for x in result['duplicates']])

    def test_incomplete_issue_source_or_target_pages_block_all_readiness(self):
        for repo, listing in [('acme/photos', 'issues?state=open'),
                              ('acme/photos', 'pulls?state=open'),
                              ('person/photos', 'pulls?state=open')]:
            with self.subTest(repo=repo, listing=listing):
                client = RepositoryGitHub()
                endpoint = f'repos/{repo}/{listing}'
                if listing.startswith('issues'):
                    client.overrides[endpoint + '&per_page=100&page=1'] = [
                        dict(client.repos[repo].request('repos/acme/photos/issues/12'), number=n)
                        for n in range(1, 101)]
                else:
                    client.overrides[endpoint + '&per_page=100&page=1'] = [
                        pr(repo, n, '') for n in range(1, 101)]
                client.failed.add(endpoint + '&per_page=100&page=2')
                found = core.discover('person/photos', client)
                self.assert_context(found)
                self.assertFalse(found['complete'])
                self.assertTrue(found['errors'])
                if listing.startswith('pulls'):
                    task = core.prepare(core.inspect_issue('person/photos#12', client))
                    checked = core.verify(task, client=client)
                    self.assertFalse(checked['live_complete'])
                    self.assertFalse(checked['execution_ready'])

    def test_cli_prepare_wrapper_keeps_resolution_and_failure_does_not_write_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            for failure in (False, True):
                client = RepositoryGitHub()
                if failure:
                    client.failed.add('repos/acme/photos')
                output = io.StringIO()
                destination = pathlib.Path(tmp, str(failure) + '.json')
                with patch('agent_contribute.core.GitHub', return_value=client), patch('sys.stdout', output):
                    status = main(['prepare', 'person/photos#12', '--output', str(destination)])
                result = json.loads(output.getvalue())
                self.assert_context(result, None if failure else 'acme/photos')
                self.assertEqual(status, 1 if failure else 0)
                self.assertEqual(destination.exists(), not failure)
                if not failure:
                    self.assertEqual(result['contract']['execution']['target_repository'], 'person/photos')

    def test_fork_execution_rejects_unrelated_target_and_unknown_parent(self):
        # A different repository name alone is not a verified fork relationship.
        for change in ({'fork': False}, {'parent': None}, {'parent': {}},
                       {'parent': {'full_name': 'other/photos'}},
                       {'parent': {'full_name': '../bad'}}):
            with self.subTest(change=change):
                task, _ = ready_contract()
                task['execution'].update(mode='fork-experiment', target_repository='person/photos')
                client = RepositoryGitHub()
                client.metadata['person/photos'].update(change)
                result = core.verify(task, client=client)
                self.assertFalse(result['execution_ready'])
                self.assertTrue(any('fork' in error.lower() for error in result['errors']))

    def test_target_metadata_and_pr_api_errors_block_fork_execution(self):
        for endpoint in ('repos/person/photos', 'repos/person/photos/pulls?state=open&per_page=100&page=1'):
            with self.subTest(endpoint=endpoint):
                task, _ = ready_contract()
                task['execution'].update(mode='fork-experiment', target_repository='person/photos')
                client = RepositoryGitHub()
                client.failed.add(endpoint)
                result = core.verify(task, client=client)
                self.assert_context(result, requested=None)
                self.assertFalse(result['execution_ready'])
                self.assertFalse(result['live_complete'])

    def test_approved_source_does_not_authorize_pending_fork_execution(self):
        task, _ = ready_contract()
        task['execution'].update(mode='pending', target_repository='person/photos',
                                 authorized_by='', authorization_evidence='')
        result = core.verify(task, client=RepositoryGitHub())
        self.assertEqual(result['approval']['status'], 'approved')
        self.assertFalse(result['execution_ready'])
        self.assertFalse(result['upstream_submission_ready'])
        task['execution'].update(mode='fork-experiment', authorized_by='human',
                                 authorization_evidence='Explicit local fork experiment')
        result = core.verify(task, client=RepositoryGitHub())
        self.assertTrue(result['execution_ready'])
        self.assertFalse(result['upstream_submission_ready'])

    def test_missing_flags_moved_identity_and_nonfork_disabled_tracker_fail_closed(self):
        cases = [dict(full_name='elsewhere/photos', fork=True, has_issues=False),
                 dict(full_name='person/photos', has_issues=False),
                 dict(full_name='person/photos', fork=True),
                 dict(full_name='person/photos', fork=1, has_issues=False),
                 dict(full_name='person/photos', fork=True, has_issues=0),
                 dict(full_name='person/photos', fork=False, has_issues=False)]
        for metadata in cases:
            with self.subTest(metadata=metadata):
                client = RepositoryGitHub()
                client.metadata['person/photos'] = metadata
                result = core.discover('person/photos', client)
                self.assert_context(result, None)
                self.assertFalse(result['complete'])

    def test_malformed_target_pr_leaves_inspection_and_verification_incomplete(self):
        client = RepositoryGitHub()
        client.repos['person/photos'].prs = [{'number': 2, 'title': 'Work', 'html_url': None}]
        inspected = core.inspect_issue('person/photos#12', client)
        self.assertFalse(inspected['complete'])
        self.assertEqual(inspected['duplicate_scan'], 'unknown')
        task, _ = ready_contract()
        task['execution'].update(mode='fork-experiment', target_repository='person/photos')
        self.assertFalse(core.verify(task, client=client)['execution_ready'])

    def test_target_only_overlap_lowers_inspect_success_likelihood(self):
        # Reusing the source-only ranking would hide a newly detected fork overlap.
        client = RepositoryGitHub()
        issue = client.repos['acme/photos'].request('repos/acme/photos/issues/12')
        issue['body'] = ('Thumbnail dimensions can exceed the supported buffer bounds. '
                         'Reject invalid dimensions and preserve the normal thumbnail path, '
                         'with a focused malformed-input regression covering the rejection.')
        client.overrides['repos/acme/photos/issues/12'] = issue
        clear = core.inspect_issue('person/photos#12', client)
        self.assertEqual(clear['ranking']['success_likelihood']['value'], 'unknown')
        client.repos['person/photos'].prs = [pr('person/photos', 2, 'Fixes acme/photos#12')]
        overlapped = core.inspect_issue('person/photos#12', client)
        self.assertTrue(overlapped['complete'])
        self.assertEqual([item['url'] for item in overlapped['duplicates']],
                         ['https://github.com/person/photos/pull/2'])
        self.assertEqual(overlapped['ranking']['success_likelihood']['value'], 'low')

    def test_empty_issue_descriptions_discover_without_crashing(self):
        # Raw null bodies must be normalized before any ranking or overlap parser.
        for requested in ('acme/photos', 'person/photos'):
            for body in (None, ''):
                with self.subTest(requested=requested, body=body):
                    client = RepositoryGitHub()
                    issue = client.repos['acme/photos'].request('repos/acme/photos/issues/12')
                    issue['body'] = body
                    client.overrides['repos/acme/photos/issues?state=open&per_page=100&page=1'] = [issue]
                    output = io.StringIO()
                    with patch('agent_contribute.core.GitHub', return_value=client), patch('sys.stdout', output):
                        status = main(['discover', requested])
                    result = json.loads(output.getvalue())
                    self.assertEqual(status, 0)
                    self.assertTrue(result['complete'])
                    self.assertEqual(result['issues'][0]['reference'], requested + '#12')
                    self.assertEqual(result['issues'][0]['ranking']['ambiguity']['value'], 'high')

    def test_ordinary_and_enabled_issue_fork_drafts_leave_execution_target_blank(self):
        # Only a resolved different source justifies proposing the requested fork in a task.
        for requested in ('acme/photos', 'person/photos'):
            with self.subTest(requested=requested):
                client = RepositoryGitHub()
                client.metadata['person/photos']['has_issues'] = True
                inspected = core.inspect_issue(requested + '#12', client)
                self.assertEqual(inspected['proposed_target_repository'], requested)
                task = core.prepare(inspected)
                self.assertEqual(task['execution'], {'mode': 'pending', 'target_repository': '',
                                                    'authorized_by': '', 'authorization_evidence': ''})

    def test_verify_does_not_invent_original_request_from_contract_target(self):
        # Schema 0.1 stores source/target roles, not the original user's repository spelling.
        for target in ('acme/photos', 'person/photos', ''):
            with self.subTest(target=target):
                task, _ = ready_contract()
                task['execution'].update(target_repository=target)
                result = core.verify(task, client=RepositoryGitHub())
                self.assertIsNone(result['requested_repository'])
                self.assertEqual(result['issue_source_repository'], 'acme/photos')
                self.assertEqual(result['proposed_target_repository'], target)
                self.assertEqual(result['resolution_provenance']['requested_repository'],
                                 'original request not stored in schema 0.1')
