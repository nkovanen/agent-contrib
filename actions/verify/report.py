"""Passive, report-only Agent Contrib check of one pull request (GitHub Action, slice 1, #11).

Reads only the pull_request event payload and the PR-head checkout. It makes no
GitHub API calls, never runs PR code, writes only the job summary and fixed log
lines, and exits 0 whatever it finds: job status carries no consistency meaning.
Design: docs/design/2026-11-02-maintainer-action.md.
"""
import os
import re
import sys
from pathlib import Path

if sys.version_info < (3, 10):
    print('Agent Contrib action needs Python 3.10 or newer')
    sys.exit(1)

ROOT = str(Path(__file__).resolve().parents[2])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)  # python3 -I leaves the checkout and working directory off sys.path

from agent_contribute import core, textfmt, workspace  # noqa: E402

MAX_BODY = 65536
MAX_BLOCK = 32 * 1024
MAX_ITEMS = 50
MAX_SUMMARY = 64 * 1024
MAX_DETAILS = 200  # detail lines in the whole summary; with MAX_ITEMS checks this stays far below MAX_SUMMARY
FENCE = '```'
TASK, EVIDENCE = 'agent-contrib-task', 'agent-contrib-evidence'
HEX40, HEX64 = re.compile('[0-9a-f]{40}'), re.compile('[0-9a-f]{64}')
RESULTS = {'no-inconsistency': 'No inconsistency found in the checks below',
           'inconsistent': '{} inconsistencies found', 'not-checked': 'Not checked: {}'}
DISCLAIMERS = (
    'Evidence is self-attested: a match means the record describes this PR, not that its tests, review or sign-off happened.',
    'Verification is not review, approval, AI-policy compliance or authorization to merge.',
    'Job status carries no meaning; only this result does. A PR that changes .github/ controls this workflow, '
    'so its report is meaningless.',
    'Author, implementer and reviewer names are not checked.')
NOT_EVALUATED = (
    'Live source freshness (issue, instructions, default branch, policy)', 'Overlap with other open PRs',
    'Repository approval status', 'Numeric source identity (repository, owner and issue IDs)',
    'Authorization stages (mandate, credential, permission)', 'Whether recorded validations ran',
    'Review and sign-off truth', 'Artifact hashes', 'Merge compatibility with the base branch')
SCHEMA_01_NOTE = ('Head repository, head ref and base ref are not bound by schema 0.1',)


class NotChecked(Exception):
    """A fixed reason; never carries untrusted text."""


def parse_blocks(body):
    """Exactly one task block and at most one evidence block, found anywhere in the raw body."""
    if body is None:
        raise NotChecked('no Agent Contrib contract in the PR body')
    if len(body) > MAX_BODY:
        raise NotChecked('the PR body exceeds 65,536 characters')
    lines = body.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    found = {}
    for kind in (TASK, EVIDENCE):
        marker = FENCE + kind
        # Any mention counts, so a hidden, quoted or indented copy cannot sit behind the parsed block.
        mentions = [i for i, line in enumerate(lines) if marker in line]
        if len(mentions) > 1:
            raise NotChecked(f'more than one {kind} block')
        if not mentions:
            continue
        start = mentions[0]
        if lines[start].rstrip(' \t') != marker:
            raise NotChecked(f'the {kind} fence must be a line of its own starting in column 0')
        end = next((i for i in range(start + 1, len(lines)) if lines[i].rstrip(' \t') == FENCE), None)
        if end is None:
            raise NotChecked(f'the {kind} block is not closed')
        text = '\n'.join(lines[start + 1:end])
        if len(text.encode('utf-8', errors='surrogatepass')) > MAX_BLOCK:
            raise NotChecked(f'the {kind} block exceeds 32 KiB')
        try:
            found[kind] = core.strict_json(text)
        except (core.ProtocolError, ValueError, RecursionError):
            raise NotChecked(f'the {kind} block is not valid strict JSON') from None
    if TASK not in found:
        raise NotChecked('no Agent Contrib contract in the PR body')
    return found[TASK], found.get(EVIDENCE)


def _field(value, key, kind, check=None):
    item = value.get(key) if isinstance(value, dict) else None
    if not isinstance(item, kind) or isinstance(item, bool) or (check and not check(item)):
        raise NotChecked('the event payload lacks pull request facts')
    return item


