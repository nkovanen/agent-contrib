"""PR body rendering: golden output, inert untrusted text, no GitHub writes."""
import contextlib
import html
import copy
import io
import json
import os
import pathlib
import re
import tempfile
import unittest
from unittest.mock import patch

from agent_contribute import cli, core, prbody
from tests.test_authorization import candidate_task
from tests.test_protocol import FakeGitHub, evidence_checkout, ready_contract
from tests.test_schema_compatibility import FrozenClock

GOLDEN = pathlib.Path(__file__).parent / 'fixtures' / 'pr_body'
SCANNED = {'pulls': {'complete': True, 'pages': 1, 'errors': []}}


def fixed_evidence(task, signoff='passed'):
    digest = core.canonical_hash(task)
    attestation = {'status': 'passed', 'reviewer': 'independent', 'git_head': 'c' * 40,
                   'contract_sha256': digest, 'notes': 'Reviewed'}
    return {'schema_version': '0.1', 'contract_sha256': digest, 'git_head': 'c' * 40, 'git_tree': 'd' * 40,
            'base_commit': 'a' * 40, 'worktree_clean': True, 'implementer': 'builder', 'artifacts': [],
            'validations': [{'id': 'unit', 'argv': ['python3', '-m', 'unittest'], 'status': 'passed',
                             'exit_code': 0, 'skipped': 0, 'output': 'OK', 'tool_version': 'Python 3.12',
                             'git_head': 'c' * 40, 'tests_run': 7, 'started_at': '2030-01-01T00:00:00Z',
                             'finished_at': '2030-01-01T00:00:01Z'}],
            'criteria': [{'id': 'bounds', 'status': 'passed', 'evidence': 'Regression rejects 0x0'}],
            'independent_review': copy.deepcopy(attestation),
            'human_signoff': dict(attestation, reviewer='' if signoff == 'pending' else 'human', status=signoff)}


