"""Read-only maintainer view of what an agent sees in a repository. Suggestions are non-binding."""
import re

from . import core
from .prbody import TEMPLATE

EXPECTED = {'contributing': ('CONTRIBUTING.md',), 'agent instructions': ('AGENTS.md', 'CLAUDE.md'),
            'pull request template': (),
            'architecture/spec index': ('docs/architecture.md', 'specs/readme.md', 'spec/readme.md',
                                        'docs/readme.md', 'docs/index.md')}
POLICY_TEMPLATE = {'schema_version': core.VERSION, 'agent_approved_labels': ['agent-approved'],
                   'label_authority': 'repository-label-permission'}


def _normal(label):
    return re.sub(r'[-_\s]+', '', label).casefold()


def _matches(paths, kind):
    """Bare names match any directory, as the snapshot reads them; paths match exactly."""
    if kind == 'pull request template':
        return any(TEMPLATE.fullmatch(path) for path in paths)
    lowered = {path.lower() for path in paths}
    basenames = {path.rsplit('/', 1)[-1] for path in lowered}
    return any(name.lower() in (lowered if '/' in name else basenames) for name in EXPECTED[kind])


def _coverage(kind, loaded, tree):
    if _matches(loaded, kind):
        return 'loaded'
    if tree is None:
        return 'unknown'
    return 'present_unread' if _matches(tree, kind) else 'missing'


def audit(repository, client=None, *, print_policy=False):
    client = client or core.GitHub()
    result, snapshot = core.discover_with_snapshot(repository, client)
    report = {key: result.get(key) for key in ('requested_repository', 'issue_source_repository',
                                               'proposed_target_repository', 'resolution_provenance')}
    report.update(complete=result.get('complete') is True, errors=result.get('errors', []),
                  warning='Read-only report. Suggestions are non-binding; nothing is written to the repository.')
    if snapshot is None:
        return report
    from . import policy as policy_inventory
    report['tipjar'] = snapshot['tipjar']
    report['repository_policy'] = policy_inventory.report(snapshot['repository'], snapshot['commit'],
        snapshot['instructions'], client, default_branch=snapshot['default_branch'], tipjar_report=snapshot['tipjar'])
    issues = result['issues']
    policy = {'state': snapshot['policy_state'], 'path': '.agent-contrib.json', 'commit': snapshot['commit']}
    labels = [label.get('name') for label in snapshot['labels']]
    malformed = sum(not isinstance(name, str) or not name.strip() for name in labels)
    labels = [name for name in labels if isinstance(name, str) and name.strip()]
    if malformed:
        # discover tolerates these; the audit consumes names, so it must not report them as complete.
        report['errors'] = report['errors'] + [f'{malformed} repository label(s) have a malformed name']
        report['complete'] = False
    if snapshot['policy_state'] == 'present':
        verdict = core.approval_for(snapshot, {'labels': []})
        policy['valid'] = verdict['status'] != 'unknown'
        policy['reason'] = verdict['reason']
        declared = snapshot['policy'].get('agent_approved_labels') if isinstance(snapshot['policy'], dict) else None
        if isinstance(declared, list) and not malformed:
            existing = set(labels)
            policy['approval_labels'] = [core.safe_text(l, 100) for l in declared if isinstance(l, str)]
            policy['missing_labels'] = [core.safe_text(l, 100) for l in declared if isinstance(l, str) and l not in existing]
            generic = {_normal(name) for name in core.GENERIC_LABELS}
            policy['generic_approval_labels'] = [core.safe_text(l, 100) for l in declared
                                                 if isinstance(l, str) and _normal(l) in generic]
    else:
        policy['valid'] = None
        policy['reason'] = ('No approval policy at the default branch snapshot' if snapshot['policy_state'] == 'missing'
                            else 'Policy read is incomplete; approval would be unknown')
    instruction_paths = [item['path'] for item in snapshot['instructions']]
    found = {kind: _coverage(kind, instruction_paths, snapshot['blob_paths']) for kind in EXPECTED}
    tree_complete = snapshot['blob_paths'] is not None
    ambiguity = {}
    for issue in issues:
        value = issue['ranking']['ambiguity']['value']
        ambiguity[value] = ambiguity.get(value, 0) + 1
    approvals = {}
    for issue in issues:
        approvals[issue['approval']['status']] = approvals.get(issue['approval']['status'], 0) + 1
    overlapping = sum(bool(issue['duplicates']) for issue in issues)
    report.update(
        repository=snapshot['repository'], commit=snapshot['commit'], policy=policy,
        instructions={'found': instruction_paths, 'expected': found,
                      'read_limit': 60, 'tree_complete': tree_complete},
        labels={'count': len(labels), 'malformed': malformed, 'scan': snapshot['labels_scan']},
        issues={'open': len(issues), 'ambiguity': ambiguity, 'approval': approvals,
                'excluded': sum(bool(issue['exclusions']) for issue in issues), 'overlapping': overlapping,
                'scan': result['issue_scan']},
        pull_requests={'open': len(snapshot['pulls']), 'scan': snapshot['pulls_scan'],
                       'overlap_density': round(overlapping / len(issues), 3) if issues else None},
        fork={'tracker': result['resolution_provenance']['reason'],
              'proposed_target_pulls': result['provenance']['proposed_target_pulls']})
    suggestions = []
    if not tree_complete:
        suggestions.append('Repository tree is truncated; agents cannot see every instruction file.')
    for kind, state in found.items():
        if state == 'missing':
            suggestions.append(f'Add a {kind} file so agents read your expectations.')
        elif state == 'present_unread':
            suggestions.append(f'A {kind} exists but is not among the instruction files agents load.')
    if snapshot['policy_state'] == 'missing':
        suggestions.append('No approval policy: every issue is only a candidate. Add .agent-contrib.json to delegate '
                           'approval to a dedicated label (see --print-policy).')
    elif policy.get('valid') is False:
        suggestions.append('Fix the approval policy; it currently makes every issue unknown: ' + policy['reason'])
    if policy.get('missing_labels'):
        suggestions.append('Create the approval labels the policy names: ' + ', '.join(policy['missing_labels']))
    if issues and ambiguity.get('high', 0) * 2 > len(issues):
        suggestions.append('Most issues read as ambiguous; add acceptance criteria, checklists or reproduction steps.')
    report['suggestions'] = suggestions
    if print_policy:
        report['policy_template'] = POLICY_TEMPLATE
    return report
