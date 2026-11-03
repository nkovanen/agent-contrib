"""Offline, proposed stopping budgets over an untrusted discovery snapshot."""
import hashlib

from . import core, outputs

MAX_INPUT_BYTES = 8 * 1024 * 1024
FOLLOW_UP = [
    'Read all repository policies, instructions and jar boundaries; stop on prohibitions or unresolved rules.',
    'Refresh inspect --ownership and review existing local work; unrequested checks remain unassessed. Stop on incomplete reads, claims, prior fixes or overlapping pull requests.',
    'Prepare and review a scoped task contract; review validation commands before any host execution.',
    'Stop for actual human/host implementation authorization; publication and completion require separate authority.',
]
NOTICE = ('Proposed shortlist only; actions are not authorized. Minutes are stopping caps, not completion estimates. '
          'The source is an untrusted historical snapshot; no network checks or execution occurred. '
          'Discovery without a jar observation is undeclared and requires manual jar review, never implied approval.')


def _invalid(message):
    raise core.ProtocolError('invalid_discovery', message)


def _display(report, count):
    display = report.get('display')
    if display is not None and (display['returned'] != count or
                               display['total_issues_considered'] != count + display['omitted'] or
                               display['truncated'] != (display['omitted'] > 0) or
                               count > display['requested_limit']):
        _invalid('Discovery display counts conflict with retained entries')


def _resolution(repository, requested, source):
    """Check identities against the same one-parent resolver that produced discovery."""
    target = core.parse_repository(repository.get('proposed_target_repository', requested))
    if target.casefold() != requested.casefold():
        _invalid('Proposed target conflicts with requested repository')
    provenance = repository.get('resolution_provenance')
    if provenance is None:  # A failed multi-repository entry has no resolved context.
        return
    if provenance['execution_authority'] != 'none':
        _invalid('Repository resolution cannot grant authority')
    if source is None:
        return  # Unresolved reports remain visible but cannot supply issues.
    reads = provenance['metadata_reads']
    if not reads or reads[0]['endpoint'].casefold() != ('repos/' + requested).casefold():
        _invalid('Missing or conflicting requested repository metadata')
    observed = reads[0]['observed']
    if core.parse_repository(observed['full_name']).casefold() != requested.casefold():
        _invalid('Requested repository conflicts with observed metadata')
    if observed['has_issues']:
        if len(reads) != 1 or source.casefold() != requested.casefold():
            _invalid('Issue source conflicts with requested tracker metadata')
    else:
        parent = observed.get('parent', {}).get('full_name')
        if not observed['fork'] or parent is None or len(reads) != 2:
            _invalid('Issue source requires an observed immediate fork parent')
        parent = core.parse_repository(parent)
        parent_read = reads[1]
        if (parent.casefold() == requested.casefold() or source.casefold() != parent.casefold() or
                parent_read['endpoint'].casefold() != ('repos/' + parent).casefold() or
                core.parse_repository(parent_read['observed']['full_name']).casefold() != parent.casefold() or
                parent_read['observed']['has_issues'] is not True):
            _invalid('Issue source conflicts with immediate parent metadata')


def _validate(report):
    if core.schema_errors(report, outputs.output_schema('discover')):
        _invalid('Discovery does not match the supported packaged output schema')
    repositories = report.get('repositories', [report])
    rows, by_requested, identities = {}, {}, set()
    for repository_index, repository in enumerate(repositories):
        requested = core.parse_repository(repository['requested_repository'])
        if requested.casefold() in by_requested:
            _invalid('Duplicate requested repository')
        by_requested[requested.casefold()] = repository
        source = repository.get('repository')
        if source is not None:
            core.parse_repository(source)
            if repository['issue_source_repository'] != source:
                _invalid('Conflicting issue source repository')
        _resolution(repository, requested, source)
        for issue_index, issue in enumerate(repository['issues']):
            reference = f'{requested}#{issue["number"]}'
            if source is None or issue['reference'] != reference or issue['issue_url'] != (
                    f'https://github.com/{source}/issues/{issue["number"]}'):
                _invalid('Conflicting issue identity or URL')
            core.parse_issue(reference)
            identity = f'{source}#{issue["number"]}'.casefold()
            if identity in identities:
                _invalid('Duplicate issue identity')
            identities.add(identity)
            rows[(requested.casefold(), reference)] = (repository_index, issue_index, repository, issue)
        _display(repository, len(repository['issues']))
    if 'repositories' not in report:
        return list(rows.values())
    included_rows = {key: row for key, row in rows.items()
                     if row[2].get('selection', {}).get('included', True)}
    ordered, seen = [], set()
    for candidate in report['candidates']:
        key = (candidate['repository'].casefold(), candidate['reference'])
        if key in seen or key not in included_rows:
            _invalid('Duplicate, excluded or missing merged candidate identity')
        seen.add(key)
        row = rows[key]
        repository, issue = row[2:]
        expected = {'number': issue['number'], 'excluded': bool(issue['exclusions']),
                    'overlapping': bool(issue['duplicates']),
                    'low_likelihood': issue['ranking']['success_likelihood']['value'] == 'low',
                    'score': issue.get('signals', {}).get('score'),
                    'complete': issue['complete'] and repository['complete']}
        if any(candidate[field] != value for field, value in expected.items()):
            _invalid('Merged candidate conflicts with its source issue')
        ordered.append(row)
    if seen != set(included_rows):
        _invalid('Merged candidate list omits retained included source issues')
    _display(report, len(ordered))
    if report['complete'] != all(r['complete'] for r in repositories):
        _invalid('Conflicting multi-repository completeness')
    # Keep excluded diagnostic rows visible after the merged candidate order.
    return ordered + [row for key, row in rows.items() if key not in included_rows]