def _repository(value):
    return (_field(value, 'full_name', str, lambda name: 0 < len(name) <= 200),
            _field(value, 'id', int, lambda number: number > 0))


def pr_facts(event):
    pr = _field(event, 'pull_request', dict)
    head, base = _field(pr, 'head', dict), _field(pr, 'base', dict)
    body = pr.get('body')
    if body is not None and not isinstance(body, str):
        raise NotChecked('the event payload lacks pull request facts')
    if 'repo' not in head:
        raise NotChecked('the event payload lacks pull request facts')
    head_repo = head['repo']  # null when the head repository was deleted: a known gap, not a match
    return {'number': _field(pr, 'number', int, lambda number: number > 0), 'body': body,
            'head_sha': _field(head, 'sha', str, HEX40.fullmatch), 'head_ref': _field(head, 'ref', str),
            'head_repo': None if head_repo is None else _repository(head_repo),
            'base_ref': _field(base, 'ref', str), 'base_repo': _repository(_field(base, 'repo', dict))}


def check(name, state, details=()):
    return {'name': name, 'state': state, 'details': list(details)}


def compare(name, expected, actual, casefold=False, labels=('contract', 'PR')):
    same = (expected.casefold() == actual.casefold() if casefold and isinstance(expected, str) and isinstance(actual, str)
            else type(expected) is type(actual) and expected == actual)
    return check(name, 'match' if same else 'mismatch', () if same else [list(zip(labels, (expected, actual)))])


def route_checks(task, facts, workflow_repository):
    """Bind the PR route in the event payload to the contract (MA-02); missing data is not evaluated."""
    base_name, base_id = facts['base_repo']
    execution = task['execution']
    checks = [compare('Base repository is the workflow repository', workflow_repository, base_name, casefold=True,
                      labels=('workflow', 'PR')),
              compare('source.repository is the base repository', task['source']['repository'], base_name, casefold=True),
              compare('execution.target_repository is the base repository', execution['target_repository'], base_name,
                      casefold=True)]
    # Applies to every schema version: without the head repository the PR route is not fully known (MA-07).
    deleted = facts['head_repo'] is None
    checks.append(check('Head repository is known', 'not-evaluated' if deleted else 'match',
                        [[('', 'the head repository was deleted')]] if deleted else ()))
    if task['schema_version'] != '0.2':
        same = execution['mode'] == 'upstream-contribution'
        checks.append(check('execution.mode is upstream-contribution', 'match' if same else 'mismatch',
                            () if same else [[('contract', execution['mode'])]]))
        return checks
    checks += [compare('execution.target_repository_id is the base repository ID', execution['target_repository_id'], base_id),
               compare('execution.base_ref is the PR base ref', execution['base_ref'], facts['base_ref'])]
    names = ('Head repository is execution.head_repository', 'Head repository ID is execution.head_repository_id',
             'Head ref is execution.head_ref')
    if deleted:
        return checks + [check(name, 'not-evaluated', [[('', 'the head repository was deleted')]]) for name in names]
    head_name, head_id = facts['head_repo']
    return checks + [compare(names[0], execution['head_repository'], head_name, casefold=True),
                     compare(names[1], execution['head_repository_id'], head_id),
                     compare(names[2], execution['head_ref'], facts['head_ref'])]


def _has_commit(directory, sha):
    try:
        return core.git_read(directory, 'cat-file', '-t', sha) == 'commit'
    except core.ProtocolError:
        return False


def _ancestor(name, directory, older, newer):
    """Only a completed count proves a negative (MA-09); a failed read or a shallow graft proves nothing."""
    if not _has_commit(directory, older) or not _has_commit(directory, newer):
        return check(name, 'not-evaluated', [[('', 'a commit is missing from the checkout history')]])
    try:
        if core.git_read(directory, 'rev-parse', '--is-shallow-repository') != 'false':
            return check(name, 'not-evaluated', [[('', 'the checkout history is shallow')]])
        # Commits reachable from older but not from newer: zero exactly when older is an ancestor of newer.
        outside = core.git_read(directory, 'rev-list', '--count', older, '--not', newer)
    except core.ProtocolError:
        return check(name, 'not-evaluated', [[('', 'the ancestry read failed')]])
    if not outside.isdigit():
        return check(name, 'not-evaluated', [[('', 'the ancestry read failed')]])
    return check(name, 'match' if outside == '0' else 'mismatch')


