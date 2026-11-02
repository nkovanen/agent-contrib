"""Static checks of the two owned Action YAML files (#11). Line-based: no YAML dependency, so the files stay in a
small block-style subset that these checks enforce first. Not a linter for arbitrary workflows."""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
ACTION = ROOT / 'actions' / 'verify' / 'action.yml'
WORKFLOW = ROOT / 'docs' / 'examples' / 'agent-contrib-verify.yml'
# The only key syntax the scanner understands: plain keys. Quoted, complex (?) or other keys are rejected,
# so a step key such as 'run' cannot hide from the checks below (MA-10).
KEY_LINE = re.compile(r' *(- )?([A-Za-z0-9_][A-Za-z0-9_-]*):( .*)?')
SEQUENCE_ITEM = re.compile(r' *- [A-Za-z0-9_][A-Za-z0-9_.-]*')
STEP_ACTIONS = (re.compile(r'actions/checkout@[0-9a-f]{40}'), re.compile(r'nkovanen/agent-contrib/actions/verify@[0-9a-f]{40}'))
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
        key = KEY_LINE.fullmatch(line)
        if not key and not SEQUENCE_ITEM.fullmatch(line):
            errors.append('unsupported line or key syntax: ' + line.strip())
        elif re.search(r':\s*[&*!|>]|:\s*[\[{]|^\s*<<:|^---', line):
            errors.append('outside the block-style subset: ' + line.strip())
    return errors


def keys(lines):
    return [match.group(2) for match in map(KEY_LINE.fullmatch, lines) if match]


def steps(lines):
    """Each step as its list of lines, from the single steps: block."""
    start = next((i for i, line in enumerate(lines) if line.strip() == 'steps:'), None)
    if start is None or sum(line.strip() == 'steps:' for line in lines) != 1:
        return None
    body = []
    for line in lines[start + 1:]:
        if indent(line) <= indent(lines[start]):
            break
        body.append(line)
    depth = min((indent(line) for line in body), default=0)
    out = []
    for line in body:
        if indent(line) == depth and line.lstrip().startswith('- '):
            out.append([line])
        elif out:
            out[-1].append(line)
        else:
            return None
    return out


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
    if 'run' in keys(lines):
        errors.append('the example workflow runs no shell steps')
    found = steps(lines)
    uses = [re.sub(r' +#.*', '', step[0].split('uses:', 1)[1]).strip() if 'uses:' in step[0] else None
            for step in found or []]
    if len(uses) != 2 or not all(value and pattern.fullmatch(value) for value, pattern in zip(uses, STEP_ACTIONS)):
        errors.append('steps must be exactly the pinned checkout, then this action')
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
    if run_values(lines) != [RUN_COMMAND] or keys(lines).count('run') != 1 or len(steps(lines) or []) != 1:
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
    'single-quoted run key': ('          checkout-path: pr-head\n',
                              '          checkout-path: pr-head\n      - \'run\': echo "${{ github.event.pull_request.title }}"\n'),
    'double-quoted run key': ('          checkout-path: pr-head\n',
                              '          checkout-path: pr-head\n      - "run": echo "${{ github.event.pull_request.title }}"\n'),
    'complex run key': ('          checkout-path: pr-head\n',
                        '          checkout-path: pr-head\n      - ? run\n        : echo "${{ github.head_ref }}"\n'),
    'PR code step': ('          checkout-path: pr-head\n', '          checkout-path: pr-head\n      - run: python3 pr-head/setup.py\n'),
    'extra pinned action': ('          checkout-path: pr-head\n',
                            '          checkout-path: pr-head\n      - uses: someone/tool@0123456789abcdef0123456789abcdef01234567\n'),
    'action before checkout': ('      - uses: actions/checkout@', '      - uses: someone/tool@0123456789abcdef0123456789abcdef01234567\n'
                                                                 '      - uses: actions/checkout@'),
    # These two sit inside an allowed step, so only the key grammar or the run-key rule can reject them.
    'quoted key inside a step': ('          lfs: false\n',
                                 '          lfs: false\n          \'run\': echo "${{ github.event.pull_request.title }}"\n'),
    'run key inside a step': ('          lfs: false\n', '          lfs: false\n        run: python3 pr-head/setup.py\n'),
    'block scalar': ('          checkout-path: pr-head\n', '          checkout-path: pr-head\n      - run: |\n          echo hi\n'),
}
ACTION_MUTANTS = {
    'input in run': (RUN_COMMAND, 'python3 -I "$GITHUB_ACTION_PATH/report.py" "${{ inputs.checkout-path }}"'),
    'env file write': (RUN_COMMAND, 'echo "X=1" >> "$GITHUB_ENV"'),
    'second step': ('      run: ' + RUN_COMMAND + '\n',
                    '      run: ' + RUN_COMMAND + '\n    - uses: actions/cache@0123456789abcdef0123456789abcdef01234567\n'),
    'event env': ('        AGENT_CONTRIB_CHECKOUT: ${{ inputs.checkout-path }}\n',
                  '        AGENT_CONTRIB_CHECKOUT: ${{ inputs.checkout-path }}\n        TITLE: ${{ github.event.pull_request.title }}\n'),
    'docker': ('using: composite', 'using: docker'),
    'quoted run key': ('      run: ' + RUN_COMMAND + '\n', '      run: ' + RUN_COMMAND + '\n    - name: x\n      shell: bash\n'
                       '      \'run\': echo "${{ github.event.pull_request.title }}"\n'),
    'second run step': ('      run: ' + RUN_COMMAND + '\n', '      run: ' + RUN_COMMAND + '\n    - name: x\n      shell: bash\n'
                        '      run: python3 "$GITHUB_WORKSPACE/pr-head/setup.py"\n'),
}


class KeyGrammarTests(unittest.TestCase):
    def test_only_plain_keys_and_items_are_accepted(self):
        for line in ("'run': x", '"run": x', '? run', 'run : x', '- \'uses\': a/b@c', 'run:x', '!!str run: x', '  continued text'):
            with self.subTest(line=line):
                self.assertTrue(subset(line + '\n'))
        for line in ('run: x', '- uses: a/b@c', '  - opened', 'with:', 'key-name_1: "quoted value"'):
            with self.subTest(line=line):
                self.assertEqual(subset(line + '\n'), [])


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
