"""Host issuer requirements for overlap dispositions ship with (or before) waiver evaluation."""
import importlib.resources
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def flat(text):
    return ' '.join(text.split())


def issuer_section():
    text = flat((ROOT / 'docs' / 'host-authorization.md').read_text('utf-8'))
    start = text.index('## Overlap dispositions')
    return text[start:text.index('## ', start + 3)]


class IssuerRequirementTests(unittest.TestCase):
    def test_code_comparison_is_immutable_and_base_tip_is_resolved_independently(self):
        section = issuer_section()
        for phrase in ('`GET repos/{source}/git/ref/heads/{base.ref}`', "never the PR's `base.sha`",
                       '`compare/{base_tip_sha}...{head_sha}`', '`merge_base_commit.sha`',
                       'A mutable diff link is not enough', '`material_sha256`',
                       '`filename`, `previous_filename`, `status`, `sha` and `patch`',
                       'Retains the exact material it showed'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, section)

    def test_refusal_rules(self):
        section = issuer_section()
        for phrase in ('comparison is unavailable', 'reports 300 files',
                       'any changed file has no reviewable textual patch', 'binary',
                       'authored by the credential actor', 'explicit reference to the issue',
                       'incomplete open-PR scan'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, section)

    def test_mandatory_host_negative_tests(self):
        section = issuer_section()
        for case in ('a forged or stale summary', 'edited between review and issuance',
                     'truthful API response whose description misleads', 'pushed while the human reviews',
                     'a saturated or truncated comparison', "`base.sha` differs from the base-branch tip",
                     'binary executable or WebAssembly module', 'source file GitHub reports without a patch',
                     'mixed PR', 'revoked or superseded disposition', 'agent-callable API'):
            with self.subTest(case=case):
                self.assertIn(case, section)

    def test_worker_never_writes_dispositions(self):
        workflow = flat(importlib.resources.files('agent_contribute').joinpath('instructions.md').read_text('utf-8'))
        self.assertIn('**Overlap dispositions.**', workflow)
        self.assertIn('The worker never writes, edits or completes an `overlap_dispositions` record', workflow)
        self.assertIn('direct references, incomplete scans', workflow)


if __name__ == '__main__':
    unittest.main()
