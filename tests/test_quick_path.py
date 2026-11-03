"""The workflow starts with a short quick path that defers to the detailed rules, without duplicates."""
import importlib.resources
import re
import unittest


def resource(path):
    return importlib.resources.files('agent_contribute').joinpath(path).read_text('utf-8')


def quick_path():
    text = resource('instructions.md')
    start = text.index('## Quick path')
    return text[start:text.index('\n## ', start + 1)]


class QuickPathTests(unittest.TestCase):
    def test_quick_path_comes_first_and_is_short(self):
        text = resource('instructions.md')
        self.assertLess(text.index('## Quick path'), text.index('## Start with discovery'))
        self.assertLessEqual(len(quick_path().strip().splitlines()), 40)

    def test_quick_path_names_the_command_sequence(self):
        section = ' '.join(quick_path().split())
        for command in ("agent-contrib --report-budget discover owner/repo --signals", '--responsiveness',
                        "agent-contrib inspect 'owner/repo#N' --ownership", 'the repository policy step',
                        "agent-contrib prepare 'owner/repo#N' --output task.json", '--schema-version 0.2',
                        'agent-contrib verify task.json --stage implementation',
                        'agent-contrib authorization-request task.json', 'scope-check', 'evidence init'):
            with self.subTest(command=command):
                self.assertIn(command, section)
        self.assertLess(section.index('discover owner/repo'), section.index("inspect 'owner/repo#N'"))
        self.assertLess(section.index("inspect 'owner/repo#N'"), section.index("prepare 'owner/repo#N'"))
        self.assertLess(section.index("prepare 'owner/repo#N'"), section.index('authorization-request'))

    def test_repository_policy_step_names_its_command_and_sections(self):
        # Dogfood 3 F43/F44: the step must say where it is and which command feeds it. Since policy-v2 the
        # repository policy report is default-on, so the step must not tell agents to pass the ignored --ai-policy.
        section = ' '.join(quick_path().split())
        self.assertIn("agent-contrib inspect 'owner/repo#N' --ownership", section)
        self.assertIn('the policy report is always added', section)
        self.assertNotIn('--ai-policy', section)
        text = resource('instructions.md')
        for heading in ('Start with discovery, then choose a contract version', 'Repository requirements'):
            with self.subTest(heading=heading):
                self.assertIn('"' + heading.split(',')[0] + '"', section)
                self.assertIn('\n## ' + heading, text)
        self.assertIn('`ai-policy-review`', section)

    def test_quick_path_states_every_stop_point_and_defers_to_the_detail(self):
        section = ' '.join(quick_path().split())
        self.assertIn('**Stop and report', section)
        for point in ('bare help request', 'repository policy step', 'overlap', 'incomplete',
                      'no human/host-issued mandate', 'explicit execution authorization',
                      'a gate in steps 6-8 is false', 'publication needs its own user authorization',
                      'final sign-off is pending'):
            with self.subTest(point=point):
                self.assertIn(point, section)
        self.assertIn('never overrides', section)


def steps():
    """Numbered quick-path steps, each flattened to one line."""
    parts = re.split(r'\n(?=\d\. )', quick_path().split('**Stop and report')[0])
    return {int(part[0]): ' '.join(part.split()) for part in parts if part[:1].isdigit()}


class QuickPathGateTests(unittest.TestCase):
    def test_editing_requires_authorization_and_the_passing_execution_gate(self):
        gate = next(text for text in steps().values() if text.startswith('6. '))
        self.assertIn("Edit only with the user's actual authorization and a passing gate", gate)
        self.assertIn('0.1: `execution_ready: true`', gate)
        self.assertIn('0.2: `agent-contrib verify task.json --stage implementation --host-context-stdin`', gate)
        self.assertIn('`implementation_ready: true`', gate)
        self.assertIn('host-issued context unchanged', gate)
        section = ' '.join(quick_path().split())
        self.assertLess(section.index('`implementation_ready: true`'), section.index('isolated branch'))

    def test_publication_requires_its_own_authorization_and_the_draft_gate(self):
        gate = steps()[7]
        self.assertIn('separate user authorization and a passing publication gate', gate)
        self.assertIn('0.1: `upstream_submission_ready: true`', gate)
        self.assertIn('--stage draft --host-context-stdin', gate)
        self.assertIn('`draft_create_ready: true`', gate)
        self.assertIn('as a draft PR only', gate)
        self.assertIn('`publication.verified: true`', gate)

    def test_completion_requires_a_separate_final_signoff_and_is_reported_pending_until_then(self):
        final = steps()[8]
        self.assertIn('separate, later human/host final sign-off', final)
        self.assertIn('--stage completion', final)
        self.assertIn('`completion_ready: true`', final)
        self.assertIn('pending acceptance', final)
        self.assertIn('Never mark the PR ready, merge or release', final)


class DriftAndObservationTests(unittest.TestCase):
    """A2-10: the workflow names drift where a stale contract matters, and the observation flags as report-only."""
    def test_quick_path_runs_drift_before_authorization_and_publication(self):
        self.assertIn('Run `agent-contrib drift task.json` before asking for any authorization', steps()[5])
        self.assertIn('Rerun `drift` first', steps()[7])
        self.assertIn('`--observe-ci`/`--observe-signatures` are optional reports', steps()[7])

    def test_detail_explains_drift_and_report_only_observations(self):
        text = ' '.join(resource('instructions.md').split())
        for phrase in ('`drifted: true` means re-review and re-prepare the contract',
                       'exit 1 with `complete: false` means the change is unknown, which is not a pass',
                       'They never change gates or the exit code'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)


class DeduplicationTests(unittest.TestCase):
    def test_canonical_json_recipe_and_precommit_rule_are_stated_once(self):
        text = ' '.join(resource('instructions.md').split())
        self.assertEqual(text.count("separators `(',', ':')`"), 1)
        self.assertEqual(text.count('Keep precommit evidence separately'), 0)
        self.assertEqual(text.count('run precommit checks before every commit'), 1)

    def test_core_discovery_limits_do_not_deny_the_ownership_report(self):
        text = ' '.join(resource('instructions.md').split())
        self.assertNotIn('It does not inspect timeline links', text)
        self.assertIn('`inspect --ownership` reports', text)

if __name__ == '__main__':
    unittest.main()
