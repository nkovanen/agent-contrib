"""Commit-signature observations (#18, part): report only, strict shapes, no signature programs, never a gate."""
import contextlib
import copy
import io
import json
import os
import pathlib
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from agent_contribute import cli, core, outputs, signatures
from tests.test_authorization import candidate_task
from tests.test_protocol import evidence_checkout, ready_contract, refresh_checkout_evidence

HEAD = 'a' * 40


def verification(verified=False, reason='unsigned', verified_at=None):
    return {'verified': verified, 'reason': reason, 'signature': 'SIGNATURE-MARKER', 'payload': 'PAYLOAD-MARKER',
            'verified_at': verified_at}


class SignatureGitHub:
    """Answers the two signature endpoints; everything else goes to the wrapped fixture client."""
    def __init__(self, base, head=HEAD):
        self.base, self.calls, self.failed = base, [], set()
        self.commit = {'sha': head, 'message': 'MESSAGE-MARKER', 'verification': verification()}
        self.rules = [{'type': 'pull_request', 'ruleset_id': 5, 'ruleset_source_type': 'Repository',
                       'ruleset_source': 'acme/photos'}]

    def request(self, endpoint):
        if '/git/commits/' in endpoint or '/rules/branches/' in endpoint:
            self.calls.append(endpoint)
            if any(key in endpoint for key in self.failed):
                raise core.ProtocolError('api_error', 'GitHub read failed')
            if '/git/commits/' in endpoint:
                return copy.deepcopy(self.commit)
            page = int(endpoint.rsplit('page=', 1)[1])
            return copy.deepcopy(self.rules[(page - 1) * 100:page * 100])
        return self.base.request(endpoint)


def without_times(value):
    """Read timestamps differ between two runs; everything else must match exactly."""
    if isinstance(value, dict):
        return {k: without_times(v) for k, v in value.items() if k not in ('fetched_at', 'read_at', 'checked_at')}
    if isinstance(value, list):
        return [without_times(v) for v in value]
    return value


def observe(client=None, evidence=None, task=None, repo_dir=None):
    task = task or ready_contract()[0]
    client = client or SignatureGitHub(ready_contract()[1])
    return signatures.observe(task, {'git_head': HEAD} if evidence is None else evidence, repo_dir, client), client


class GitHubVerificationTests(unittest.TestCase):
    def test_reports_verification_without_signature_payload_or_message(self):
        client = SignatureGitHub(ready_contract()[1])
        client.commit['verification'] = verification(True, 'valid', '2029-12-01T00:00:00Z')
        result, _ = observe(client)
        part = result['github_verification']
        self.assertEqual({k: part[k] for k in ('complete', 'verified', 'reason', 'verified_at')},
                         {'complete': True, 'verified': True, 'reason': 'valid', 'verified_at': '2029-12-01T00:00:00Z'})
        self.assertIn('repos/acme/photos/git/commits/' + HEAD, client.calls)
        text = json.dumps(result)
        for marker in ('SIGNATURE-MARKER', 'PAYLOAD-MARKER', 'MESSAGE-MARKER'):
            self.assertNotIn(marker, text)
        self.assertIn('not approval', result['notice'])
        self.assertIn('not approval', part['verified_means'])
        unsigned, _ = observe()
        self.assertEqual((unsigned['github_verification']['verified'], unsigned['github_verification']['reason']),
                         (False, 'unsigned'))

    def test_unknown_reason_is_not_echoed(self):
        client = SignatureGitHub(ready_contract()[1])
        client.commit['verification'] = verification(False, '\x1b[31mtrust me')
        result, _ = observe(client)
        self.assertEqual(result['github_verification']['reason'], 'unrecognized')
        self.assertTrue(result['github_verification']['complete'])
        self.assertNotIn('trust me', json.dumps(result))

    def test_malformed_or_failed_reads_are_unknown(self):
        cases = {'failed': lambda c: c.failed.add('/git/commits/'),
                 'other commit': lambda c: c.commit.update(sha='b' * 40),
                 'not an object': lambda c: setattr(c, 'commit', ['x']),
                 'no verification': lambda c: c.commit.pop('verification'),
                 'verified text': lambda c: c.commit['verification'].update(verified='true'),
                 'reason missing': lambda c: c.commit['verification'].update(reason=None),
                 'bad time': lambda c: c.commit['verification'].update(verified_at='soon'),
                 'naive time': lambda c: c.commit['verification'].update(verified_at='2029-12-01T00:00:00'),
                 'verified but not valid': lambda c: c.commit['verification'].update(verified=True, reason='unsigned'),
                 'valid but not verified': lambda c: c.commit['verification'].update(verified=False, reason='valid')}
        for name, change in cases.items():
            with self.subTest(name):
                client = SignatureGitHub(ready_contract()[1])
                change(client)
                result, _ = observe(client)
                part = result['github_verification']
                self.assertEqual((part['complete'], part['verified'], part['reason']), (False, None, None))
                self.assertTrue(part['errors'])
                self.assertFalse(result['complete'])
                # Only a failed read, not a malformed answer, gets the unpushed-head hint.
                self.assertEqual('not pushed' in part['errors'][0], name == 'failed')

    def test_verification_time_must_be_strict_rfc3339(self):
        # Review R6-04: fromisoformat accepted any single separator, so controls rode along in verified_at.
        for value in ['2029-12-01\x1b00:00:00+00:00', '2029-12-01\u202e00:00:00+00:00', '2029-12-01\x0000:00:00+00:00',
                      '2029-12-01\n00:00:00+00:00', '2029-12-01 00:00:00+00:00', '', '2029-12-01T00:00:00.1234567Z',
                      '2029-12-01T00:00:00-00:00', '2029-12-01T00:00:00+24:00', '2029-12-01']:
            with self.subTest(value=value):
                client = SignatureGitHub(ready_contract()[1])
                client.commit['verification'] = verification(True, 'valid', value)
                part = observe(client)[0]['github_verification']
                self.assertEqual((part['complete'], part['verified_at']), (False, None))
        for value in ['2029-12-01T00:00:00Z', '2029-12-01T00:00:00.5+02:00']:
            client = SignatureGitHub(ready_contract()[1])
            client.commit['verification'] = verification(True, 'valid', value)
            self.assertEqual(observe(client)[0]['github_verification']['verified_at'], value)

    def test_missing_or_invalid_evidence_head_reads_nothing(self):
        for evidence in [{}, {'git_head': 'HEAD'}, ['x'], {'git_head': 'A' * 40}]:
            with self.subTest(evidence=evidence):
                client = SignatureGitHub(ready_contract()[1])
                result = signatures.observe(ready_contract()[0], evidence, None, client)
                self.assertFalse(result['complete'])
                self.assertTrue(result['errors'])
                self.assertEqual(client.calls, [])
        client = SignatureGitHub(ready_contract()[1])
        self.assertFalse(signatures.observe(ready_contract()[0], None, None, client)['complete'])
        self.assertEqual(client.calls, [])


