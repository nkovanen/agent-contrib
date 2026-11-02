"""Documented contract mappings and route profiles; fixtures grant no real authority."""
import copy
import datetime as dt
import importlib.resources
import pathlib
import re
import unittest

from agent_contribute import core
from tests.test_authorization import NOW, event_binding
from tests import test_lifecycle
from tests.test_protocol import ready_contract

ROOT = pathlib.Path(__file__).resolve().parents[1]


def flat(text):
    return re.sub(r'\s+', ' ', text)


def workflow():
    return flat(importlib.resources.files('agent_contribute').joinpath('instructions.md').read_text('utf-8'))


class WorkflowTextTests(unittest.TestCase):
    def test_review_records_name_existing_fields(self):
        text = workflow()
        for phrase in ('`ai-policy-review`', '`Requirements ledger:`', '`independent_review.notes`'):
            self.assertIn(phrase, text)
        self.assertNotIn('record the review in the contract', text)
        self.assertNotIn('existing review notes', text)

    def test_local_only_and_coordinator_rules(self):
        text = workflow()
        self.assertIn('**Local-only work.**', text)
        self.assertIn('request only `implement`', text)
        self.assertIn('It must not issue, edit, re-serialize or approve', text)
        self.assertIn('answering host permission prompts', text)

    def test_stacked_base_limitation_is_documented(self):
        text = workflow()
        self.assertIn('**Stacked or unpublished bases.**', text)
        self.assertIn('an unpublished commit cannot be the evidence base', text)
        self.assertIn('includes the whole unpublished stack', text)
        self.assertIn('must be excluded from this contribution', text)
        self.assertIn('Old evidence, review and mandate do not transfer', text)
        self.assertNotIn('work stacked on unpublished commits cannot reach', text)
        host = flat((ROOT / 'docs' / 'host-authorization.md').read_text('utf-8'))
        self.assertIn('An unpublished commit cannot be the evidence base', host)
        self.assertNotIn('Work stacked on unpublished commits cannot produce valid', host)

    def test_host_handoff_shows_the_complete_contract(self):
        text = flat((ROOT / 'docs' / 'host-authorization.md').read_text('utf-8'))
        self.assertIn('complete reviewed contract', text)
        self.assertIn('never a summary', text)
        self.assertIn('## Local-only work', text)


class LifecycleFixture(unittest.TestCase):
    # Borrow the integrated fixture without re-collecting its tests here.
    setUp = test_lifecycle.IntegratedLifecycleTests.setUp
    verify = test_lifecycle.IntegratedLifecycleTests.verify
    rebind = test_lifecycle.IntegratedLifecycleTests.rebind


class IssuerRequirementTests(unittest.TestCase):
    def test_issuer_requirements_are_normative_and_keep_post_expiry_recognition(self):
        text = flat((ROOT / 'docs' / 'host-authorization.md').read_text('utf-8'))
        self.assertIn('## Host issuer requirements', text)
        for phrase in ('one parsed snapshot', 'agent-callable', '`active`, `revoked` or `superseded`',
                       'Expiry is not a status', 'never substitutes a fresh mandate',
                       'whatever the gates say', 'Single-use per mandate', 'Mandatory issuer tests'):
            self.assertIn(phrase, text)
        status = flat((ROOT / 'docs' / 'development-status.md').read_text('utf-8'))
        self.assertIn('issuer requirements are specified; no native issuer ships', status)


