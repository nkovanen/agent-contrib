"""The Skill stays thin but names the first command and the quick path."""
import importlib.resources
import re
import unittest


def resource(path):
    return importlib.resources.files('agent_contribute').joinpath(path).read_text('utf-8')


class SkillTests(unittest.TestCase):
    def test_skill_names_the_first_command_and_the_quick_path(self):
        skill = resource('adapters/agent-contribute/SKILL.md')
        self.assertIn('agent-contrib --format text instructions', skill)
        self.assertIn('Quick path', skill)
        flat = ' '.join(skill.split())
        # An older CLI's workflow has no quick path; the Skill must not send the agent looking for one.
        self.assertIn('"Quick path" section if it has one; otherwise follow the returned workflow directly', flat)
        self.assertLess(len(skill), 2000)
        self.assertIsNone(re.search(r'--signals|discover owner', skill))  # the flow lives in the workflow


if __name__ == '__main__':
    unittest.main()