def evidence_checks(task, evidence, facts, directory, head):
    checks = [compare('Evidence git_head is the PR head', evidence['git_head'], facts['head_sha'], labels=('evidence', 'PR')),
              compare('Evidence git_tree is the head tree', evidence['git_tree'],
                      core.git_read(directory, 'rev-parse', head + '^{tree}'), labels=('evidence', 'checkout')),
              compare('Evidence contract_sha256 is the contract hash', evidence['contract_sha256'], core.canonical_hash(task),
                      labels=('evidence', 'contract')),
              check('Evidence records a clean worktree', 'match' if evidence['worktree_clean'] is True else 'mismatch'),
              _ancestor('Evidence base_commit is an ancestor of the PR head', directory, evidence['base_commit'], head),
              _ancestor('source.commit is an ancestor of evidence base_commit', directory, task['source']['commit'],
                        evidence['base_commit'])]
    scope = workspace.scope_check(task, directory, evidence['base_commit'])
    if scope['violations']:
        details = [[('', violation['path']), ('', violation['rule'])] for violation in scope['violations']]
        checks.append(check('Changes stay within the contract scope', 'mismatch', details))
    elif scope['errors']:
        checks.append(check('Changes stay within the contract scope', 'not-evaluated', [[('', e)] for e in scope['errors']]))
    else:
        checks.append(check('Changes stay within the contract scope', 'match'))
    return checks


def checkout_root(environ):
    workspace_dir, relative = environ.get('GITHUB_WORKSPACE', ''), environ.get('AGENT_CONTRIB_CHECKOUT', 'pr-head')
    path = Path(relative)
    if not workspace_dir or not relative or path.is_absolute() or '..' in path.parts:
        raise NotChecked('the checkout path must be a relative path inside the workspace')
    root = Path(workspace_dir).resolve()
    directory = (root / path).resolve()
    if not directory.is_relative_to(root) or not directory.is_dir():
        raise NotChecked('the checkout path must be a relative path inside the workspace')
    return str(directory)


def build(environ):
    """The report model. Every failure before the checks is a fixed not-checked reason."""
    facts = None
    try:
        if environ.get('GITHUB_EVENT_NAME') != 'pull_request':
            raise NotChecked('this is not a pull_request event')
        repository = environ.get('GITHUB_REPOSITORY', '')
        if not repository:
            raise NotChecked('GITHUB_REPOSITORY is not set')
        try:
            event = core.read_json(environ.get('GITHUB_EVENT_PATH', ''))
        except (core.ProtocolError, OSError, ValueError):
            raise NotChecked('the event payload cannot be read') from None
        facts = pr_facts(event)
        directory = checkout_root(environ)
        task, evidence = parse_blocks(facts['body'])
        try:
            core.require_worktree_root(directory)
            core.require_safe_config(directory)
            head = core.current_head(directory)
        except core.ProtocolError:
            raise NotChecked('the checkout is not a usable Git worktree') from None
        if head != facts['head_sha']:
            raise NotChecked('the checkout is not the PR head commit')
    except NotChecked as exc:
        return not_checked(str(exc), facts)
    contract_errors = core.validate_contract(task)
    version = task.get('schema_version') if isinstance(task, dict) else None
    documents = [check(f'Contract matches the task schema {version if version in ("0.1", "0.2") else ""}'.rstrip(),
                       'mismatch' if contract_errors else 'match', [[('', error)] for error in contract_errors])]
    sections = [('Documents', documents)]
    if evidence is None:
        return not_checked('No evidence block in the PR body', facts, sections)
    # Validated on its own (MA-08): an invalid contract does not stop the evidence check, and a check that
    # cannot run is not evaluated rather than an empty, matching list.
    name = 'Evidence matches the evidence schema of the contract version'
    if version not in core.SUPPORTED_SCHEMA_VERSIONS:
        evidence_errors = None
        documents.append(check(name, 'not-evaluated', [[('', 'the contract schema version is unsupported')]]))
    else:
        evidence_errors = (['$.schema_version: differs from the contract'] if not isinstance(evidence, dict)
                           or evidence.get('schema_version') != version
                           else core.schema_errors(evidence, core.bundled_schema('evidence', version)))
        documents.append(check(name, 'mismatch' if evidence_errors else 'match',
                               [[('', error)] for error in evidence_errors]))
    if not contract_errors:
        sections.append(('PR route binding', route_checks(task, facts, repository)))
    if not contract_errors and evidence_errors == []:
        sections.append(('Evidence binding and scope', evidence_checks(task, evidence, facts, directory, head)))
    return finish(facts, sections, version)