def plan(path, *, max_tasks, minutes):
    """Read once, validate strictly, and allocate caps without executing or authorizing work."""
    if type(max_tasks) is not int or not 1 <= max_tasks <= 20 or type(minutes) is not int or not 1 <= minutes <= 1440:
        raise core.ProtocolError('usage', '--max-tasks must be 1–20 and --minutes must be 1–1440')
    try:
        data = core.read_regular(path, MAX_INPUT_BYTES)
        report = core.strict_json(data.decode('utf-8'))
    except (OSError, UnicodeError) as exc:
        raise core.ProtocolError('file_error', 'Cannot read discovery as an 8 MiB bounded UTF-8 regular file') from exc
    rows = _validate(report)
    candidates, tasks = [], []
    for repository_index, issue_index, repository, issue in rows:
        reasons = []
        jar = repository.get('tipjar')
        if jar is not None and (jar['state'] == 'unknown' or jar['complete'] is not True):
            reasons.append('source_jar_unknown')
        elif jar is not None and jar['state'] == 'closed':
            reasons.append('source_jar_closed')
        elif repository.get('selection', {}).get('included') is False:
            reasons.append('source_selection_excluded')
        if repository['complete'] is not True or repository['errors']:
            reasons.append('repository_incomplete')
        provenance = repository['provenance']
        scans = [repository['issue_scan'], provenance['pulls_scan'], provenance['labels_scan'],
                 provenance['proposed_target_pulls']]
        if any(scan is not None and (scan['complete'] is not True or scan['errors']) for scan in scans):
            reasons.append('repository_scans_incomplete')
        if provenance['policy_state'] == 'unknown':
            reasons.append('source_policy_unknown')
        if issue['complete'] is not True:
            reasons.append('issue_incomplete')
        if issue['approval']['status'] == 'unknown':
            reasons.append('source_approval_unknown')
        if issue['exclusions']:
            reasons.append('excluded')
        if issue['duplicates']:
            reasons.append('overlapping')
        local = repository.get('local_work')
        work_signal = issue.get('signals', {}).get('local_work', {})
        if local is not None and (local['complete'] is not True or local['errors']):
            reasons.append('local_work_incomplete')
        if work_signal.get('value') == 'unknown':
            reasons.append('local_work_unknown')
        if (work_signal.get('value') == 'referenced' or work_signal.get('commits') or
                local is not None and any(item['number'] == issue['number'] for item in local['issues'])):
            reasons.append('local_work_referenced')
        top_check = issue.get('top_check', {})
        if top_check.get('complete') is False or top_check.get('errors'):
            reasons.append('ownership_check_incomplete')
        if top_check.get('demotions'):
            reasons.append('ownership_existing_work')
        if issue.get('signals', {}).get('assignees'):
            reasons.append('current_assignee')
        if not reasons and len(tasks) >= min(max_tasks, minutes):
            reasons.append('session_capacity')
        entry = {'reference': issue['reference'], 'source_repository_index': repository_index,
                 'source_issue_index': issue_index, 'selected': not reasons, 'reasons': reasons}
        candidates.append(entry)
        if not reasons:
            tasks.append({'reference': issue['reference'], 'issue_url': issue['issue_url'],
                          'source_repository_index': repository_index, 'source_issue_index': issue_index,
                          'stop_after_minutes': 0, 'required_follow_up': list(FOLLOW_UP)})
    for index, task in enumerate(tasks):
        task['stop_after_minutes'] = minutes // len(tasks) + (index < minutes % len(tasks))
    return {'schema_version': '0.1', 'status': 'proposed', 'actions_authorized': False,
            'minutes': minutes, 'max_tasks': max_tasks, 'allocated_minutes': minutes if tasks else 0,
            'source_file_sha256': hashlib.sha256(data).hexdigest(), 'source_report': report,
            'source_complete': report['complete'], 'candidates': candidates, 'tasks': tasks, 'notice': NOTICE}
