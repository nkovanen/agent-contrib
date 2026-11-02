"""Static checks of the PROPOSED PyPI release workflow (docs/examples/release-pypi.yml, #26).

It reuses the line-based scanner of tests/test_workflow_lint.py, so the file stays in the same small block-style
subset. These checks cover this one owned file; they are not a linter for arbitrary workflows."""
import pathlib
import re
import unittest

from tests.test_workflow_lint import KEY_LINE, PINNED, block, code_lines, indent, keys, run_values, steps, subset

ROOT = pathlib.Path(__file__).resolve().parents[1]
RELEASE = ROOT / 'docs' / 'examples' / 'release-pypi.yml'
ACTIONS = {'build': ['actions/checkout', 'actions/setup-python', 'actions/upload-artifact'],
           'publish': ['actions/download-artifact', 'actions/attest-build-provenance', 'pypa/gh-action-pypi-publish']}
PUBLISH_PERMISSIONS = ['contents: read', 'id-token: write', 'attestations: write']
# The only expression in the file outside if:/environment: values: the release tag, passed to run: through env:.
TAG_ENV = 'RELEASE_TAG: ${{ github.event.release.tag_name }}'


def job(lines, name):
    return block(block(lines, 'jobs', 0) or [], name, 2)


def lint(text):
    lines = code_lines(text)
    errors = subset(text)
    errors += ['expression in run: ' + value for value in run_values(lines) if '${{' in value]
    for line in lines:
        if 'uses:' in line and not PINNED.fullmatch(line):
            errors.append('unpinned uses: ' + line.strip())
        for forbidden in ('secrets.', 'GITHUB_ENV', 'GITHUB_PATH', 'GITHUB_OUTPUT', 'actions/cache', 'write-all',
                          'password', 'pull_request', 'workflow_dispatch', 'workflow_run', 'push:'):
            if forbidden in line:
                errors.append(f'forbidden {forbidden}: ' + line.strip())
        if '${{' in line and line.strip() != TAG_ENV:
            errors.append('unexpected expression: ' + line.strip())
    if [line.strip() for line in block(lines, 'on', 0) or []] != ['release:', 'types:', '- published']:
        errors.append('the only trigger is a published release')
    if [line.strip() for line in block(lines, 'permissions', 0) or []] != ['contents: read']:
        errors.append('workflow permissions must be exactly contents: read')
    if keys([line for line in block(lines, 'jobs', 0) or [] if indent(line) == 2]) != ['build', 'publish']:
        errors.append('jobs must be exactly build, then publish')
    build, publish = job(lines, 'build') or [], job(lines, 'publish') or []
    if 'permissions' in keys(build) or any('id-token' in line or 'attestations' in line for line in build):
        errors.append('the build job inherits contents: read only')
    if [line.strip() for line in block(publish, 'permissions', 4) or []] != PUBLISH_PERMISSIONS:
        errors.append('publish permissions must be exactly ' + ', '.join(PUBLISH_PERMISSIONS))
    if 'needs: build' not in [line.strip() for line in publish]:
        errors.append('publish needs build')
    if [line.strip() for line in block(publish, 'environment', 4) or []][:1] != ['name: pypi']:
        errors.append('publish runs in the protected pypi environment')
    for name, allowed in ACTIONS.items():
        used = [re.sub(r'@.*', '', step[0].split('uses:', 1)[1]).strip() for step in steps(job(lines, name) or []) or []
                if 'uses:' in step[0]]
        if [action for action in used if action in allowed] != used or not set(allowed) <= set(used):
            errors.append(f'{name} uses exactly ' + ', '.join(allowed))
    checkout = next((i for i, line in enumerate(lines) if 'uses: actions/checkout@' in line), None)
    settings = [line.strip() for line in block(lines[checkout + 1:], 'with', indent(lines[checkout]) + 2) or []] \
        if checkout is not None else []
    if 'persist-credentials: false' not in settings:
        errors.append('checkout must not persist credentials')
    builds = [value for value in run_values(lines) if re.match(r'python3? -m build\b', value)]
    if len(builds) != 1:
        errors.append('the distributions are built exactly once')
    if not any('tools/release_check.py --release --tag "$RELEASE_TAG"' in value for value in run_values(build)):
        errors.append('the build job checks the tag and dated CHANGELOG before building')
    return errors