def not_checked(reason, facts=None, sections=()):
    return {'result': 'not-checked', 'reason': reason, 'mismatches': 0, 'sections': list(sections),
            'pr': facts and facts['number'], 'head': facts and facts['head_sha'], 'version': None}


def finish(facts, sections, version):
    states = [item['state'] for _, checks in sections for item in checks]
    mismatches = states.count('mismatch')
    model = {'result': 'inconsistent' if mismatches else 'no-inconsistency', 'reason': '', 'mismatches': mismatches,
             'sections': sections, 'pr': facts['number'], 'head': facts['head_sha'], 'version': version}
    if not mismatches and (states.count('not-evaluated') or len(sections) < 3):
        model.update(result='not-checked', reason=f'{states.count("not-evaluated")} checks could not be evaluated')
    return model


def code(value):
    """One inline code span: one line, no control or format characters, no backticks, bounded."""
    text = textfmt.line(value, 200).replace('`', "'")
    return '`' + (text or '(empty)') + '`'


def _detail(pairs):
    return '  - ' + ', '.join((label + ' ' if label else '') + code(value) for label, value in pairs)


def render(model):
    result = model['result']
    wording = RESULTS[result].format(model['mismatches'] if result == 'inconsistent' else model['reason'])
    lines = ['## Agent Contrib report (report-only)', '', f'**Result: {textfmt.line(wording, 200)}**', '']
    if isinstance(model.get('pr'), int) and isinstance(model.get('head'), str) and HEX40.fullmatch(model['head']):
        lines += [f'- PR {model["pr"]} at head `{model["head"]}`', '']
    lines += ['- ' + statement for statement in DISCLAIMERS] + ['']
    budget = MAX_DETAILS
    for title, checks in model['sections']:
        lines += [f'### {title}', '']
        for item in checks[:MAX_ITEMS]:
            lines.append(f'- {item["state"].replace("-", " ")}: {item["name"]}')
            details = [[('', d)] if isinstance(d, str) else d for d in item['details']]
            shown = min(len(details), MAX_ITEMS, budget)
            budget -= shown
            lines += [_detail(pairs) for pairs in details[:shown]]
            if len(details) > shown:
                lines.append(f'  - {len(details) - shown} more not shown')
        if len(checks) > MAX_ITEMS:
            lines.append(f'- {len(checks) - MAX_ITEMS} more checks not shown')
        lines.append('')
    if model.get('version') == '0.1':
        lines += ['### Notes', ''] + ['- ' + note for note in SCHEMA_01_NOTE] + ['']
    lines += ['### Not evaluated in this version', ''] + ['- ' + item for item in NOT_EVALUATED]
    text = '\n'.join(lines) + '\n'
    if len(text.encode()) > MAX_SUMMARY:
        raise ValueError('report exceeds the summary cap')  # unreachable with the caps; main reports an internal error
    return text


def main(environ=None):
    environ = os.environ if environ is None else environ
    try:
        model = build(environ)
        text = render(model)
    except Exception:  # never echo a traceback: it could carry attacker-controlled values
        model = not_checked('internal error in the action')
        text = render(model)
    try:
        with open(environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as handle:
            handle.write(text)
        print('Agent Contrib report written to the job summary: ' + model['result'])
    except (KeyError, OSError):
        print('Agent Contrib report could not be written: GITHUB_STEP_SUMMARY is unavailable')
    return 0


if __name__ == '__main__':
    try:
        os.chdir(os.environ.get('RUNNER_TEMP') or os.path.expanduser('~'))
    except OSError:
        pass
    sys.exit(main())