def observe_type(kind):
    client = SignatureGitHub(ready_contract()[1])
    client.rules.append({'type': kind, 'ruleset_id': 7})
    part = observe(client)[0]['required_signatures']
    return part['complete'], part['required']


class RequiredSignatureTests(unittest.TestCase):
    def test_required_signature_rule_and_ruleset_ids(self):
        client = SignatureGitHub(ready_contract()[1])
        client.rules += [{'type': 'required_signatures', 'ruleset_id': 9, 'ruleset_source_type': 'Organization',
                          'ruleset_source': 'acme'},
                         {'type': 'required_signatures', 'ruleset_id': 3, 'ruleset_source_type': 'Repository',
                          'ruleset_source': 'acme/photos'}]
        result, _ = observe(client)
        part = result['required_signatures']
        self.assertEqual({k: part[k] for k in ('complete', 'required', 'ruleset_ids', 'branch', 'classic_branch_protection')},
                         {'complete': True, 'required': True, 'ruleset_ids': [3, 9], 'branch': 'main',
                          'classic_branch_protection': 'not_observed'})
        self.assertIn('repos/acme/photos/rules/branches/main?per_page=100&page=1', client.calls)
        plain, _ = observe()
        self.assertEqual((plain['required_signatures']['required'], plain['required_signatures']['ruleset_ids']), (False, []))
        self.assertEqual(plain['required_signatures']['classic_branch_protection'], 'not_observed')

    def test_malformed_or_unrecognized_rule_types_are_never_a_confident_negative(self):
        # Review R6-05: any string type counted, so '' or 'required_signatures ' gave required: false, complete.
        for kind in ['', 'required_signatures ', '\u202erequired_signatures', 'Required_Signatures', 'required-signatures',
                     'x' * 101, 'future_rule']:
            with self.subTest(kind=kind):
                client = SignatureGitHub(ready_contract()[1])
                client.rules.append({'type': kind, 'ruleset_id': 7})
                part = observe(client)[0]['required_signatures']
                self.assertEqual((part['complete'], part['required'], part['ruleset_ids']), (False, None, None))
                self.assertTrue(part['errors'])
        for kind in ['', 'required_signatures ', '\u202erequired_signatures', 'Required_Signatures', 'x' * 101]:
            with self.subTest(malformed_beside_exact=kind):  # malformed data voids the read, even beside a real rule
                client = SignatureGitHub(ready_contract()[1])
                client.rules += [{'type': kind, 'ruleset_id': 7}, {'type': 'required_signatures', 'ruleset_id': 8}]
                part = observe(client)[0]['required_signatures']
                self.assertEqual((part['complete'], part['required']), (False, None))
        self.assertEqual(observe_type('x' * 100), (False, None), 'a well-formed unknown type of 100 characters')
        client = SignatureGitHub(ready_contract()[1])
        client.rules += [{'type': 'future_rule', 'ruleset_id': 7}, {'type': 'required_signatures', 'ruleset_id': 8}]
        part = observe(client)[0]['required_signatures']
        self.assertEqual((part['complete'], part['required'], part['ruleset_ids']), (True, True, [8]),
                         'an exact required_signatures rule is certain even beside an unrecognized type')
        client = SignatureGitHub(ready_contract()[1])
        client.rules = [{'type': kind, 'ruleset_id': i} for i, kind in enumerate(sorted(signatures.RULE_TYPES - {'required_signatures'}), 1)]
        part = observe(client)[0]['required_signatures']
        self.assertEqual((part['complete'], part['required']), (True, False))

    def test_a_rule_on_a_later_page_counts(self):
        client = SignatureGitHub(ready_contract()[1])  # Review R6-M01
        client.rules = [{'type': 'creation', 'ruleset_id': i} for i in range(1, 101)] + [
            {'type': 'required_signatures', 'ruleset_id': 500}]
        part = observe(client)[0]['required_signatures']
        self.assertEqual((part['complete'], part['required'], part['ruleset_ids']), (True, True, [500]))

    def test_every_documented_reason_passes_through(self):
        for reason in sorted(signatures.REASONS):  # Review R6-M02
            with self.subTest(reason=reason):
                client = SignatureGitHub(ready_contract()[1])
                client.commit['verification'] = verification(reason == 'valid', reason)
                self.assertEqual(observe(client)[0]['github_verification']['reason'], reason)
        self.assertEqual(len(signatures.REASONS), 15)

    def test_base_ref_is_used_and_quoted(self):
        task, base = candidate_task()
        task['execution']['base_ref'] = 'release/1.x'
        client = SignatureGitHub(base)
        result = signatures.observe(task, {'git_head': HEAD}, None, client)
        self.assertEqual(result['required_signatures']['branch'], 'release/1.x')
        self.assertIn('repos/acme/photos/rules/branches/release%2F1.x?per_page=100&page=1', client.calls)
        legacy, base = ready_contract()
        legacy['source']['default_branch'] = 'trunk'
        client = SignatureGitHub(base)
        signatures.observe(legacy, {'git_head': HEAD}, None, client)
        self.assertIn('repos/acme/photos/rules/branches/trunk?per_page=100&page=1', client.calls)

    def test_malformed_partial_or_failed_rules_are_unknown(self):
        def full_pages(c):
            c.rules = [{'type': 'creation', 'ruleset_id': i} for i in range(1, 4001)]
        cases = {'failed': lambda c: c.failed.add('/rules/branches/'),
                 'type missing': lambda c: c.rules.append({'ruleset_id': 4}),
                 'type not text': lambda c: c.rules.append({'type': 7, 'ruleset_id': 4}),
                 'id missing': lambda c: c.rules.append({'type': 'required_signatures'}),
                 'id bool': lambda c: c.rules.append({'type': 'required_signatures', 'ruleset_id': True}),
                 'id zero': lambda c: c.rules.append({'type': 'required_signatures', 'ruleset_id': 0}),
                 'repeated': lambda c: c.rules.append(dict(c.rules[0])),
                 'entry not object': lambda c: c.rules.append('required_signatures'),
                 'page limit': full_pages}
        for name, change in cases.items():
            with self.subTest(name):
                client = SignatureGitHub(ready_contract()[1])
                change(client)
                result, _ = observe(client)
                part = result['required_signatures']
                self.assertEqual((part['complete'], part['required'], part['ruleset_ids']), (False, None, None))
                self.assertTrue(part['errors'])
                self.assertEqual(part['classic_branch_protection'], 'not_observed')


class LocalCommitTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.repo = self.directory.name

    def git(self, *argv, stdin=None):
        return subprocess.run(['git', '-C', self.repo, '-c', 'user.name=Test', '-c', 'user.email=test@example.org', *argv],
                              input=stdin, capture_output=True, text=True, check=True).stdout.strip()

    def build(self, signed=(False, True, False)):
        self.git('init', '-q')
        self.git('commit', '-q', '--allow-empty', '-m', 'base')
        base = head = self.git('rev-parse', 'HEAD')
        tree = self.git('rev-parse', 'HEAD^{tree}')
        commits = []
        for number, is_signed in enumerate(signed):
            header = f'tree {tree}\nparent {head}\nauthor A <a@e> {number} +0000\ncommitter A <a@e> {number} +0000\n'
            if is_signed:
                header += 'gpgsig -----BEGIN PGP SIGNATURE-----\n \n FORGED\n -----END PGP SIGNATURE-----\n'
            head = self.git('hash-object', '-t', 'commit', '-w', '--stdin', stdin=header + f'\nchange {number}\n')
            commits.append(head)
        self.git('update-ref', 'refs/heads/main', head)
        return base, head, commits

    def local(self, base, head, **kwargs):
        return observe(evidence={'git_head': head, 'base_commit': base}, repo_dir=self.repo, **kwargs)[0]['local_commits']

    def test_header_presence_per_commit_oldest_first(self):
        base, head, commits = self.build()
        part = self.local(base, head)
        self.assertEqual(part['commits'], [{'sha': commits[0], 'signature_header': 'absent'},
                                           {'sha': commits[1], 'signature_header': 'present'},
                                           {'sha': commits[2], 'signature_header': 'absent'}])
        self.assertEqual((part['complete'], part['with_header'], part['without_header'], part['limit']), (True, 1, 2, 1000))
        self.assertIn('presence', part['notice'])

    def test_sha256_signature_header_counts(self):
        self.git('init', '-q')
        self.git('commit', '-q', '--allow-empty', '-m', 'base')
        base, tree = self.git('rev-parse', 'HEAD'), self.git('rev-parse', 'HEAD^{tree}')
        content = (f'tree {tree}\nparent {base}\nauthor A <a@e> 1 +0000\ncommitter A <a@e> 1 +0000\n'
                   'gpgsig-sha256 -----BEGIN SSH SIGNATURE-----\n FORGED\n -----END SSH SIGNATURE-----\n\nmessage\n')
        head = self.git('hash-object', '-t', 'commit', '-w', '--stdin', stdin=content)
        self.assertEqual(self.local(base, head)['commits'], [{'sha': head, 'signature_header': 'present'}])

    def test_header_text_in_the_message_is_not_a_signature(self):
        self.git('init', '-q')
        self.git('commit', '-q', '--allow-empty', '-m', 'base')
        base, tree = self.git('rev-parse', 'HEAD'), self.git('rev-parse', 'HEAD^{tree}')
        content = (f'tree {tree}\nparent {base}\nauthor A <a@e> 1 +0000\ncommitter A <a@e> 1 +0000\n'
                   '\ngpgsig -----BEGIN PGP SIGNATURE----- in the message\n')
        head = self.git('hash-object', '-t', 'commit', '-w', '--stdin', stdin=content)
        self.assertEqual(self.local(base, head)['commits'], [{'sha': head, 'signature_header': 'absent'}])

    def raw_commit(self, extra_headers, message=b'message\n'):
        self.git('init', '-q')
        self.git('commit', '-q', '--allow-empty', '-m', 'base')
        base, tree = self.git('rev-parse', 'HEAD'), self.git('rev-parse', 'HEAD^{tree}')
        content = (f'tree {tree}\nparent {base}\nauthor A <a@e> 1 +0000\ncommitter A <a@e> 1 +0000\n'.encode()
                   + extra_headers + b'\n' + message)
        head = subprocess.run(['git', '-C', self.repo, 'hash-object', '-t', 'commit', '-w', '--stdin', '--literally'],
                              input=content, capture_output=True, check=True).stdout.decode().strip()
        return base, head

    def test_carriage_returns_and_lookalikes_never_forge_a_header(self):
        # Review R6-03: text-mode newline conversion turned a CR inside another header into a gpgsig line.
        for name, headers in {'cr in extra header': b'x-note hello\rgpgsig FORGED\n',
                              'cr in continuation': b'mergetag object x\n gpgsig IGNORE\rgpgsig FORGED\n',
                              'continuation only': b'mergetag object x\n gpgsig not-a-header\n',
                              'lookalike name': b'gpgsignature FORGED\n',
                              'name without value': b'gpgsig\n'}.items():
            with self.subTest(name):
                base, head = self.raw_commit(headers)
                self.assertEqual(self.local(base, head)['commits'], [{'sha': head, 'signature_header': 'absent'}])
        base, head = self.raw_commit(b'x-note a\rb\ngpgsig -----BEGIN\n FORGED\n')
        self.assertEqual(self.local(base, head)['commits'], [{'sha': head, 'signature_header': 'present'}])

    def test_non_utf8_commit_is_read_as_bytes(self):
        base, head = self.raw_commit(b'encoding ISO-8859-1\ngpgsig -----BEGIN\n \xe9\n', message=b'caf\xe9\n')
        part = self.local(base, head)
        self.assertEqual((part['complete'], part['commits']), (True, [{'sha': head, 'signature_header': 'present'}]))

    def test_shallow_history_is_incomplete_even_when_the_base_is_reachable(self):
        # Review R6-06: in a shallow clone, base..head stops at the shallow boundary while merge-base still finds the
        # base through a merge parent, so a truncated list looked complete.
        self.git('init', '-q', '-b', 'main')
        self.git('commit', '-q', '--allow-empty', '-m', 'B')
        base, tree = self.git('rev-parse', 'HEAD'), self.git('rev-parse', 'HEAD^{tree}')

        def commit(parents, extra=b'', number=0):
            lines = [f'tree {tree}'] + [f'parent {p}' for p in parents] + [
                f'author A <a@e> {number} +0000', f'committer A <a@e> {number} +0000']
            content = '\n'.join(lines).encode() + b'\n' + extra + b'\n' + f'commit {number}\n'.encode()
            return subprocess.run(['git', '-C', self.repo, 'hash-object', '-t', 'commit', '-w', '--stdin'], input=content,
                                  capture_output=True, check=True).stdout.decode().strip()
        signed = commit([base], b'gpgsig -----BEGIN\n FORGED\n', 1)
        side = commit([signed], number=2)
        merge = commit([base, side], number=3)
        self.git('update-ref', 'refs/heads/main', merge)
        full = self.local(base, merge)
        self.assertEqual((full['complete'], full['with_header'], full['without_header']), (True, 1, 2))
        shallow = os.path.join(self.directory.name, 'shallow')
        subprocess.run(['git', 'clone', '-q', '--depth=2', '--branch', 'main', 'file://' + self.repo, shallow],
                       capture_output=True, check=True)
        self.assertEqual(subprocess.run(['git', '-C', shallow, 'merge-base', base, merge], capture_output=True,
                                        text=True, check=True).stdout.strip(), base, 'fixture: base stays reachable')
        result = observe(SignatureGitHub(ready_contract()[1], head=merge),
                         evidence={'git_head': merge, 'base_commit': base}, repo_dir=shallow)[0]
        part = result['local_commits']
        self.assertEqual((part['complete'], part['commits'], part['with_header'], result['complete']), (False, None, None, False))
        self.assertTrue(any('shallow' in error.lower() for error in part['errors']))
        with patch.object(signatures, 'MAX_COMMITS', 2):  # the cap cannot be bypassed through a shallow graph
            self.assertFalse(self.local(base, merge)['complete'])
            self.assertFalse(observe(evidence={'git_head': merge, 'base_commit': base}, repo_dir=shallow)[0]
                             ['local_commits']['complete'])

    def test_unexpected_shallow_answer_fails_closed(self):
        base, head, _ = self.build()
        real = core.git_read
        for answer in ('true', '--is-shallow-repository', '', 'False'):
            with self.subTest(answer=answer):
                def fake(directory, *args, **kwargs):
                    return answer if args[:1] == ('rev-parse',) else real(directory, *args, **kwargs)
                with patch.object(core, 'git_read', fake):
                    self.assertFalse(self.local(base, head)['complete'])

    def test_over_the_cap_is_incomplete_not_truncated(self):
        base, head, _ = self.build((False, False, False))
        with patch.object(signatures, 'MAX_COMMITS', 2):
            part = self.local(base, head)
        self.assertEqual((part['complete'], part['commits'], part['with_header'], part['without_header'], part['limit']),
                         (False, None, None, None, 2))
        self.assertTrue(part['errors'])
        with patch.object(signatures, 'MAX_COMMITS', 3):
            self.assertTrue(self.local(base, head)['complete'])

    def test_non_ancestor_missing_or_invalid_bases_are_incomplete(self):
        base, head, commits = self.build()
        self.git('checkout', '-q', '--orphan', 'other')
        self.git('commit', '-q', '--allow-empty', '-m', 'unrelated')
        unrelated = self.git('rev-parse', 'HEAD')
        for name, (start, end) in {'not an ancestor': (unrelated, head), 'reversed': (head, base),
                                   'missing object': ('c' * 40, head), 'missing head': (base, 'd' * 40),
                                   'no base': (None, head), 'short base': (base[:12], head),
                                   'option-like base': ('--octopus', head)}.items():
            with self.subTest(name):
                calls, real = [], core.git_read
                with patch.object(core, 'git_read', lambda directory, *args, **kw: calls.append(args) or real(directory, *args, **kw)):
                    result = observe(SignatureGitHub(ready_contract()[1], head=end),
                                     evidence={'git_head': end, 'base_commit': start}, repo_dir=self.repo)[0]
                part = result['local_commits']
                self.assertTrue(result['github_verification']['complete'] and result['required_signatures']['complete'])
                self.assertEqual((part['complete'], part['commits'], result['complete']), (False, None, False))
                self.assertTrue(part['errors'])
                if name in ('no base', 'short base', 'option-like base'):
                    self.assertEqual(calls, [], 'an invalid base must never reach Git')

    def test_empty_range_is_complete(self):
        base, _, _ = self.build(())
        part = self.local(base, base)
        self.assertEqual((part['complete'], part['commits'], part['with_header'], part['without_header']), (True, [], 0, 0))

    def test_not_requested_without_repo_dir(self):
        result, client = observe()
        self.assertEqual(result['local_commits'], {'status': 'not_requested'})
        self.assertTrue(result['complete'])

    def test_hostile_repository_config_runs_no_signature_program(self):
        base, head, _ = self.build()
        marker = pathlib.Path(self.repo, 'ran')
        script = pathlib.Path(self.directory.name, 'evil.sh')
        script.write_text('#!/bin/sh\ntouch "%s"\nexit 0\n' % marker)
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        calls = []
        real = core.git_read

        def recording(directory, *args, **kwargs):
            calls.append(args)
            return real(directory, *args, **kwargs)

        # Settings git_read forces off, or that its fixed commands never reach: the scan completes.
        for key in ('core.fsmonitor', 'core.pager', 'pager.cat-file', 'pager.rev-list', 'core.sshCommand'):
            self.git('config', key, str(script))
        self.git('config', 'log.showSignature', 'true')
        with patch.object(core, 'git_read', recording):
            part = self.local(base, head)
        self.assertTrue(part['complete'], part.get('errors'))
        self.assertEqual({args[0] for args in calls}, {'config', 'rev-parse', 'merge-base', 'rev-list', 'cat-file'})
        for args in calls:
            self.assertFalse({'--show-signature', 'verify-commit', '--pretty', '--format'} & set(args), args)
        self.assertNotIn('subprocess', vars(signatures))
        # Signature programs in checkout config are refused before any read, so they cannot run either.
        for key in ('gpg.program', 'gpg.openpgp.program', 'gpg.ssh.program', 'gpg.x509.program'):
            with self.subTest(key=key):
                self.git('config', key, str(script))
                part = self.local(base, head)
                self.assertEqual((part['complete'], part['commits']), (False, None))
                self.assertIn(key.lower(), part['errors'][0])
                self.git('config', '--unset', key)
        self.assertFalse(marker.exists())

