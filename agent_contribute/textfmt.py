"""Concise text summaries of command results. JSON stays canonical; remote prose is one sanitized line."""
from . import core, policy


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


def _dispositions(result):
    # A waiver can turn a gate green, so text never shows the gate without the exception behind it.
    report = result.get('overlap_dispositions')
    if not isinstance(report, dict):
        return []
    out = ['Overlap dispositions (host-asserted): ' + line(report.get('status', 'unknown'), 40)]
    waived = report.get('waived') or []
    if waived:
        numbers = ', '.join('#' + line(item.get('number'), 12) for item in waived)
        out.append(f'Overlaps waived by host disposition: {len(waived)} - PR {numbers}; see JSON overlap_dispositions')
    return out + _list('Disposition errors', report.get('errors', []))


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
        return out + _dispositions(result) + _list('Errors', result.get('errors', []))
    out = ['Gates:'] + [f'  {name}: {_flag(result.get(name))}' for name in
                        ('schema_valid', 'execution_ready', 'evidence_valid', 'upstream_submission_ready',
                         'fork_completion_ready')]
    return out + _list('Blockers', result.get('errors', [])) + _list('Evidence blockers', result.get('evidence_errors', []))


def _display(result):
    display = result.get('display')
    if display is None:
        return []
    return [f"Display: shown {display['returned']} of {display['total_issues_considered']} observed candidates; "
            f"omitted {display['omitted']} (--limit {display['requested_limit']}; global budget). "
            "Scan completeness is separate."]