class PRBodyTests(unittest.TestCase):
    def setUp(self):
        clock = patch.object(core.dt, 'datetime', FrozenClock)
        clock.start()
        self.addCleanup(clock.stop)

    def assertGolden(self, name, text):
        if os.environ.get('UPDATE_GOLDEN'):
            (GOLDEN / name).write_text(text, encoding='utf-8')
        self.assertEqual(text, (GOLDEN / name).read_text(encoding='utf-8'))

    def test_draft_only_golden_shows_every_pending_gate(self):
        task, client = ready_contract()
        body, verification = prbody.pr_body(task, client=client)
        self.assertTrue(verification['execution_ready'])
        self.assertGolden('draft.md', body)
        self.assertIn('No execution evidence, independent review or human signoff provided', body)

    def test_full_evidence_golden(self):
        task, _ = ready_contract()
        verification = {'schema_valid': True, 'execution_ready': True, 'evidence_valid': True,
                        'upstream_submission_ready': True, 'fork_completion_ready': False, 'errors': [],
                        'evidence_errors': [], 'live_complete': True, 'duplicates': [],
                        'contract_sha256': core.canonical_hash(task), 'live_provenance': SCANNED}
        template = {'state': 'found', 'templates': [{'path': '.github/pull_request_template.md', 'sha': 'e' * 40}]}
        self.assertGolden('full.md', prbody.render(task, verification, fixed_evidence(task), assistant='Claude Opus 5.5',
                                                   template=template))

    def test_pending_signoff_golden(self):
        task, _ = ready_contract()
        verification = {'schema_valid': True, 'execution_ready': True, 'evidence_valid': False,
                        'upstream_submission_ready': False, 'fork_completion_ready': False, 'errors': [],
                        'evidence_errors': ['human_signoff is missing, failed, pending or stale'],
                        'live_complete': True, 'duplicates': [], 'contract_sha256': core.canonical_hash(task),
                        'live_provenance': SCANNED}
        body = prbody.render(task, verification, fixed_evidence(task, 'pending'), template={'state': 'none', 'templates': []})
        self.assertGolden('pending_signoff.md', body)
        self.assertIn('- Human signoff: unverified claim: pending\n', body)
        self.assertIn('- evidence: human\\_signoff is missing, failed, pending or stale', body)

    def test_untrusted_text_is_inert(self):
        task, _ = ready_contract()
        hostile = ('Fixes #12 closes acme/photos#3 RESOLVED https://github.com/acme/photos/issues/4 @octocat '
                   '<img src=x onerror=alert(1)> ![p](https://t.example/p.png) [link](javascript:x)\n# Heading\n```')
        task['objective'] = hostile
        task['behavior_criteria'][0]['description'] = hostile
        verification = {'schema_valid': True, 'errors': [hostile], 'evidence_errors': [],
                        'duplicates': [{'url': hostile, 'reason': hostile}]}
        body = prbody.render(task, verification, assistant=hostile)
        self.assertEqual(body.count('Refs acme/photos#12'), 1, 'only the trusted reference stays live')
        # As GitHub sees the text: the entity becomes a real zero-width space.
        quoted = body.replace('Refs acme/photos#12', '').replace('&#8203;', '\u200b')
        visible = body.replace('&#8203;', '')
        self.assertNotRegex(quoted, r'(?i)\b(close[sd]?|fix(e[sd])?|resolve[sd]?)\b')
        self.assertNotRegex(quoted, r'@[A-Za-z]')
        self.assertNotRegex(quoted, r'#[0-9]')
        self.assertNotRegex(quoted, r'https?://')
        self.assertNotIn('<img', body)
        self.assertNotRegex(body, r'(?<!\\)!(?<!\\)\[')
        self.assertNotIn('```', body)
        self.assertFalse(any(line.startswith('#') and 'Heading' in line for line in body.splitlines()))
        self.assertIn('Fixes', visible)
        self.assertIn('@octocat', visible)

    def test_entity_encoded_references_and_strikethrough_stay_inert(self):
        task, _ = ready_contract()
        hostile = ('&commat;octocat &num;12 acme/photos&num;3 https&colon;&sol;&sol;evil.example '
                   '&#64;octocat &#x23;4 ~~verified~~ | x | y |')
        task['objective'] = hostile
        body = prbody.render(task, {'schema_valid': True, 'errors': [hostile], 'evidence_errors': []})
        # After one HTML decoding pass, no entity may reintroduce a mention, reference or URL.
        decoded = html.unescape(body.replace('Refs acme/photos#12', ''))
        self.assertNotRegex(decoded, r'@[A-Za-z]')
        self.assertNotRegex(decoded, r'#[0-9]')
        self.assertNotRegex(decoded, r'https?://')
        self.assertIn('&amp;commat;octocat', body)
        self.assertNotRegex(body, r'(?<!\\)~')
        self.assertEqual(prbody.md('~~x~~ | y'), r'\~\~x\~\~ \| y')

    def test_schema_02_evidence_claims_follow_technical_evidence_validity(self):
        task, _ = ready_contract()
        task.update(schema_version='0.2', source=candidate_task()[0]['source'])
        evidence = fixed_evidence(task)
        for technical, legacy, verified in [(True, None, True), (False, True, False)]:
            with self.subTest(technical=technical, legacy=legacy):
                verification = {'schema_valid': True, 'technical_evidence_valid': technical, 'stage_blockers': {}}
                if legacy is not None:
                    verification['evidence_valid'] = legacy
                body = prbody.render(task, verification, evidence)
                self.assertEqual('unverified claim' in body, not verified, body)
                self.assertEqual('Supplied evidence did not pass `verify`' in body, not verified)
                self.assertIn('(' + ('' if verified else 'unverified claim: ') + 'passed: Regression rejects 0x0)', body)

    def test_schema_02_omits_authority_gates_it_cannot_reproduce(self):
        # pr-body has no host context, so 0.2 authority states would always read "unauthorized" (A1-12).
        task, _ = candidate_task()
        verification = {'schema_valid': True, 'implementation_ready': False, 'technical_evidence_valid': False,
                        'draft_create_ready': False, 'completion_ready': False, 'next_action': 'resolve_blockers',
                        'errors': ['Missing human/host mandate', 'Live discovery is incomplete', 'Current mandate expired'],
                        'user_authorization': {'errors': ['Missing human/host mandate'],
                                               'current_errors': ['Current mandate expired']},
                        'evidence_errors': ['No technical execution evidence provided'],
                        'independent_review': {'status': 'passed', 'valid': False,
                                               'errors': ['Independent reviewer must differ from implementer']},
                        'stage_blockers': {'implementation': ['Current implement action is not authorized'],
                                           'completion': ['Final human signoff is pending or invalid']}}
        body = prbody.render(task, verification)
        for line in ['- `technical_evidence_valid`: no', '- source: Live discovery is incomplete',
                     '- evidence: No technical execution evidence provided',
                     '- review: Independent reviewer must differ from implementer',
                     '- Independent review: passed (not valid per verify)',
                     '- Final human sign-off: not shown (requires host context)']:
            self.assertIn(line + '\n', body)
        self.assertIn(prbody.AUTHORITY_OMITTED, body)
        for text in ['implementation_ready', 'draft_create_ready', 'completion_ready', '`next_action`:',
                     'mandate', 'not authorized', 'signoff is pending']:
            self.assertNotIn(text, body)

    def test_schema_02_real_path_does_not_claim_the_work_is_unauthorized(self):
        task, client = candidate_task()
        client.compare_status = 'ahead'
        client.commit = 'b' * 40  # a different tip: equal commits can only be identical (FR1-04)
        body, verification = prbody.pr_body(task, None, None, client)
        self.assertIn('Current implement action is not authorized', verification['stage_blockers']['implementation'])
        for text in ['mandate', 'not authorized', '`implementation_ready`', '`draft_create_ready`', '`completion_ready`']:
            self.assertNotIn(text, body)
        self.assertIn(prbody.AUTHORITY_OMITTED, body)
        self.assertIn('- source: Reviewed source commit is not in current source default-branch history: base '
                      f'{task["source"]["commit"]} is ahead of acme/photos default branch main at {"b" * 40}\n', body)
        self.assertIn('- evidence: No technical execution evidence provided\n', body)

    def test_schema_02_keeps_source_identity_blockers_reported_by_authorization(self):
        # R1-10: identity failures arrive in user_authorization.errors but are source facts, not authority states.
        from tests import test_lifecycle
        case = test_lifecycle.IntegratedLifecycleTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        cases = [('repos/acme/photos', 'id', 102, 'Reviewed repository or owner identity changed'),
                 ('repos/acme/photos/issues/12', 'id', 9999, 'Reviewed issue identity changed')]
        for endpoint, key, value, error in cases:
            with self.subTest(error=error):
                original = case.client.request
                case.client.request = lambda e, o=original: dict(o(e), **{key: value}) if e == endpoint else o(e)
                try:
                    body, verification = prbody.pr_body(case.task, case.evidence, case.directory.name, case.client)
                finally:
                    case.client.request = original
                self.assertIn(error, verification['user_authorization']['errors'])
                self.assertIn('- source: ' + error + '\n', body)
                self.assertNotIn('No pending gates were reported.', body)
                self.assertNotIn('mandate', body)

    def test_next_action_enum_is_never_mangled_or_echoed_for_schema_02(self):
        # A1-14 kept the enum from being mangled; A1-12 omits it, so neither form may appear as a gate.
        task, _ = candidate_task()
        for value in ('resolve_blockers', 'create_draft', 'implement', 'none', 'Fixes #1 `x`'):
            with self.subTest(value=value):
                body = prbody.render(task, {'schema_valid': True, 'next_action': value})
                self.assertNotIn('- `next_action`:', body)
                self.assertNotIn(prbody.md(value), body.replace(prbody.AUTHORITY_OMITTED, ''))
                self.assertIn(prbody.AUTHORITY_OMITTED, body)

    def test_argv_is_exact_unambiguous_data(self):
        task, _ = ready_contract()
        task['validation'][0]['argv'] = ['python3', '-c', 'print("hello world")', 'a`b``c', '\n@x #1']
        body = prbody.render(task, {'schema_valid': True})
        self.assertIn('argv ``` ["python3", "-c", "print(\\"hello world\\")", "a`b``c", "\\n@x #1"] ```;', body)

    def test_every_blocker_and_overlap_is_rendered_without_silent_caps(self):
        task, _ = ready_contract()
        errors = ['blocker %03d ' % i + 'x' * 3000 for i in range(250)]
        duplicates = [{'url': 'dup%d' % i, 'reason': 'r'} for i in range(80)]
        body = prbody.render(task, {'errors': errors, 'evidence_errors': [], 'duplicates': duplicates})
        self.assertIn('Pending gates (250):', body)
        self.assertEqual(body.count('- execution: blocker'), 250)
        self.assertIn('blocker 249 ' + 'x' * 3000, body)
        self.assertEqual(sum(line.startswith('- dup') for line in body.splitlines()), 80)

    def test_invalid_evidence_is_labelled_as_unverified_claims(self):
        with tempfile.TemporaryDirectory() as tmp:
            task, client, evidence, _ = evidence_checkout(tmp)
            evidence['git_head'] = 'f' * 40  # schema-valid, wrong head
            body, verification = prbody.pr_body(task, evidence, tmp, client)
            self.assertFalse(verification['evidence_valid'])
            self.assertIn('Supplied evidence did not pass `verify`; its statuses below are unverified claims.', body)
            self.assertIn('(unverified claim: passed: Bounds verified)', body)
            self.assertIn('unverified claim: status passed', body)
            self.assertIn('- Independent review: unverified claim: passed by independent', body)

    def test_template_pointer_and_scan_provenance(self):
        task, client = ready_contract()
        original = client.request
        def with_template(endpoint):
            value = original(endpoint)
            if '/git/trees/' in endpoint:
                value['tree'] += [{'path': '.github/PULL_REQUEST_TEMPLATE.md', 'type': 'blob', 'sha': 'e' * 40},
                                  {'path': 'docs/pull_request_template/bug.md', 'type': 'blob', 'sha': 'nothex'},
                                  {'path': 'src/pull_request_template.md', 'type': 'blob'}]
            return value
        client.request = with_template
        body, _ = prbody.pr_body(task, client=client)
        self.assertIn('- ` ".github/PULL_REQUEST_TEMPLATE.md" ` (blob `' + 'e' * 40 + '`)', body)
        self.assertIn('- ` "docs/pull_request_template/bug.md" `\n', body)
        self.assertNotIn('src/pull_request_template.md', body)
        self.assertIn('repos/acme/photos/git/trees/' + task['source']['commit'] + '?recursive=1', client.calls)
        self.assertIn('- Source open PRs (acme/photos): complete yes, pages 1, errors 0', body)
        client.request = original
        self.assertIn('No pull request template exists at the pinned commit', prbody.pr_body(task, client=client)[0])
        client.failed.add('/git/trees/' + task['source']['commit'])
        self.assertEqual(prbody.template_pointer(task, client), {'state': 'unknown', 'templates': []})
        truncated = FakeGitHub()
        truncated.request = lambda endpoint: {'truncated': True, 'tree': []}
        self.assertEqual(prbody.template_pointer(task, truncated)['state'], 'unknown')

    def test_a_malformed_tree_entry_makes_the_template_lookup_unknown(self):
        # A template entry without a valid type was skipped, so the body claimed no template exists.
        task, client = ready_contract()
        original = client.request
        for name, entry in {'type missing': {'path': '.github/PULL_REQUEST_TEMPLATE.md'},
                            'type unknown': {'path': '.github/PULL_REQUEST_TEMPLATE.md', 'type': 'unknown'},
                            'mode contradicts type': {'path': 'docs', 'type': 'tree', 'mode': '100644'},
                            'empty path': {'path': '', 'type': 'blob'},
                            'repeated path': {'path': 'AGENTS.md', 'type': 'blob', 'sha': 'e' * 40}}.items():
            def request(endpoint, entry=entry):
                value = original(endpoint)
                if '/git/trees/' in endpoint:
                    value['tree'].append(dict(entry))
                return value
            with self.subTest(case=name):
                client.request = request
                self.assertEqual(prbody.template_pointer(task, client), {'state': 'unknown', 'templates': []})
                self.assertIn('Pull request template presence is unknown', prbody.pr_body(task, client=client)[0])

        def non_blobs(endpoint):  # valid tree and submodule entries with template names are not templates
            value = original(endpoint)
            if '/git/trees/' in endpoint:
                value['tree'] += [{'path': 'docs/pull_request_template.md', 'type': 'tree', 'mode': '040000'},
                                  {'path': '.github/pull_request_template.md', 'type': 'commit', 'mode': '160000'}]
            return value
        client.request = non_blobs
        self.assertEqual(prbody.template_pointer(task, client), {'state': 'none', 'templates': []})
        client.request = original

    def test_closing_keyword_only_when_requested(self):
        task, client = ready_contract()
        self.assertIn('\nRefs acme/photos#12\n', prbody.pr_body(task, client=client)[0])
        self.assertIn('\nCloses acme/photos#12\n', prbody.pr_body(task, client=client, closes=True)[0])

    def test_malformed_evidence_is_not_quoted_and_contract_must_validate(self):
        with tempfile.TemporaryDirectory() as tmp:
            task, client, evidence, _ = evidence_checkout(tmp)
            evidence['criteria'][0]['evidence'] = 'QUOTE-ME'
            evidence['extra'] = True
            body, verification = prbody.pr_body(task, evidence, tmp, client)
            self.assertFalse(verification['evidence_valid'])
            self.assertNotIn('QUOTE-ME', body)
        with self.assertRaises(core.ProtocolError):
            prbody.pr_body({'schema_version': '0.1'}, client=FakeGitHub())

    def test_no_github_writes_and_exclusive_cli_output(self):
        task, client = ready_contract()
        with tempfile.TemporaryDirectory() as out:
            contract = pathlib.Path(out, 'task.json')
            contract.write_text(json.dumps(task))
            target = pathlib.Path(out, 'body.md')
            def run():
                output = io.StringIO()
                with patch.object(core, 'GitHub', return_value=client), contextlib.redirect_stdout(output):
                    code = cli.main(['pr-body', str(contract), '--output', str(target)])
                return code, json.loads(output.getvalue())
            code, result = run()
            self.assertEqual(code, 0, result)
            self.assertTrue(target.read_text().startswith('## Summary\n'))
            target.write_text('edited')
            self.assertEqual(run()[1]['error']['code'], 'file_error')
            self.assertEqual(target.read_text(), 'edited')
        self.assertTrue(all(not re.search(r'(?i)method|POST|PATCH|PUT|DELETE', call) for call in client.calls))


if __name__ == '__main__':
    unittest.main()
