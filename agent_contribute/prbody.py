"""Render a PR description from the contract, evidence and verify gates. No GitHub writes."""
import json
import re

from . import core, __version__

AUTHORITY_OMITTED = ('Schema 0.2 authority gates, `next_action`, final sign-off and authorization blockers are '
                     'not shown: `pr-body` takes no host context, so it cannot reproduce the host\'s '
                     '`verify --host-context-stdin` run. That run alone decides them.')
KEYWORD = re.compile(r'(?i)\b(clos|fix|resolv)(?=(?:e|es|ed|s)?\b)')


def md(value, limit=2000):
    """Quote untrusted text inert: no HTML, Markdown structure, mentions or closing keywords."""
    text = ' '.join(core.safe_text(str(value), limit).split())
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    text = re.sub(r'([\\`*_\[\]()!|~])', r'\\\1', text)
    # Zero-width space entities break mentions, references and closing keywords; the visible text is unchanged.
    text = re.sub(r'[@#]|(?<=:)//', lambda m: m.group() + '&#8203;' if m.group() != '//' else '&#8203;//', text)
    return KEYWORD.sub(lambda m: m.group(1)[0] + '&#8203;' + m.group(1)[1:], text)


def code(value):
    """Exact data as a JSON code span; the delimiter outgrows any backtick run inside."""
    text = json.dumps(value, ensure_ascii=True)
    fence = '`' * (max((len(run) for run in re.findall('`+', text)), default=0) + 1)
    return f'{fence} {text} {fence}'


def _gate(name, value):
    return f'- `{name}`: {"yes" if value is True else "no"}'


def _scan(label, scan):
    if not isinstance(scan, dict):
        return f'- {label}: not read'
    return (f'- {label}: complete {"yes" if scan.get("complete") is True else "no"}, '
            f'pages {md(scan.get("pages"))}, errors {len(scan.get("errors") or [])}')


