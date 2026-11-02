"""Static checks of the two owned Action YAML files (#11). Line-based: no YAML dependency, so the files stay in a
small block-style subset that these checks enforce first. Not a linter for arbitrary workflows."""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
ACTION = ROOT / 'actions' / 'verify' / 'action.yml'
WORKFLOW = ROOT / 'docs' / 'examples' / 'agent-contrib-verify.yml'
PINNED = re.compile(r'\s*(- )?uses: [A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(/[A-Za-z0-9_./-]+)?@[0-9a-f]{40}( +#.*)?')
RUN_COMMAND = 'python3 -I "$GITHUB_ACTION_PATH/report.py"'


def indent(line):
    return len(line) - len(line.lstrip(' '))


def code_lines(text):
    return [line for line in text.split('\n') if line.strip() and not line.lstrip().startswith('#')]


def run_values(lines):
    """Every run: value, inline or block scalar."""
    values = []
    for i, line in enumerate(lines):
        match = re.fullmatch(r'(\s*)(- )?run:\s*(.*)', line)
        if not match:
            continue
        value = match.group(3)
        if value[:1] in ('|', '>'):
            depth = indent(line) + (2 if match.group(2) else 0)
            block = []
            for nxt in lines[i + 1:]:
                if indent(nxt) <= depth:
                    break
                block.append(nxt)
            value = '\n'.join(block)
        values.append(value)
    return values


def block(lines, key, depth):
    """Lines nested under the first `key:` at exactly this indentation."""
    for i, line in enumerate(lines):
        if indent(line) == depth and line.strip() == key + ':':
            out = []
            for nxt in lines[i + 1:]:
                if indent(nxt) <= depth:
                    break
                out.append(nxt)
            return out
    return None


def subset(text):
    errors = []
    if '\t' in text or '\r' in text:
        errors.append('tabs or carriage returns')
    for line in code_lines(text):
        if re.search(r':\s*[&*]\w|:\s*[\[{]|^\s*<<:|^---', line):
            errors.append('outside the block-style subset: ' + line.strip())
    return errors


def common(text):
    lines = code_lines(text)
    errors = subset(text)
    errors += ['expression in run: ' + value for value in run_values(lines) if '${{' in value]
    for line in lines:
        if 'uses:' in line and not PINNED.fullmatch(line):
            errors.append('unpinned uses: ' + line.strip())
        for forbidden in ('secrets.', 'GITHUB_ENV', 'GITHUB_PATH', 'GITHUB_OUTPUT', 'actions/cache', 'write-all',
                          'pull_request_target', 'workflow_run', 'issue_comment'):
            if forbidden in line:
                errors.append(f'forbidden {forbidden}: ' + line.strip())
        if re.search(r':\s*write\b', line):
            errors.append('write permission: ' + line.strip())
    return errors, lines


def lint_workflow(text):
    errors, lines = common(text)
    triggers = block(lines, 'on', 0)
    if triggers is None or [line.strip() for line in triggers if indent(line) == 2] != ['pull_request:']:
        errors.append('triggers must be pull_request only')
    if sum(line.strip().startswith('permissions:') for line in lines) != 1 or \
            [line.strip() for line in block(lines, 'permissions', 0) or []] != ['contents: read']:
        errors.append('permissions must be exactly contents: read, once, at the top level')
    checkout = [i for i, line in enumerate(lines) if 'uses: actions/checkout@' in line]
    required = {'persist-credentials: false', 'submodules: false', 'lfs: false',
                'ref: ${{ github.event.pull_request.head.sha }}'}
    for i in checkout:
        settings = {line.strip() for line in block(lines[i + 1:], 'with', indent(lines[i]) + 2) or []}
        if not required <= settings:
            errors.append('checkout settings missing: ' + ', '.join(sorted(required - settings)))
    if not checkout:
        errors.append('no checkout step')
    return errors


def lint_action(text):
    errors, lines = common(text)
    if [line.strip() for line in lines if line.strip().startswith('using:')] != ['using: composite']:
        errors.append('must be a composite action')
    if run_values(lines) != [RUN_COMMAND]:
        errors.append('exactly one run step running the report script')
    if any('uses:' in line for line in lines):
        errors.append('the action must not call other actions')
    env = [line.strip() for line in block(lines, 'env', 6) or []]
    if env != ['AGENT_CONTRIB_CHECKOUT: ${{ inputs.checkout-path }}']:
        errors.append('unexpected step environment: ' + ', '.join(env))
    return errors


