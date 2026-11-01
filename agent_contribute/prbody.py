"""Render a PR description from the contract, evidence and verify gates. No GitHub writes."""
import re

from . import core, __version__

KEYWORD = re.compile(r'(?i)\b(clos|fix|resolv)(?=(?:e|es|ed|s)?\b)')


def md(value, limit=2000):
    """Quote untrusted text inert: no HTML, Markdown structure, mentions or closing keywords."""
    text = ' '.join(core.safe_text(str(value), limit).split())
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    text = re.sub(r'([\\`*_\[\]()!|~])', r'\\\1', text)
    # Zero-width space entities break mentions, references and closing keywords; the visible text is unchanged.
    text = re.sub(r'[@#]|(?<=:)//', lambda m: m.group() + '&#8203;' if m.group() != '//' else '&#8203;//', text)
    return KEYWORD.sub(lambda m: m.group(1)[0] + '&#8203;' + m.group(1)[1:], text)


def _gate(name, value):
    return f'- `{name}`: {"yes" if value is True else "no"}'


def render(task, verification, evidence=None, *, closes=False, assistant=None):
    source = task['source']
    reference = f'{source["repository"]}#{source["issue"]}'
    lines = ['## Summary', '', ('Closes ' if closes else 'Refs ') + reference, '',
             '**Objective:** ' + md(task['objective']), '',
             '**Scope:** allowed ' + ', '.join(md(p) for p in task['scope']['allowed_paths']) +
             '; prohibited ' + ', '.join(md(p) for p in task['scope']['prohibited_paths']), '',
             '## Acceptance criteria', '']
    observed = {item['id']: item for item in (evidence or {}).get('criteria', [])}
    for item in task['behavior_criteria']:
        record = observed.get(item['id'])
        status = md(record['status']) + ': ' + md(record['evidence']) if record else 'no evidence supplied'
        lines.append(f'- {md(item["id"])}: {md(item["description"])} ({status})')
    lines += ['', '## Validation', '']
    checks = {item['id']: item for item in (evidence or {}).get('validations', [])}
    for item in task['validation']:
        record = checks.get(item['id'])
        argv = md(' '.join(item['argv']))
        if record:
            lines.append(f'- {md(item["id"])} ({md(item["kind"])}): {argv}; status {md(record["status"])}, '
                         f'exit {md(record["exit_code"])}, tests run {md(record["tests_run"])}, skipped {md(record["skipped"])}')
        else:
            lines.append(f'- {md(item["id"])} ({md(item["kind"])}): {argv}; no result supplied')
    lines += ['', 'Evidence is self-attested by the contributor; the verifier does not prove that tests ran.', '',
              '## Review and sign-off', '']
    for name in ('independent_review', 'human_signoff'):
        record = (evidence or {}).get(name)
        lines.append(f'- {name.replace("_", " ").capitalize()}: ' +
                     (md(record['status']) + (' by ' + md(record['reviewer']) if record['reviewer'].strip() else '')
                      if record else 'pending (not supplied)'))
    lines += ['', '## Verification gates', '', '`agent-contrib verify` reported:', '']
    if task['schema_version'] == '0.2':
        for name in ('implementation_ready', 'technical_evidence_valid', 'draft_create_ready', 'completion_ready'):
            lines.append(_gate(name, verification.get(name)))
        lines.append('- `next_action`: ' + md(verification.get('next_action', 'unknown')))
        blockers = [(stage, error) for stage, errors in verification.get('stage_blockers', {}).items() for error in errors]
    else:
        for name in ('execution_ready', 'evidence_valid', 'upstream_submission_ready', 'fork_completion_ready'):
            lines.append(_gate(name, verification.get(name)))
        blockers = [('execution', error) for error in verification.get('errors', [])]
        blockers += [('evidence', error) for error in verification.get('evidence_errors', [])]
    lines += ['', 'Pending gates:' if blockers else 'No pending gates were reported.']
    lines += [f'- {md(stage)}: {md(error)}' for stage, error in blockers[:200]]
    lines += ['', '## Overlap scan', '']
    duplicates = verification.get('duplicates', [])
    lines.append(f'Live open-PR scan complete: {"yes" if verification.get("live_complete") is True else "no"}. '
                 f'Overlapping PRs: {len(duplicates)}.')
    lines += [f'- {md(item.get("url", ""))}: {md(item.get("reason", ""))}' for item in duplicates[:50]]
    lines += ['', '## AI assistance disclosure', '',
              f'Prepared with Agent Contrib CLI {__version__}. Contract SHA-256: '
              f'`{verification.get("contract_sha256") or core.canonical_hash(task)}`.']
    if assistant:
        lines.append('Host-reported assistant: ' + md(assistant, 200) + '.')
    lines += ['', '<!-- If the repository has a pull request template, merge these sections into it. '
              'Rendering is not publication authority. -->', '']
    return '\n'.join(lines)


def pr_body(task, evidence=None, repo_dir=None, client=None, **options):
    """Read-only: verify gates come from a fresh verify run, never from the caller."""
    verification = core.verify(task, evidence, repo_dir, client)
    if verification.get('schema_valid') is not True:
        raise core.ProtocolError('invalid_contract', 'Contract does not match its bundled schema')
    if evidence is not None and core.schema_errors(evidence, core.bundled_schema('evidence', task['schema_version'])):
        evidence = None  # Malformed evidence is reported by the gates, never quoted.
    return render(task, verification, evidence, **options), verification
