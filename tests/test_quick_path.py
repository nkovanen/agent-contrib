"""The workflow starts with a short quick path that defers to the detailed rules, without duplicates."""
import importlib.resources
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

    def test_quick_path_states_every_stop_point_and_defers_to_the_detail(self):
        section = ' '.join(quick_path().split())
        self.assertIn('**Stop and report', section)
        for point in ('bare help request', 'repository policy step', 'overlap', 'incomplete',
                      'no human/host-issued mandate', 'explicit execution authorization',
                      'publication needs its own user authorization', 'never merge'):
            with self.subTest(point=point):
                self.assertIn(point, section)
        self.assertIn('never overrides', section)


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