class ConfiguredProgramTests(unittest.TestCase):
    """Review R6-01: a missing object must never lazy-fetch through a repository-configured transport."""
    def trap(self, root, include=False):
        repo = pathlib.Path(root, 'repo')
        repo.mkdir()
        git = lambda *a: subprocess.run(['git', '-C', str(repo), '-c', 'user.name=T', '-c', 'user.email=t@e', *a],
                                        capture_output=True, text=True, check=True).stdout.strip()
        git('init', '-q')
        git('commit', '-q', '--allow-empty', '-m', 'base')
        marker, helper = pathlib.Path(root, 'EXECUTED'), pathlib.Path(root, 'helper.sh')
        helper.write_text('#!/bin/sh\nprintf ran > %s\nexit 1\n' % marker)
        helper.chmod(0o700)
        settings = [('extensions.partialClone', 'trap'), ('remote.trap.promisor', 'true'),
                    ('remote.trap.url', 'ext::' + str(helper)), ('protocol.ext.allow', 'always')]
        if include:  # the same settings through a conditional include
            included = pathlib.Path(root, 'trap.config')
            for key, value in settings:
                subprocess.run(['git', 'config', '--file', str(included), key, value], check=True)
            git('config', f'includeIf.gitdir:{repo}/.git.path', str(included))
        else:
            for key, value in settings:
                git('config', key, value)
        return repo, git('rev-parse', 'HEAD'), marker

    def test_promisor_transport_never_runs_and_the_part_is_incomplete(self):
        for include in (False, True):
            with self.subTest(include=include), tempfile.TemporaryDirectory() as root:
                repo, base, marker = self.trap(root, include)
                part = signatures.local_commits(str(repo), base, 'f' * 40)
                self.assertFalse(marker.exists(), 'configured transport executed')
                self.assertEqual((part['complete'], part['commits']), (False, None))
                # Defense in depth for Git without GIT_NO_LAZY_FETCH: the checkout config is refused before any read.
                self.assertIn('extensions.partialclone', part['errors'][0])

    def test_promisor_transport_never_runs_through_verify(self):
        task, base_client = ready_contract()
        with tempfile.TemporaryDirectory() as root:
            repo, base, marker = self.trap(root)
            paths = pathlib.Path(root, 'task.json'), pathlib.Path(root, 'e.json')
            paths[0].write_text(json.dumps(task))
            paths[1].write_text(json.dumps({'git_head': 'f' * 40, 'base_commit': base}))
            runs = []
            for flags in ([], ['--observe-signatures']):
                output = io.StringIO()
                with patch.object(core, 'GitHub', return_value=SignatureGitHub(base_client, head='f' * 40)), \
                        contextlib.redirect_stdout(output):
                    code = cli.main(['verify', str(paths[0]), '--evidence', str(paths[1]), '--repo-dir', str(repo), *flags])
                runs.append((code, json.loads(output.getvalue())))
            self.assertFalse(marker.exists(), 'configured transport executed through verify')
            self.assertEqual(runs[0][0], runs[1][0])
            self.assertFalse(runs[1][1]['signature_observation']['local_commits']['complete'])

    def test_raw_reads_inherit_every_hardening_setting(self):
        calls = []

        def capture(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, stdout=b'' if not kwargs.get('text') else '', stderr='')
        with patch.object(core.subprocess, 'run', capture):
            core.git_read('/x', 'cat-file', 'commit', 'a' * 40)
            core.git_read('/x', 'cat-file', 'commit', 'a' * 40, raw=True)
        (text_argv, text_kw), (raw_argv, raw_kw) = calls
        self.assertEqual(raw_argv, text_argv)
        self.assertEqual((text_kw.pop('text'), raw_kw.pop('text')), (True, False))
        self.assertEqual(raw_kw, text_kw)
        self.assertEqual((raw_kw['env'].get('GIT_NO_LAZY_FETCH'), 'protocol.allow=never' in raw_argv), ('1', True))


