"""The instruction allow-list feeds instructions_sha256 in every contract and mandate: it is frozen.

Policy-only files (AI_POLICY.md, SECURITY.md, CONTRIBUTING.rst, owner defaults ...) belong to the separate
policy inventory. Changing this golden invalidates existing contracts; it needs a new schema, not an edit.
"""
import base64
import unittest

from agent_contribute import core
from tests.test_protocol import FakeGitHub

TREE = ['README.md', 'readme.MD', 'AGENTS.md', 'pkg/AGENTS.md', 'CLAUDE.md', 'x/claude.md', 'CONTRIBUTING.md',
        'docs/CONTRIBUTING.md', 'CONTRIBUTING.rst', 'CONTRIBUTE.md', 'CODE_OF_CONDUCT.md', '.github/CODE_OF_CONDUCT.md',
        'SECURITY.md', '.github/SECURITY.md', 'AI_POLICY.md', 'ai-policy.md', '.github/copilot-instructions.md',
        '.cursorrules', '.github/pull_request_template.md', '.github/PULL_REQUEST_TEMPLATE/feature.md',
        'docs/architecture.md', 'docs/index.md', 'docs/README.md', 'specs/README.md', 'spec/readme.md',
        'GOVERNANCE.md', 'SUPPORT.md', 'docs/README.rst', 'src/main.py']
LOADED = ['README.md', 'readme.MD', 'AGENTS.md', 'pkg/AGENTS.md', 'CLAUDE.md', 'x/claude.md', 'CONTRIBUTING.md',
          'docs/CONTRIBUTING.md', 'CODE_OF_CONDUCT.md', '.github/CODE_OF_CONDUCT.md',
          '.github/pull_request_template.md', 'docs/architecture.md', 'docs/index.md', 'docs/README.md',
          'specs/README.md', 'spec/readme.md']


class SelectionGitHub(FakeGitHub):
    def request(self, endpoint):
        path = endpoint.split('?')[0]
        if '/git/trees/' in path:
            self.calls.append(endpoint)
            return {'truncated': False, 'tree': [{'path': p, 'type': 'blob'} for p in TREE]}
        if '/contents/' in path:
            self.calls.append(endpoint)
            name = path.split('/contents/')[1]
            return {'encoding': 'base64', 'content': base64.b64encode(('text of ' + name).encode()).decode()}
        return super().request(endpoint)


class InstructionSelectionTests(unittest.TestCase):
    def test_instruction_allow_list_and_hash_are_frozen(self):
        snapshot = core.repository_snapshot('acme/photos', SelectionGitHub())
        self.assertEqual([item['path'] for item in snapshot['instructions']], LOADED)
        self.assertEqual(snapshot['instructions_sha256'], FROZEN)


FROZEN = '6249bd1193fc96f5b5c038cd4a54481306ce26477d74d970fc568367941b8311'  # computed at e53e894

if __name__ == '__main__':
    unittest.main()