def render(task, verification, evidence=None, *, closes=False, assistant=None, template=None):
    source = task['source']
    v2 = task['schema_version'] == '0.2'
    verified = verification.get('technical_evidence_valid' if v2 else 'evidence_valid') is True
    claim = '' if verified else 'unverified claim: '
    reference = f'{source["repository"]}#{source["issue"]}'
    lines = ['## Summary', '', ('Closes ' if closes else 'Refs ') + reference, '',
             '**Objective:** ' + md(task['objective']), '',
             '**Scope:** allowed ' + ', '.join(md(p) for p in task['scope']['allowed_paths']) +
             '; prohibited ' + ', '.join(md(p) for p in task['scope']['prohibited_paths']), '',
             '## Acceptance criteria', '']
    if evidence is not None and not verified:
        lines += ['Supplied evidence did not pass `verify`; its statuses below are unverified claims.', '']
    observed = {item['id']: item for item in (evidence or {}).get('criteria', [])}
    for item in task['behavior_criteria']:
        record = observed.get(item['id'])
        status = claim + md(record['status']) + ': ' + md(record['evidence']) if record else 'no evidence supplied'
        lines.append(f'- {md(item["id"])}: {md(item["description"])} ({status})')
    lines += ['', '## Validation', '']
    checks = {item['id']: item for item in (evidence or {}).get('validations', [])}
    for item in task['validation']:
        record = checks.get(item['id'])
        prefix = f'- {md(item["id"])} ({md(item["kind"])}): argv {code(item["argv"])}; '
        if record:
            lines.append(prefix + f'{claim}status {md(record["status"])}, exit {md(record["exit_code"])}, '
                         f'tests run {md(record["tests_run"])}, skipped {md(record["skipped"])}')
        else:
            lines.append(prefix + 'no result supplied')
    lines += ['', 'Evidence is self-attested by the contributor; the verifier does not prove that tests ran.', '',
              '## Review and sign-off', '']
    if v2:
        state = verification.get('independent_review') or {}
        lines += [f'- Independent review: {md(state.get("status", "pending"))} '
                  f'({"valid" if state.get("valid") is True else "not valid"} per verify)',
                  '- Final human sign-off: not shown (requires host context)']
    else:
        for name in ('independent_review', 'human_signoff'):
            record = (evidence or {}).get(name)
            lines.append(f'- {name.replace("_", " ").capitalize()}: ' +
                         (claim + md(record['status']) + (' by ' + md(record['reviewer']) if record['reviewer'].strip() else '')
                          if record else 'pending (not supplied)'))
    lines += ['', '## Verification gates', '']
    if v2:
        # Without host context every authority state reads as unauthorized; omit rather than misstate it.
        lines += ['`agent-contrib verify` reported (text neutralized):', '',
                  _gate('technical_evidence_valid', verification.get('technical_evidence_valid')), '', AUTHORITY_OMITTED]
        authority = verification.get('user_authorization') or {}
        omitted = (set(authority.get('errors', [])) | set(authority.get('current_errors', []))) - set(
            authority.get('source_errors', []))
        blockers = [('source', error) for error in verification.get('errors', []) if error not in omitted]
        blockers += [('evidence', error) for error in verification.get('evidence_errors', [])]
        blockers += [('review', error) for error in (verification.get('independent_review') or {}).get('errors', [])]
    else:
        lines += ['`agent-contrib verify` reported (text neutralized, none omitted):', '']
        for name in ('execution_ready', 'evidence_valid', 'upstream_submission_ready', 'fork_completion_ready'):
            lines.append(_gate(name, verification.get(name)))
        blockers = [('execution', error) for error in verification.get('errors', [])]
        blockers += [('evidence', error) for error in verification.get('evidence_errors', [])]
    lines += ['', f'Pending gates ({len(blockers)}):' if blockers else 'No pending gates were reported.']
    lines += [f'- {md(stage)}: {md(error, 100000)}' for stage, error in blockers]
    lines += ['', '## Overlap scan', '']
    provenance = verification.get('live_provenance') or {}
    duplicates = verification.get('duplicates', [])
    lines += [f'Live refresh complete: {"yes" if verification.get("live_complete") is True else "no"}. '
              f'Overlapping PRs: {len(duplicates)}.',
              _scan(f'Source open PRs ({md(source["repository"])})', provenance.get('pulls'))]
    if 'proposed_target_pulls' in provenance:
        target = provenance['proposed_target_pulls'] or {}
        lines.append(_scan(f'Target open PRs ({md(target.get("repository", ""))})', target))
    lines += [f'- {md(item.get("url", ""))}: {md(item.get("reason", ""))}' for item in duplicates]
    lines += ['', 'Only open PRs are scanned; PRs that are no longer open, timeline claims and file-level conflicts are not checked.',
              '', '## AI assistance disclosure', '',
              f'Prepared with Agent Contrib CLI {__version__}. Contract SHA-256: '
              f'`{verification.get("contract_sha256") or core.canonical_hash(task)}`.']
    if assistant:
        lines.append('Host-reported assistant: ' + md(assistant, 200) + '.')
    lines += ['', '## Pull request template', '']
    template = template or {'state': 'unknown', 'templates': []}
    if template['state'] == 'found':
        lines.append(f'Merge these sections into the repository template at the pinned commit `{source["commit"]}`:')
        lines += [f'- {code(item["path"])}' + (f' (blob `{item["sha"]}`)' if item.get('sha') else '')
                  for item in template['templates']]
    elif template['state'] == 'none':
        lines.append(f'No pull request template exists at the pinned commit `{source["commit"]}`.')
    else:
        lines.append('Pull request template presence is unknown (tree read failed or was incomplete).')
    lines += ['', '<!-- Rendering is not publication authority. -->', '']
    return '\n'.join(lines)


TEMPLATE = re.compile(r'(?i)(?:\.github/|docs/)?pull_request_template(?:\.md|/[^/]{1,200}\.md)')


def template_pointer(task, client):
    """One bounded tree read at the reviewed source commit; template contents are not read."""
    source = task['source']
    try:
        tree = core.require(client.request(f'repos/{source["repository"]}/git/trees/{source["commit"]}?recursive=1'),
                            dict, 'tree')
        entries = core.require(tree.get('tree'), list, 'tree entries')
        if tree.get('truncated') is not False:
            raise core.ProtocolError('partial_tree', 'Repository tree is truncated')
        found = []
        # A malformed entry or a repeated path makes presence unknown, never absent.
        for entry, (path, kind) in zip(entries, core.tree_entries(entries)):
            if kind == 'blob' and TEMPLATE.fullmatch(path):
                sha = entry.get('sha')
                found.append({'path': core.safe_text(path, 500),
                              'sha': sha if isinstance(sha, str) and core.SHA.fullmatch(sha) else None})
        return {'state': 'found' if found else 'none', 'templates': sorted(found, key=lambda t: t['path'])[:20]}
    except core.ProtocolError:
        return {'state': 'unknown', 'templates': []}


def pr_body(task, evidence=None, repo_dir=None, client=None, **options):
    """Read-only: verify gates come from a fresh verify run, never from the caller."""
    verification = core.verify(task, evidence, repo_dir, client)
    if verification.get('schema_valid') is not True:
        raise core.ProtocolError('invalid_contract', 'Contract does not match its bundled schema')
    if evidence is not None and core.schema_errors(evidence, core.bundled_schema('evidence', task['schema_version'])):
        evidence = None  # Malformed evidence is reported by the gates, never quoted.
    template = template_pointer(task, client or core.GitHub())
    return render(task, verification, evidence, template=template, **options), verification