class OutputSchemaTests(unittest.TestCase):
    def errors(self, value):
        schema = outputs.output_schema('verify')
        return core.schema_errors(value, {'$ref': '#/$defs/signature_observation'}, root=schema)

    def test_observations_match_the_closed_output_schema(self):
        local = LocalCommitTests()
        local.setUp()
        base, head, _ = local.build()
        complete = observe(SignatureGitHub(ready_contract()[1], head=head), evidence={'git_head': head, 'base_commit': base},
                           repo_dir=local.repo)[0]
        failed = observe(evidence={})[0]
        local.doCleanups()
        for value in (complete, failed, observe()[0]):
            self.assertEqual(self.errors(value), [])
        drifted = []
        for change in [lambda v: v.update(extra=1), lambda v: v['github_verification'].update(reason='bogus'),
                       lambda v: v['github_verification'].update(verified='true'),
                       lambda v: v['github_verification'].update(extra=1),
                       lambda v: v['required_signatures'].update(classic_branch_protection='none'),
                       lambda v: v['required_signatures'].update(ruleset_ids=[0]),
                       lambda v: v['local_commits']['commits'][0].update(signature_header='valid'),
                       lambda v: v['local_commits']['commits'][0].update(sha='A' * 40),
                       lambda v: v['local_commits'].update(with_header=-1),
                       lambda v: v['local_commits'].update(commits=[v['local_commits']['commits'][0]] * 1001),
                       lambda v: v.update(local_commits={'status': 'skipped'}),
                       lambda v: v.update(head_sha='a' * 39)]:
            value = copy.deepcopy(complete)
            change(value)
            drifted.append(bool(self.errors(value)))
        self.assertEqual(drifted, [True] * len(drifted))