class PrerequisitePins(LifecycleFixture):
    """The documented ai-policy-review convention relies on existing prerequisite gating."""

    def with_prerequisite(self, status, evidence):
        self.task['prerequisites'] = [{'id': 'ai-policy-review', 'description': 'AI-policy review',
                                       'status': status, 'evidence': evidence}]
        self.rebind()
        return self.verify(evidence=False)

    def test_unsatisfied_ai_policy_review_blocks_implementation(self):
        self.assertTrue(self.with_prerequisite('satisfied', 'Coverage complete, 0 excerpts')['implementation_ready'])
        for status, evidence in [('blocked', 'Repository refuses AI contributions'),
                                 ('pending', 'Coverage incomplete'), ('satisfied', '  ')]:
            with self.subTest(status=status, evidence=evidence):
                result = self.with_prerequisite(status, evidence)
                self.assertFalse(result['implementation_ready'])
                state = 'satisfied without evidence' if status == 'satisfied' else status  # F1 (F5) wording
                self.assertIn(f'Prerequisites are not satisfied with evidence: ai-policy-review ({state})',
                              result['stage_blockers']['implementation'])

    def test_legacy_schema_prerequisites_block_readiness(self):
        task, client = ready_contract()
        for status, evidence in [('blocked', 'Refused'), ('pending', 'Incomplete'), ('satisfied', '')]:
            with self.subTest(status=status):
                candidate = copy.deepcopy(task)
                candidate['prerequisites'] = [{'id': 'ai-policy-review', 'description': 'AI-policy review',
                                               'status': status, 'evidence': evidence}]
                result = core.verify(candidate, client=client)
                self.assertFalse(result['execution_ready'])
                state = 'satisfied without evidence' if status == 'satisfied' else status  # F1 (F5) wording
                self.assertIn(f'Prerequisites are not satisfied with evidence: ai-policy-review ({state})',
                              result['errors'])

    def test_undeclared_review_field_still_fails_closed(self):
        for version in ('0.1', '0.2'):
            with self.subTest(version=version):
                task = copy.deepcopy(self.task) if version == '0.2' else ready_contract()[0]
                task['reviews'] = {'ai_policy': 'clear'}
                self.assertTrue(core.validate_contract(task))


class LocalOnlyPins(LifecycleFixture):
    def test_implement_only_mandate_never_reaches_draft_creation(self):
        self.context['mandate']['actions'] = ['implement']
        self.context['mandate']['event']['binding_sha256'] = event_binding(self.context['mandate'])
        result = self.verify()
        self.assertTrue(result['implementation_ready'], result)
        self.assertFalse(result['draft_create_ready'])
        self.assertIn('Both implement and create_draft actions must be authorized',
                      result['stage_blockers']['draft'])

    def stack(self, path):
        # Commit an unpublished "stacked base" that GitHub cannot resolve, then work on top of it.
        directory = pathlib.Path(self.directory.name)
        (directory / path).parent.mkdir(exist_ok=True)
        (directory / path).write_text('unpublished base work')
        self.git('add', '.')
        self.git('commit', '-q', '-m', 'unpublished stacked base')
        stacked = self.git('rev-parse', 'HEAD')
        (directory / 'src' / 'thumb.rs').write_text('work on the stacked base')
        self.git('add', '.')
        self.git('commit', '-q', '-m', 'task work')
        head = self.git('rev-parse', 'HEAD')
        self.evidence.update(git_head=head, git_tree=self.git('rev-parse', 'HEAD^{tree}'))
        self.evidence['independent_review']['git_head'] = head
        for validation in self.evidence['validations']:
            validation['git_head'] = head
        self.client.failed = {'...' + stacked}
        return stacked

    def test_unpublished_evidence_base_or_out_of_scope_stack_cannot_validate(self):
        stacked = self.stack('docs/stacked.md')
        self.evidence['base_commit'] = stacked
        result = self.verify()
        self.assertFalse(result['technical_evidence_valid'])
        self.assertIn('Could not authenticate evidence base against source default-branch history',
                      result['evidence_errors'])
        self.evidence['base_commit'] = self.task['source']['commit']
        result = self.verify()
        self.assertFalse(result['technical_evidence_valid'])
        self.assertIn('Implementation changes a path outside reviewed scope: docs/stacked.md',
                      result['evidence_errors'])

    def test_in_scope_unpublished_stack_validates_from_a_published_base(self):
        stacked = self.stack('src/stacked.rs')
        self.evidence['base_commit'] = self.task['source']['commit']
        result = self.verify()
        self.assertTrue(result['technical_evidence_valid'], result['evidence_errors'])
        self.assertTrue(result['independent_review']['valid'])
        self.assertNotIn(stacked, str(self.client.calls))


if __name__ == '__main__':
    unittest.main()