class ReleaseWorkflowTests(unittest.TestCase):
    def test_proposed_workflow_passes(self):
        self.assertEqual(lint(RELEASE.read_text('utf-8')), [])

    def test_it_is_only_a_proposal_until_adopted_unchanged(self):
        self.assertIn('PROPOSED', RELEASE.read_text('utf-8').split('\n', 1)[0])
        workflows = ROOT / '.github' / 'workflows'
        others = [path.name for path in workflows.iterdir()
                  if path.name != 'release-pypi.yml' and ('pypi' in path.name.lower() or 'release' in path.name.lower())]
        self.assertEqual(others, [])
        adopted = workflows / 'release-pypi.yml'
        if adopted.exists():  # a maintainer's adopted copy must stay identical to the reviewed example
            self.assertEqual(adopted.read_text('utf-8'), RELEASE.read_text('utf-8'))

    def test_no_github_event_expression_reaches_a_run_step(self):
        for value in run_values(code_lines(RELEASE.read_text('utf-8'))):
            self.assertNotIn('${{', value)
            self.assertNotRegex(value, r'github\.(event|head_ref)')


MUTANTS = {
    'tag in run': ('run: python3 -I tools/release_check.py --release --tag "$RELEASE_TAG"',
                   'run: python3 -I tools/release_check.py --release --tag "${{ github.event.release.tag_name }}"'),
    'release name in run': ('        run: python -m unittest discover -v\n',
                            '        run: echo "${{ github.event.release.name }}"\n'),
    'quoted run key': ('        run: python -m unittest discover -v\n',
                       '        \'run\': echo "${{ github.event.release.body }}"\n'),
    'unpinned publish': ('pypa/gh-action-pypi-publish@7245906fb61fa33a13554f9d5fb856fe61758086',
                         'pypa/gh-action-pypi-publish@release/v1'),
    'extra pinned action': ('      - uses: pypa/gh-action-pypi-publish@',
                            '      - uses: someone/uploader@0123456789abcdef0123456789abcdef01234567\n'
                            '      - uses: pypa/gh-action-pypi-publish@'),
    'push trigger': ('on:\n  release:\n', 'on:\n  push:\n    tags:\n      - v*\n  release:\n'),
    'manual trigger': ('on:\n  release:\n', 'on:\n  workflow_dispatch:\n  release:\n'),
    'created releases': ('      - published\n', '      - created\n'),
    'workflow id-token': ('permissions:\n  contents: read\n', 'permissions:\n  contents: read\n  id-token: write\n'),
    'build id-token': ('    timeout-minutes: 20\n', '    timeout-minutes: 20\n    permissions:\n      id-token: write\n'),
    'contents write': ('      contents: read\n      id-token: write\n', '      contents: write\n      id-token: write\n'),
    'no environment': ('    environment:\n      name: pypi\n', '    environment:\n      name: other\n'),
    'token secret': ('    steps:\n      - uses: actions/download-artifact@',
                     '    env:\n      TOKEN: ${{ secrets.PYPI_TOKEN }}\n    steps:\n      - uses: actions/download-artifact@'),
    'api token input': ('      - uses: pypa/gh-action-pypi-publish@7245906fb61fa33a13554f9d5fb856fe61758086 # v1.14.3\n',
                        '      - uses: pypa/gh-action-pypi-publish@7245906fb61fa33a13554f9d5fb856fe61758086 # v1.14.3\n'
                        '        with:\n          password: x\n'),
    'second build': ('        run: python -m unittest discover -v\n',
                     '        run: python -m build --outdir other\n'),
    'persisted credentials': ('          persist-credentials: false\n', '          persist-credentials: true\n'),
    'no tag check': ('run: python3 -I tools/release_check.py --release --tag "$RELEASE_TAG"', 'run: python3 -I tools/release_check.py'),
    'publish without build': ('    needs: build\n', ''),
    # Each of these is rejected by one rule only.
    'build contents write': ('    timeout-minutes: 20\n', '    timeout-minutes: 20\n    permissions:\n      contents: write\n'),
    'expression in env only': ('        run: python -m unittest discover -v\n',
                               '        run: python -m unittest discover -v\n        env:\n'
                               '          TITLE: ${{ github.event.release.name }}\n'),
}


class SeededMutantTests(unittest.TestCase):
    def test_every_seeded_violation_is_rejected(self):
        text = RELEASE.read_text('utf-8')
        for name, (old, new) in MUTANTS.items():
            with self.subTest(mutant=name):
                self.assertIn(old, text)
                self.assertTrue(lint(text.replace(old, new, 1)), name)


if __name__ == '__main__':
    unittest.main()