class ContainmentTests(unittest.TestCase):
    """Review R6-02: an optional observer may never replace the verify result or change its exit status."""
    def verify_both(self, tmp, task, client, evidence, patches=()):
        contract, path = pathlib.Path(tmp, '..', 'task.json').resolve(), pathlib.Path(tmp, '..', 'e.json').resolve()
        contract.write_text(json.dumps(task))
        path.write_text(json.dumps(evidence))
        runs = []
        for flags in ([], ['--observe-signatures']):
            output = io.StringIO()
            with contextlib.ExitStack() as stack:
                stack.enter_context(patch.object(core, 'GitHub', return_value=client))
                stack.enter_context(contextlib.redirect_stdout(output))
                for target, name, value in patches:
                    stack.enter_context(patch.object(target, name, value))
                code = cli.main(['verify', str(contract), '--evidence', str(path), '--repo-dir', tmp, *flags])
            runs.append((code, json.loads(output.getvalue())))
        (plain_code, plain), (code, observed) = runs
        self.assertEqual(code, plain_code)
        report = observed.pop('signature_observation')
        self.assertEqual(without_times(observed), without_times(plain))
        return plain_code, plain, report

    def latin1_checkout(self, tmp):
        task, base, evidence, git = evidence_checkout(tmp)
        head = git('rev-parse', 'HEAD')
        content = (f'tree {git("rev-parse", "HEAD^{tree}")}\nparent {head}\nauthor A <a@e> 1 +0000\n'
                   f'committer A <a@e> 1 +0000\nencoding ISO-8859-1\n\n').encode() + b'caf\xe9\n'
        new = subprocess.run(['git', '-C', tmp, 'hash-object', '-t', 'commit', '-w', '--stdin'], input=content,
                             capture_output=True, check=True).stdout.decode().strip()
        git('update-ref', 'HEAD', new)
        refresh_checkout_evidence(evidence, git)
        return task, SignatureGitHub(base, head=new), evidence

    def test_non_utf8_commit_keeps_a_passing_verify_passing(self):
        with tempfile.TemporaryDirectory() as root:
            tmp = os.path.join(root, 'checkout')
            os.mkdir(tmp)
            task, client, evidence = self.latin1_checkout(tmp)
            code, plain, report = self.verify_both(tmp, task, client, evidence)
            self.assertEqual(code, 0, plain)
            self.assertTrue(plain['upstream_submission_ready'])
            self.assertTrue(report['local_commits']['complete'], report['errors'])

    def test_unexpected_observer_failures_stay_inside_the_report(self):
        failures = [(signatures, 'github_verification', lambda *a: 1 / 0),
                    (signatures, 'required_signatures', lambda *a: [][1]),
                    (signatures, 'local_commits', lambda *a: b'\xe9'.decode())]
        for failure in failures:
            with self.subTest(part=failure[1]), tempfile.TemporaryDirectory() as root:
                tmp = os.path.join(root, 'checkout')
                os.mkdir(tmp)
                task, client, evidence = self.latin1_checkout(tmp)
                code, plain, report = self.verify_both(tmp, task, client, evidence, [failure])
                self.assertEqual(code, 0)
                part = report[failure[1]]
                self.assertFalse(part['complete'] or report['complete'])
                self.assertEqual(part['errors'], ['Unexpected failure; not observed'])


