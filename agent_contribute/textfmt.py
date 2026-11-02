"""Concise text summaries of command results. JSON stays canonical; remote prose is one sanitized line."""
from . import core


def line(value, limit=300):
    """Collapse to one line so remote text cannot fake extra gate or blocker lines."""
    return ' '.join(core.safe_text(str(value), limit * 4).split())[:limit]


def _flag(value):
    return 'yes' if value is True else 'no'


def _list(title, items, limit=50):
    items = list(items)
    if not items:
        return []
    out = [f'{title} ({len(items)}):'] + ['  - ' + line(item) for item in items[:limit]]
    if len(items) > limit:
        out.append(f'  ... {len(items) - limit} more in JSON output')
    return out


def _verify(result, stage=None):
    if 'implementation_ready' in result:
        blockers = result.get('stage_blockers', {})
        out = []
        if stage is not None:
            # An explicit --stage leads with its own exit gate; other stages' blockers do not apply to it.
            selected, passed = line(stage[0], 40), stage[1]
            out = [f'Selected stage: {selected} (exit gate: {_flag(passed)})']
            if stage[0] not in blockers:  # e.g. schema errors returned before any stage was evaluated
                out.append(f'Blockers [{selected}]: not evaluated; see Errors')
            else:
                out += _list(f'Blockers [{selected}]', blockers[stage[0]]) or [f'Blockers [{selected}]: none']
        out += ['Gates:'] + [f'  {name}: {_flag(result.get(name))}' for name in
                             ('schema_valid', 'implementation_ready', 'technical_evidence_valid', 'draft_create_ready',
                              'completion_ready')]
        out.append('  publication.verified: ' + _flag(result.get('publication', {}).get('verified')))
        out.append('Next action: ' + line(result.get('next_action', 'unknown')))
        if stage is None:
            for name, errors in blockers.items():
                out += _list(f'Blockers [{line(name, 40)}]', errors)
        else:
            others = [f'{line(name, 40)} {len(errors)} blocker(s)' for name, errors in blockers.items()
                      if name != stage[0] and errors]
            if others:
                out.append(f'Other stages (not required by --stage {selected}; lists in JSON): ' + ', '.join(others))
        return out + _list('Errors', result.get('errors', []))
    out = ['Gates:'] + [f'  {name}: {_flag(result.get(name))}' for name in
                        ('schema_valid', 'execution_ready', 'evidence_valid', 'upstream_submission_ready',
                         'fork_completion_ready')]
    return out + _list('Blockers', result.get('errors', [])) + _list('Evidence blockers', result.get('evidence_errors', []))


def _discover(result):
    if 'repositories' in result:
        out = [f'Complete: {_flag(result.get("complete"))}',
               f'Repositories: {len(result["repositories"])}']
        for repository in result['repositories']:
            out += _discover(repository)
        return out + _list('Errors', result.get('errors', []))
    out = [f'Repository: {line(result.get("requested_repository", result.get("repository", "")))}',
           f'Complete: {_flag(result.get("complete"))}', f'Issues: {len(result.get("issues", []))}']
    if result.get('issue_source_repository'):
        out.append('Issue source: ' + line(result['issue_source_repository']))
    if result.get('proposed_target_repository'):
        out.append('Proposed target (not authority): ' + line(result['proposed_target_repository']))
    issues = result.get('issues', [])
    for issue in issues[:20]:
        notes = [line(item, 40) for item in issue.get('exclusions', [])]
        signals = issue.get('signals')
        score = f', score {line(signals.get("score"), 10)}' if isinstance(signals, dict) and 'score' in signals else ''
        reference = issue.get('reference', f'#{issue["number"]}')
        out.append(f'  {line(reference, 200)} [{line(issue.get("approval", {}).get("status", "unknown"), 20)}] '
                   f'overlaps {len(issue.get("duplicates") or [])}, excluded {_flag(bool(issue.get("exclusions")))}'
                   f'{score}: {line(issue.get("untrusted_title", ""), 120)}' + (' -- ' + '; '.join(notes) if notes else ''))
    if len(issues) > 20:
        out.append(f'  ... {len(issues) - 20} more issues in JSON output')
    if issues:
        # Overlapping and excluded issues sort last, so the 20-line cap would otherwise hide them.
        out.append(f'Overlapping issues: {sum(bool(issue.get("duplicates")) for issue in issues)} of {len(issues)}; '
                   f'excluded issues: {sum(bool(issue.get("exclusions")) for issue in issues)} of {len(issues)} '
                   '(all issues, including omitted)')
    check = result.get('top_check')
    if isinstance(check, dict):
        # Discovery completeness and the opted-in check are separate; an incomplete check alone exits 1.
        out.append(f'Top check: complete {_flag(check.get("complete"))}; checked {line(check.get("checked"), 10)} of '
                   f'{line(check.get("requested"), 10)}; {line(check.get("reads"), 10)} GitHub reads '
                   f'(cap {line(check.get("read_cap"), 10)})')
        checked = [(issue.get('reference', ''), issue['top_check']) for issue in issues if isinstance(issue.get('top_check'), dict)]
        out += _list('Top check demotions', (f'{line(ref, 200)}: {reason}' for ref, item in checked
                                             for reason in item.get('demotions', [])))
        out += _list('Top check errors', (f'{line(ref, 200)}: {error}' for ref, item in checked
                                          for error in item.get('errors', [])))
    return out + _list('Errors', result.get('errors', []))