def _discover(result):
    if 'repositories' in result:
        out = [f'Complete: {_flag(result.get("complete"))}',
               f'Repositories: {len(result["repositories"])}']
        out += _display(result)
        for repository in result['repositories']:
            out += _discover(repository)
        return out + _list('Errors', result.get('errors', []))
    out = [f'Repository: {line(result.get("requested_repository", result.get("repository", "")))}',
           f'Complete: {_flag(result.get("complete"))}', f'Issues: {len(result.get("issues", []))}'] + _policy(result)
    if result.get('tipjar'):
        out += _jar_summary(result)
    out += _display(result)
    if result.get('issue_source_repository'):
        out.append('Issue source: ' + line(result['issue_source_repository']))
    if result.get('proposed_target_repository'):
        out.append('Proposed target (not authority): ' + line(result['proposed_target_repository']))
    issues = result.get('issues', [])
    for issue in issues[:20]:
        notes = [line(item, 40) for item in issue.get('exclusions', [])]
        signals = issue.get('signals')
        local = signals.get('local_work') if isinstance(signals, dict) else None
        if isinstance(local, dict) and local.get('value') == 'referenced':
            notes.append(f'demoted: closed by {len(local.get("commits") or [])} local commit(s)')
        check = issue.get('top_check')
        notes += ['demoted: ' + line(reason, 120) for reason in (check.get('demotions') or [] if isinstance(check, dict) else [])]
        score = f', score {line(signals.get("score"), 10)}' if isinstance(signals, dict) and 'score' in signals else ''
        reference = issue.get('reference', f'#{issue["number"]}')
        out.append(f'  {line(reference, 200)} [{line(issue.get("approval", {}).get("status", "unknown"), 20)}] '
                   f'overlaps {len(issue.get("duplicates") or [])}, excluded {_flag(bool(issue.get("exclusions")))}'
                   f'{score}: {line(issue.get("untrusted_title", ""), 120)}' + (' -- ' + '; '.join(notes) if notes else ''))
    if len(issues) > 20:
        out.append(f'  ... {len(issues) - 20} more issues in JSON output')
    if issues or result.get('display', {}).get('total_issues_considered'):
        # Overlapping and excluded issues sort last, so the 20-line cap would otherwise hide them.
        counts = result.get('display', {})
        total = counts.get('total_issues_considered', len(issues))
        overlaps = counts.get('overlapping', sum(bool(issue.get('duplicates')) for issue in issues))
        excluded = counts.get('excluded', sum(bool(issue.get('exclusions')) for issue in issues))
        out.append(f'Overlapping issues: {overlaps} of {total}; '
                   f'excluded issues: {excluded} of {total} '
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
    report = (result.get('repository_signals') or {}).get('responsiveness')
    if isinstance(report, dict):
        out.append(f'Responsiveness: {line(report.get("value", "unknown"), 20)} (complete {_flag(report.get("complete"))}): '
                   f'{line(report.get("explanation", ""))}')
    local = result.get('local_work')
    if isinstance(local, dict):
        numbers = [item.get('number') for item in local.get('issues', []) if isinstance(item, dict)]
        out.append(f'Local work: {len(numbers)} issue(s) referenced by {line(local.get("commits_scanned"), 10)} scanned '
                   f'local commit(s) (complete {_flag(local.get("complete"))})' +
                   (': ' + line(', '.join(f'#{number}' for number in numbers[:50])) if numbers else ''))
        out += _list('Local work errors', local.get('errors', []))
    return out + _list('Errors', result.get('errors', []))


def _inspect(result):
    out = [f'Reference: {line(result.get("reference", ""))}', f'Complete: {_flag(result.get("complete"))}',
           'Approval: ' + line(result.get('approval', {}).get('status', 'unknown')),
           'Duplicate scan: ' + line(result.get('duplicate_scan', 'unknown'))] + _policy(result)
    out += _jar_summary(result)
    out += _list('Exclusions', result.get('exclusions', []))
    out += _list('Overlapping PRs', (f'{d.get("url", "")}: {d.get("reason", "")}' for d in result.get('duplicates', [])))
    out += _ownership(result.get('ownership_signals'))
    return out + _list('Warnings', result.get('warnings', [])) + _list('Errors', result.get('errors', []))


def _ownership(report):
    """External evaluation 3 G1: the opt-in ownership report's key signals, so text never implies no prior work."""
    if not isinstance(report, dict):
        return []
    resolution = report.get('resolution_signals') or {}
    urls = lambda items: [line(item.get('url', ''), 200) for item in items or [] if isinstance(item, dict)]
    open_prs = [line(pr.get('url', ''), 200) + (' (draft)' if pr.get('draft') is True else '')
                for pr in report.get('cross_referenced_prs') or [] if isinstance(pr, dict) and pr.get('state') == 'open']
    claims = [f'{line(claim.get("author", ""), 100)} ({line(claim.get("author_association", ""), 30)}, '
              + ('age unknown' if claim.get('age_days') is None else f'{line(claim.get("age_days"), 10)} days')
              + (', stale' if claim.get('stale') is True else '') + f'): {line(claim.get("pattern", ""), 40)}'
              for claim in report.get('claims') or [] if isinstance(claim, dict)]
    assignments = [f'{line(item.get("event", ""), 20)} {line(item.get("assignee", ""), 100)} by '
                   f'{line(item.get("actor", ""), 100)} at {line(item.get("created_at", ""), 40)}'
                   for item in report.get('assignment_history') or [] if isinstance(item, dict)]
    shown = {item.get('url') for key in ('possibly_already_fixed', 'downstream_references', 'rejected_approaches')
             for item in resolution.get(key) or [] if isinstance(item, dict)}
    other_prs = [line(pr.get('url', ''), 200) + f' ({line(pr.get("state", ""), 20)})'
                 for pr in report.get('cross_referenced_prs') or []
                 if isinstance(pr, dict) and pr.get('state') != 'open' and pr.get('url') not in shown]
    connections = [f'{line(item.get("event", ""), 20)} by {line(item.get("actor", ""), 100)} at '
                   f'{line(item.get("created_at", ""), 40)}' for item in report.get('connected_events') or []
                   if isinstance(item, dict)]
    commits = [line(item.get('commit_id', ''), 40) for item in report.get('referencing_commits') or []
               if isinstance(item, dict)]
    sections = (_list('Possibly already fixed by a merged same-repository PR', urls(resolution.get('possibly_already_fixed'))) +
                _list('Downstream references, merged elsewhere', urls(resolution.get('downstream_references'))) +
                _list('Rejected approaches, closed unmerged', urls(resolution.get('rejected_approaches'))) +
                _list('Open linked PRs', open_prs) + _list('Other linked PRs', other_prs) + _list('Claims', claims) +
                _list('Assignments', assignments) + _list('Connected or disconnected events', connections) +
                _list('Referencing commits', commits))
    out = [f'Ownership signals: complete {_flag(report.get("complete"))} '
           '(report only; incomplete reads are unknown, never "not fixed")']
    lists = [report.get(key) for key in ('cross_referenced_prs', 'claims', 'assignment_history', 'connected_events',
                                         'referencing_commits')] + [resolution.get(key) for key in
                                                                    ('possibly_already_fixed', 'downstream_references',
                                                                     'rejected_approaches')]
    if report.get('complete') is not True:
        out.append('Ownership report incomplete; absence unknown')
    elif not any(lists):  # absence only when every list in the report is empty (review TO-01)
        out.append('No linked PRs, prior fixes, claims or assignments found')
    return out + sections + _list('Ownership errors', report.get('errors', []))


def _ownership_command(result):
    return _scalars(result) + _ownership(result.get('ownership_signals')) + _list('Errors', result.get('errors', []))


def _scalars(result):
    return [f'{key}: {line(value)}' for key, value in result.items() if isinstance(value, (str, int, bool)) or value is None]


def _authorization_request(result):
    out = ['Ready for issuance: ' + _flag(result.get('ready_for_issuance')),
           'Issued: no (unsigned request; not a mandate; grants nothing)',
           'Contract SHA-256: ' + line(result.get('contract_sha256', ''), 64)]
    out.append('Requested actions (the host chooses the mandate actions): ' +
               (', '.join(line(action, 50) for action in result.get('requested_actions', [])) or 'none'))
    # Derived fields only fresh reads resolve; the human-only fields always await the host, even when ready.
    return (out + _list('Preflight errors', result.get('preflight_errors', [])) +
            _list('Unresolved derived fields', result.get('unresolved_fields', [])) +
            _list('Human-only fields, filled only by the host', result.get('human_only_fields', [])))


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
    policy_drift = result.get('repository_policy_drift') or {}
    if policy_drift.get('policy_drifted') is True:
        named = [item.get('what', '') for kind in ('changed', 'added', 'removed') for item in policy_drift.get(kind) or []]
        recorded, current = policy_drift.get('recorded_inventory_format'), policy_drift.get('current_inventory_format')
        if recorded is not None and recorded != current:
            reasons.append(f'Policy inventory changed: recorded inventory_sha256 is inventory format {line(recorded, 10)}, '
                           f'current format is {line(current, 10)}; re-review and record the new hash' +
                           (' (' + ', '.join(line(path, 200) for path in named[:10]) + ')' if named else ''))
        else:
            reasons.append('Policy inventory changed: ' + (', '.join(line(path, 200) for path in named[:10]) if named else
                                                            'recorded inventory_sha256 differs (no per-source baseline)'))
    elif policy_drift and policy_drift.get('policy_drifted') is None:
        info.append('Policy inventory could not be compared: the current read is incomplete or limited')
    if branch.get('advanced'):
        info.append('Default branch advanced since preparation')
    info += ['Overlapping PR no longer open: ' + line(url, 200) for url in overlap.get('removed', [])]
    return (_scalars(result) + _list('Drift reasons', reasons) + _list('Informational', info) +
            _list('Errors', result.get('errors', [])))


def _policy(result):
    report = result.get('repository_policy')
    if not isinstance(report, dict):
        return []
    return [f'Policy: {len(report.get("sources_scanned", []))} sources scanned, {len(report.get("unassessed", []))} '
            f'unassessed, {len(report.get("hints", []))} hints, {len(report.get("limits_reached", []))} limits reached '
            '(repository_policy; not a verdict)',
            "  Read every source, hinted line and unassessed reference before choosing work; unresolved policy blocks "
            "upstream work. This is a host obligation even when every count is zero. 'Complete' above concerns "
            "GitHub reads, not policy."] + (
        [f'  Limits hide policy sources ({len(report.get("omitted_sources", []))} omitted candidates listed): repository '
         'policy is unresolved until each is read manually or shown inapplicable.'] if report.get('limits_hide_sources') else []
    ) + _policy_hints(report) + _policy_unassessed(report)


POLICY_HINT_LINES = 5
POLICY_EXCERPT_CHARS = 200


def _uncomment(text):
    """Drop HTML comment markers from a text-view excerpt (cosmetic; JSON keeps the excerpt unchanged)."""
    return str(text).replace('<!--', ' ').replace('-->', ' ')


def _policy_hints(report):
    """The restriction sentences that may justify a stop, in the report's attention order (N-01)."""
    sources = report.get('sources_scanned', [])
    lines = report.get('hinted_lines')
    if lines is None:  # a report without grouping: one entry per hint
        lines = [dict(hint, kinds=[hint.get('kind')]) for hint in report.get('hints', [])]
    stop = [entry for entry in lines if set(entry.get('kinds', [])) & set(policy.STOP_HINTS)]
    dropped = sum(item.get('not_reported', 0) for item in report.get('limits_reached', [])
                  if item.get('limit') in ('restriction hints', 'report size: restriction hints'))
    lost = [f'  ({dropped} restriction hints not retained because of limits; see limits_reached)'] if dropped else []
    if not stop:
        if dropped or report.get('limits_hide_sources'):
            return ['  No restriction hints retained: limits hid sources or hints (see limits_reached and '
                    'omitted_sources); this is not permission.'] + lost + _vocabulary(report)
        return ['  No restriction hints; this is not permission.'] + _vocabulary(report)
    out = []
    for hint in stop[:POLICY_HINT_LINES]:
        source = sources[hint['source']] if isinstance(hint.get('source'), int) and hint['source'] < len(sources) else {}
        path = line(source.get('path', '?'), 500)
        path = path if len(path) <= 100 else '...' + path[-97:]
        text = ' '.join(line(_uncomment(hint.get('untrusted_excerpt', '')), 1000).split())
        cut = len(text) > POLICY_EXCERPT_CHARS or hint.get('excerpt_truncated') is True
        kinds = ', '.join(line(kind, 40) for kind in hint['kinds'] if kind in policy.STOP_HINTS)
        out.append(f'  ! {kinds} {line(source.get("repository", "?"), 100)}:{path}:'
                   f'{line(hint.get("line", "?"), 10)} -- {text[:POLICY_EXCERPT_CHARS]}' + ('...' if cut else ''))
    if len(stop) > POLICY_HINT_LINES:
        out.append(f'  (+{len(stop) - POLICY_HINT_LINES} more hinted lines with restrictions in JSON '
                   'repository_policy.hinted_lines)')
    return out + lost + _vocabulary(report)


POLICY_UNASSESSED_LINES = 5
POLICY_UNASSESSED_CHARS = 150


def _policy_unassessed(report):
    """The references and files the tool did not assess, which the host must read itself (G3)."""
    entries = report.get('unassessed') or []
    out = []
    for entry in entries[:POLICY_UNASSESSED_LINES]:
        what = line(entry.get('what', '?'), 1000)
        cut = len(what) > POLICY_UNASSESSED_CHARS or entry.get('what_truncated') is True
        origin = f' from {line(entry["from"], 100)}' if entry.get('from') else ''
        at = f':{line(entry["line"], 10)}' if origin and entry.get('line') is not None else ''
        out.append(f'  ? {what[:POLICY_UNASSESSED_CHARS]}{"..." if cut else ""} ({line(entry.get("reason", "?"), 60)})'
                   f'{origin}{at}')
    if len(entries) > POLICY_UNASSESSED_LINES:
        out.append(f'  (+{len(entries) - POLICY_UNASSESSED_LINES} more unassessed references in JSON '
                   'repository_policy.unassessed)')
    return out


def _vocabulary(report):
    vocabulary = report.get('project_vocabulary') or {}
    count = vocabulary.get('mentions_collapsed') or 0
    if not count:
        return []
    terms = ', '.join(repr(line(term, 40)) for term in vocabulary.get('terms', []))
    return [f'  {count} mention{"s" if count != 1 else ""} of project-name vocabulary ({terms}) summarized in JSON '
            'project_vocabulary']


def _receipt(result):
    receipt = result['receipt']
    pr = receipt['pull_request']
    return [f"Receipt saved: {line(result['output'])}",
            f"PR: {line(pr['url'])} ({line(pr['state'])})",
            f"Observed: {line(receipt['observed_at'])}", line(result['warning'], 1000),
            line(receipt['refresh'])]


def _impact(result):
    counts = result['counts']
    return [f"Impact: {result['trust']}",
            f"Unique PRs: {result['unique_prs']}; repositories represented: {result['repositories_represented']}",
            f"Open: {counts['open']} (includes drafts); closed: {counts['closed']}; merged: {counts['merged']}",
            line(result['warning'], 1000)]


def _jar_summary(result):
    jar = result.get('tipjar') or {}
    if not jar:
        return []
    out = ['Jar: ' + line(jar.get('state', 'unknown'), 30)]
    selection = result.get('selection')
    if selection:
        out.append('Selection (' + line(selection['mode']) + '): ' + line(selection['reason']))
    for key in ('wanted', 'boundaries'):
        out += _list(key.capitalize() + ' (untrusted)', (jar.get('manifest') or {}).get(key, []))
    return out


def _jar(result):
    out = [f'Repository: {line(result["repository"])}',
           f'Jar: {line(result["state"], 30)} (complete: {_flag(result["complete"])})',
           f'Pinned commit: {line(result.get("commit") or "unavailable", 40)}',
           'Source declaration only; other policy and authorization gates remain.',
           line(result['notice'])]
    manifest = result.get('manifest') or {}
    for key in ('wanted', 'boundaries'):
        out += _list(key.capitalize() + ' (untrusted)', manifest.get(key, []))
    return out + _list('Errors', result.get('errors', []))


def _onboarding(result):
    out = [f'File: {line(result.get("output", result.get("path")))}',
           f'Jar: {line(result["state"])}', f'SHA-256: {line(result["sha256"], 64)}',
           line(result['notice'])]
    return out + _list('Next steps', result.get('next_steps', []))


def _find(result):
    out = [f'Bounded batch complete: {_flag(result["complete"])}',
           'Coverage: not exhaustive; one page of at most ten indexed hits. Indexing may lag.',
           'Find reads are uncached; core budget does not measure the separate search quota.']
    welcomed = [o for o in result['observations'] if o['disposition'] == 'welcome']
    if not welcomed:
        out.append('No verified welcoming repositories in this batch')
    for obs in result['observations']:
        out.append(f'{line(obs["repository"] or "[identity withheld]")}: '
                   f'{line(obs["disposition"])} ({line(obs["reason"])})')
        if obs['disposition'] == 'welcome':
            out += ['  https://github.com/' + line(obs['repository']),
                    '  Pinned commit: ' + line(obs['jar']['commit']),
                    '  Verified at: ' + line(obs['verified_at'])]
            for key in ('wanted', 'boundaries'):
                out += _list(key.capitalize() + ' (untrusted)', obs['jar']['manifest'].get(key, []))
    if result['search']['truncated']:
        out.append('Search truncated: only this first batch was observed; no backfill or rotation.')
    if not result['complete']:
        out.append('Incomplete batch: unknown observations or search incompleteness; verified findings retained.')
    return out + _list('Errors', result['errors']) + [line(result['notice'])]


def render(command, result, stage=None):
    """stage is (name, exit_gate_passed) for an explicit verify --stage; it changes presentation only."""
    if 'error' in result:
        return f'error [{line(result["error"].get("code", ""), 60)}]: {line(result["error"].get("message", ""))}\n'
    if command == 'dependencies':
        out = ['Offline dependency candidates',
               'Supported file coverage complete: ' + _flag(result['complete']),
               'All declarations resolved: ' + _flag(result['resolution_complete'])]
        if 'installed' in result:
            installed = result['installed']
            out.append(f"Installed metadata: {installed['examined']}/{installed['max_packages']} packages; "
                       'complete: ' + _flag(installed['complete']))
            out += _list('Installed package provenance',
                         (d['package'] + '@' + d['installed']['version'] + ' -> ' + d['repository'] +
                          ' [' + d['installed']['source_file'] + ']'
                          for d in result['dependencies'] if d.get('installed', {}).get('status') == 'github'))
        out += _list('Repositories', result['repositories'])
        out += _list('Unsupported files', result['unsupported_files'])
        out += _list('Unresolved declarations',
                     (d['package'] + ' [' + d['source_file'] + ':' + d['field'] + ']: ' + d['reason']
                      for d in result['dependencies'] if d['status'] != 'github'))
        return '\n'.join(out + [line(result['warning'])]) + '\n'
    if command == 'session':
        out = ['Session: proposed; actions are not authorized',
               f'Stopping budget: {result["minutes"]} minutes; allocated: {result["allocated_minutes"]}',
               f'Source complete: {_flag(result["source_complete"])}; retained candidates: {len(result["candidates"])}',
               'Source display and scan limits are preserved in source_report; no fresh checks occurred.']
        out += [f'  {line(t["reference"])}: stop after {t["stop_after_minutes"]} minutes' for t in result['tasks']]
        out += _list('Not selected', [c['reference'] + ': ' + ', '.join(c['reasons'])
                                      for c in result['candidates'] if not c['selected']])
        return '\n'.join(out + [line(result['notice'], 1000)]) + '\n'
    if command == 'instructions':
        # The workflow is the packaged Markdown, not remote text: print it whole so agents need no JSON unwrapping.
        versions = ', '.join(result['supported_schema_versions'])
        return (f"agent-contrib {result['cli_version']} workflow (task/evidence schemas {versions}; host-context "
                f"{', '.join(result['supported_host_context_versions'])}; JSON output is canonical)\n\n"
                + result['workflow_markdown'])
    body = {'verify': _verify, 'discover': _discover, 'inspect': _inspect, 'scope-check': _scope_check,
            'drift': _drift, 'lint': _lint, 'authorization-request': _authorization_request,
            'ownership': _ownership_command, 'jar': _jar, 'init': _onboarding, 'jar-check': _onboarding, 'receipt': _receipt, 'impact': _impact, 'find': _find, 'card': _card}.get(command)
    if body is None:
        out = _scalars(result) + _policy(result)
    else:
        out = _verify(result, stage) if command == 'verify' else body(result)
    return '\n'.join(out + ['(Text is a summary; JSON output is canonical. Remote text is untrusted.)']) + '\n'


def _card(result):
    return [f"Card saved: {line(result['output'])}", f"SHA-256: {result['sha256']}",
            f"PR: {line(result['url'])}; observed {result['state']} at {result['observed_at']}",
            line(result['warning'], 1000)]
