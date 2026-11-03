"""Policy inventory identity for unread candidates and owner lookups (RP-28, RP-29)."""
import subprocess
import unittest
from unittest.mock import patch

from agent_contribute import core, policy
from tests.test_policy import PolicyGitHub, SOURCE_COMMIT
from tests.test_policy_drift import VersionedGitHub, reviewed, run, write

import os


def not_found():
    exc = core.ProtocolError('api_error', 'GitHub GET found nothing (HTTP 404): the repository, issue or path does not '
                                          'exist or is not visible to this gh account')
    exc.http_status = 404
    return exc


class OwnerGitHub(VersionedGitHub):
    """owner: 'absent' (HTTP 404), 'error' (an operational failure) or a dict of owner .github files."""
    def __init__(self, *args, owner='absent', **kwargs):
        super().__init__(*args, **kwargs)
        self.owner = owner

    def request(self, endpoint):
        path, _, query = endpoint.partition('?')
        if path.startswith('repos/acme/.github'):
            self.calls.append(endpoint)
            if self.owner == 'absent':
                raise not_found()
            if self.owner == 'error':
                raise core.ProtocolError('api_error', 'GitHub GET failed; check gh auth, access and rate limits')
            client = PolicyGitHub({}, self.owner)
            return client.request(endpoint.replace('repos/acme/.github', 'repos/acme/.github'))
        return super().request(endpoint)


class UnreadCandidateTests(unittest.TestCase):
    """RP-28: an edit to an inventoried but unread candidate changes the inventory and is drift."""
    def check(self, before, after, reason):
        client = VersionedGitHub(files=before)
        task, recorded = reviewed(client)
        path = write(task)
        self.addCleanup(os.unlink, path)
        client.advance(after)
        code, result = run(client, 'drift', path, '--policy-sha256', recorded)
        self.assertEqual(code, 1, result)
        report = result['repository_policy_drift']
        self.assertIs(report['policy_drifted'], True)
        self.assertIs(result['complete'], True)
        changed = {item['what']: item for item in report['changed']}
        self.assertIn('AI_POLICY.' + reason[0], changed)
        item = changed['AI_POLICY.' + reason[0]]
        self.assertEqual(item['stored']['state'], 'unassessed: ' + reason[1])
        self.assertNotEqual(item['stored']['fingerprint'], item['current']['fingerprint'])

    def test_an_edited_unsupported_format_policy_is_drift(self):
        self.check({'AI_POLICY.adoc': 'AI welcome.'}, {'AI_POLICY.adoc': 'AI forbidden.'}, ('adoc', 'unsupported format'))

    def test_an_edited_oversized_policy_is_drift(self):
        big = 'x' * (policy.MAX_FILE_BYTES + 1)
        self.check({'AI_POLICY.md': big}, {'AI_POLICY.md': big + 'No AI.'}, ('md', 'exceeds 200 kB'))

    def test_unread_entries_carry_their_pinned_blob(self):
        rp = policy.report('acme/photos', SOURCE_COMMIT, [], PolicyGitHub({'AI_POLICY.pdf': '%PDF'}),
                           default_branch='main')
        entry = next(u for u in rp['unassessed'] if u['what'] == 'AI_POLICY.pdf')
        self.assertRegex(entry['blob_sha'], '^[0-9a-f]{40}$')
        with patch.object(policy, 'MAX_SOURCE_FILES', 0):
            rp = policy.report('acme/photos', SOURCE_COMMIT, [], PolicyGitHub({'AI_POLICY.md': 'x'}),
                               default_branch='main')
        self.assertRegex(rp['omitted_sources'][0]['blob_sha'], '^[0-9a-f]{40}$')


class OwnerLookupTests(unittest.TestCase):
    """RP-29: the owner .github lookup outcome is part of the inventory; operational failures are unknown."""
    def test_lookup_outcomes_are_reported_and_classified(self):
        for owner, status, hides in (('absent', 'not_found_or_inaccessible', False), ('error', 'unavailable', True),
                                     ({'CONTRIBUTING.md': 'x'}, 'read', False)):
            with self.subTest(status):
                client = OwnerGitHub(owner=owner)
                rp = policy.for_inspected(core.inspect_issue('acme/photos#12', client), client)
                self.assertEqual(rp['owner_lookup'], {'repository': 'acme/.github', 'status': status})
                self.assertIs(rp['limits_hide_sources'], hides)

    def drift_after(self, before, after):
        client = OwnerGitHub(owner=before)
        task, recorded = reviewed(client)
        path = write(task)
        self.addCleanup(os.unlink, path)
        client.owner = after
        return run(client, 'drift', path, '--policy-sha256', recorded)

    def test_404_becoming_an_operational_failure_is_incomplete(self):
        code, result = self.drift_after('absent', 'error')
        self.assertEqual(code, 1)
        self.assertIs(result['complete'], False)
        self.assertIsNone(result['repository_policy_drift']['policy_drifted'])

    def test_readable_owner_becoming_unavailable_is_drift(self):
        code, result = self.drift_after({'CONTRIBUTING.md': 'No AI.'}, 'absent')
        self.assertEqual(code, 1)
        self.assertIs(result['repository_policy_drift']['policy_drifted'], True)

    def test_core_404_errors_carry_their_status(self):
        def failure(argv, **kwargs):
            kwargs['stderr'].write(b'gh: Not Found (HTTP 404)')
            return subprocess.CompletedProcess(argv, 1)
        with patch('subprocess.run', side_effect=failure), self.assertRaises(core.ProtocolError) as raised:
            core.GitHub().request('repos/acme/.github')
        self.assertEqual(raised.exception.http_status, 404)
        def other(argv, **kwargs):
            kwargs['stderr'].write(b'gh: Server Error (HTTP 418)')
            return subprocess.CompletedProcess(argv, 1)
        with patch('subprocess.run', side_effect=other), self.assertRaises(core.ProtocolError) as raised:
            core.GitHub().request('repos/acme/.github')
        self.assertIsNone(getattr(raised.exception, 'http_status', None))


if __name__ == '__main__':
    unittest.main()


class OmittedBlobTests(unittest.TestCase):
    def test_an_edited_omitted_candidate_changes_the_inventory(self):
        base = {f'AI_POLICY_{n:02d}.md': 'x' for n in range(12)}
        one = policy.report('acme/photos', SOURCE_COMMIT, [], PolicyGitHub({**base, 'AI_POLICY_12.md': 'AI welcome.'}),
                            default_branch='main')
        two = policy.report('acme/photos', SOURCE_COMMIT, [], PolicyGitHub({**base, 'AI_POLICY_12.md': 'No AI.'}),
                            default_branch='main')
        self.assertEqual([o['path'] for o in one['omitted_sources']], ['AI_POLICY_12.md'])
        self.assertNotEqual(one['omitted_sources'][0]['blob_sha'], two['omitted_sources'][0]['blob_sha'])
        self.assertNotEqual(one['inventory_sha256'], two['inventory_sha256'])