def _inspect(result):
    out = [f'Reference: {line(result.get("reference", ""))}', f'Complete: {_flag(result.get("complete"))}',
           'Approval: ' + line(result.get('approval', {}).get('status', 'unknown')),
           'Duplicate scan: ' + line(result.get('duplicate_scan', 'unknown'))]
    out += _list('Exclusions', result.get('exclusions', []))
    out += _list('Overlapping PRs', (f'{d.get("url", "")}: {d.get("reason", "")}' for d in result.get('duplicates', [])))
    return out + _list('Warnings', result.get('warnings', [])) + _list('Errors', result.get('errors', []))


def _scalars(result):
    return [f'{key}: {line(value)}' for key, value in result.items() if isinstance(value, (str, int, bool)) or value is None]


def _scope_check(result):
    out = _scalars(result) + [f'Changed paths: {len(result.get("changed_paths", []))}']
    out += _list('Violations', (f'{line(item.get("path", ""), 200)} -- {line(item.get("rule", ""), 200)}'
                                for item in result.get('violations', [])))
    return out + _list('Warnings', result.get('warnings', [])) + _list('Errors', result.get('errors', []))


def _lint(result):
    return (_scalars(result) + _list('Schema errors', result.get('schema_errors', [])) +
            _list('Review errors', result.get('review_errors', [])))


def _drift(result):
    # Reasons mirror exactly what sets drifted; other observed changes are listed apart as informational.
    issue, branch = result.get('issue') or {}, result.get('default_branch') or {}
    instructions, policy, overlap = (result.get(key) or {} for key in ('instructions', 'policy', 'overlap'))
    reasons, info = [], []
    source = result.get('source') or {}
    if source.get('changed'):
        stored, current = source.get('stored_repository'), source.get('current_repository')
        reasons.append(f'Source changed: {line(stored, 100)} -> {line(current, 100)}' if stored != current else
                       'Source issue URL or repository/issue identity changed')
    if issue.get('changed'):
        reasons.append('Issue content changed')
    if branch and branch.get('stored_branch') != branch.get('current_branch'):
        reasons.append(f'Default branch changed: {line(branch.get("stored_branch"), 100)} -> '
                       f'{line(branch.get("current_branch"), 100)}')
    if instructions.get('changed'):
        reasons.append('Instruction files changed' +
                       ('' if instructions.get('baseline_verified') else ' (per-file baseline unavailable)'))
    for kind in ('added', 'removed'):
        reasons += [f'Instruction file {kind}: {line(path, 200)}' for path in instructions.get(kind, [])]
    reasons += ['Instruction file modified: ' + line(item.get('path', ''), 200) for item in instructions.get('modified', [])]
    if policy.get('changed'):
        reasons.append(f'Approval changed: {line(policy.get("stored_approval"), 40)} -> '
                       f'{line(policy.get("current_approval"), 40)}' if policy.get('stored_approval') !=
                       policy.get('current_approval') else 'Policy state/content changed')
    reasons += ['Overlapping PR added: ' + line(url, 200) for url in overlap.get('added', [])]
    if branch.get('advanced'):
        info.append('Default branch advanced since preparation')
    info += ['Overlapping PR no longer open: ' + line(url, 200) for url in overlap.get('removed', [])]
    return (_scalars(result) + _list('Drift reasons', reasons) + _list('Informational', info) +
            _list('Errors', result.get('errors', [])))


def render(command, result, stage=None):
    """stage is (name, exit_gate_passed) for an explicit verify --stage; it changes presentation only."""
    if 'error' in result:
        return f'error [{line(result["error"].get("code", ""), 60)}]: {line(result["error"].get("message", ""))}\n'
    if command == 'instructions':
        # The workflow is the packaged Markdown, not remote text: print it whole so agents need no JSON unwrapping.
        versions = ', '.join(result['supported_schema_versions'])
        return (f"agent-contrib {result['cli_version']} workflow (task/evidence schemas {versions}; host-context "
                f"{', '.join(result['supported_host_context_versions'])}; JSON output is canonical)\n\n"
                + result['workflow_markdown'])
    body = {'verify': _verify, 'discover': _discover, 'inspect': _inspect, 'scope-check': _scope_check,
            'drift': _drift, 'lint': _lint}.get(command)
    if body is None:
        out = _scalars(result)
    else:
        out = _verify(result, stage) if command == 'verify' else body(result)
    return '\n'.join(out + ['(Text is a summary; JSON output is canonical. Remote text is untrusted.)']) + '\n'