class ReportOnlyTests(unittest.TestCase):
    def run_verify(self, task, base, flags, evidence=None, stage=(), failed=()):
        with tempfile.TemporaryDirectory() as tmp:
            contract = pathlib.Path(tmp, 'task.json')
            contract.write_text(json.dumps(task))
            path = pathlib.Path(tmp, 'e.json')
            path.write_text(json.dumps(evidence or {'git_head': HEAD}))
            client = SignatureGitHub(base)
            client.failed.update(failed)
            output = io.StringIO()
            with patch.object(core, 'GitHub', return_value=client), contextlib.redirect_stdout(output):
                code = cli.main(['verify', str(contract), '--evidence', str(path), *stage, *flags])
            return code, json.loads(output.getvalue()), client

    def test_opt_in_for_both_schemas_changes_no_gate_exit_or_read(self):
        for name, (task, base), stage in [('0.1', ready_contract(), ()), ('0.2', candidate_task(), ('--stage', 'implementation'))]:
            with self.subTest(schema=name):
                plain_code, plain, plain_client = self.run_verify(task, base, [], stage=stage)
                code, observed, client = self.run_verify(task, base, ['--observe-signatures'], stage=stage)
                self.assertEqual(code, plain_code)
                self.assertNotIn('signature_observation', plain)
                self.assertEqual(plain_client.calls, [])
                self.assertEqual(len(client.calls), 2)
                report = observed.pop('signature_observation')
                self.assertTrue(report['complete'], report['errors'])
                self.assertEqual(without_times(observed), without_times(plain))

    def test_failed_observation_still_changes_nothing(self):
        task, base = ready_contract()
        plain_code, plain, _ = self.run_verify(task, base, [])
        code, observed, _ = self.run_verify(task, base, ['--observe-signatures'], failed=('/git/commits/', '/rules/'))
        self.assertEqual(code, plain_code)
        self.assertFalse(observed.pop('signature_observation')['complete'])
        self.assertEqual(without_times(observed), without_times(plain))

    def test_schema_invalid_contract_gets_no_observation(self):
        task, base = ready_contract()
        task['schema_version'] = '9.9'
        _, result, client = self.run_verify(task, base, ['--observe-signatures'])
        self.assertNotIn('signature_observation', result)
        self.assertEqual(client.calls, [])


if __name__ == '__main__':
    unittest.main()