class OwnedFileTests(unittest.TestCase):
    def test_owned_files_pass(self):
        self.assertEqual(lint_action(ACTION.read_text('utf-8')), [])
        self.assertEqual(lint_workflow(WORKFLOW.read_text('utf-8')), [])

    def test_no_github_event_expression_reaches_a_run_step(self):
        for path in (ACTION, WORKFLOW):
            lines = code_lines(path.read_text('utf-8'))
            values = run_values(lines)
            self.assertTrue(values or path == WORKFLOW)
            for value in values:
                self.assertNotIn('${{', value)
                self.assertNotRegex(value, r'github\.(event|head_ref)')

    def test_sdist_carries_the_action_files(self):
        manifest = (ROOT / 'MANIFEST.in').read_text('utf-8')
        self.assertIn('recursive-include actions *.py *.yml', manifest)
        self.assertIn('include docs/examples/*.yml', manifest)


WORKFLOW_MUTANTS = {
    'event in inline run': ('          checkout-path: pr-head\n',
                            '          checkout-path: pr-head\n      - run: echo "${{ github.event.pull_request.title }}"\n'),
    'head_ref in block run': ('          checkout-path: pr-head\n',
                              '          checkout-path: pr-head\n      - name: x\n        run: |\n'
                              '          echo ok\n          git switch "${{ github.head_ref }}"\n'),
    'unpinned checkout': ('actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1', 'actions/checkout@v4'),
    'write-all': ('permissions:\n  contents: read\n', 'permissions: write-all\n'),
    'contents write': ('  contents: read\n', '  contents: write\n'),
    'extra scope': ('  contents: read\n', '  contents: read\n  pull-requests: read\n'),
    'job permissions': ('    runs-on: ubuntu-latest\n', '    runs-on: ubuntu-latest\n    permissions:\n      contents: read\n'),
    'pull_request_target': ('  pull_request:\n', '  pull_request_target:\n'),
    'second trigger': ('  pull_request:\n', '  push:\n  pull_request:\n'),
    'persisted credentials': ('          persist-credentials: false\n', '          persist-credentials: true\n'),
    'submodules': ('          submodules: false\n', '          submodules: recursive\n'),
    'merge ref': ('${{ github.event.pull_request.head.sha }}', '${{ github.sha }}'),
    'secret': ('          checkout-path: pr-head\n', '          checkout-path: pr-head\n          token: ${{ secrets.PAT }}\n'),
    'flow mapping': ('          checkout-path: pr-head\n', '          checkout-path: pr-head\n          extra: {a: b}\n'),
}
ACTION_MUTANTS = {
    'input in run': (RUN_COMMAND, 'python3 -I "$GITHUB_ACTION_PATH/report.py" "${{ inputs.checkout-path }}"'),
    'env file write': (RUN_COMMAND, 'echo "X=1" >> "$GITHUB_ENV"'),
    'second step': ('      run: ' + RUN_COMMAND + '\n',
                    '      run: ' + RUN_COMMAND + '\n    - uses: actions/cache@0123456789abcdef0123456789abcdef01234567\n'),
    'event env': ('        AGENT_CONTRIB_CHECKOUT: ${{ inputs.checkout-path }}\n',
                  '        AGENT_CONTRIB_CHECKOUT: ${{ inputs.checkout-path }}\n        TITLE: ${{ github.event.pull_request.title }}\n'),
    'docker': ('using: composite', 'using: docker'),
}


class SeededMutantTests(unittest.TestCase):
    def test_every_seeded_violation_is_rejected(self):
        for name, path, lint, mutants in (('workflow', WORKFLOW, lint_workflow, WORKFLOW_MUTANTS),
                                          ('action', ACTION, lint_action, ACTION_MUTANTS)):
            text = path.read_text('utf-8')
            for mutant, (old, new) in mutants.items():
                with self.subTest(file=name, mutant=mutant):
                    self.assertIn(old, text)
                    self.assertTrue(lint(text.replace(old, new, 1)), mutant)


if __name__ == '__main__':
    unittest.main()
