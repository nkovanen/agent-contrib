"""Read-only drift report for a prepared contract (#16). It never rewrites the contract."""
import hashlib

from . import core


def _sha(text):
    return hashlib.sha256(text.encode('utf-8', errors='surrogateescape')).hexdigest()


def drift(task, client=None):
    if core.validate_contract(task):
        raise core.ProtocolError('invalid_contract', 'Contract does not match its bundled schema')
    client = client or core.GitHub()
    source = task['source']
    report = {'contract_sha256': core.canonical_hash(task), 'complete': False, 'drifted': None, 'errors': [],
              'notice': 'Report only. The contract is never rewritten; after drift, re-review and re-prepare it.'}
    current = core.inspect_issue(f'{source["repository"]}#{source["issue"]}', client)
    if 'source' not in current:
        report['errors'] = list(current.get('errors') or ['Current source could not be read'])
        return report
    errors = list(current['errors'])
    live = current['source']
    try:
        issue = core.issue_data(client.request(f'repos/{live["repository"]}/issues/{source["issue"]}'), source['issue'])
        if core.issue_hash(issue) != live['issue_sha256']:
            # Never mix two snapshots: components must describe the issue the hash comparison saw.
            raise core.ProtocolError('issue_moved', 'Issue changed between reads; rerun drift')
        components = {'title_sha256': _sha(issue['title']), 'body_sha256': _sha(issue['body']),
                      'state': core.safe_text(issue['state'], 40),
                      'labels': sorted(core.safe_text(label['name'], 100) for label in issue['labels']),
                      'assignees': sorted(core.safe_text(user['login'], 100) for user in issue.get('assignees', []))}
    except core.ProtocolError as exc:
        errors.append(str(exc) if exc.code == 'issue_moved' else 'Could not read current issue components: ' + str(exc))
        components = None
    report['issue'] = {'changed': live['issue_sha256'] != source['issue_sha256'],
                       'stored_sha256': source['issue_sha256'], 'current_sha256': live['issue_sha256'],
                       'stored_updated_at': source['issue_updated_at'], 'current_updated_at': live['issue_updated_at'],
                       'current_components': components,
                       'component_baseline': 'unavailable: the contract stores one combined issue hash; '
                                             'per-component baselines need a future task schema'}
    report['default_branch'] = {'stored_branch': source['default_branch'], 'current_branch': live['default_branch'],
                                'stored_commit': source['commit'], 'current_commit': live['commit'],
                                'advanced': source['commit'] != live['commit'],
                                'note': 'Informational; an advanced branch alone is not drift'}
    current_files = {item['path']: item['sha256'] for item in current['instructions']}
    instructions = {'changed': live['instructions_sha256'] != source['instructions_sha256'],
                    'baseline_verified': False, 'added': [], 'removed': [], 'modified': []}
    try:
        # The pinned commit is immutable: re-reading it reconstructs per-file baselines without a schema change.
        baseline = core.repository_snapshot(live['repository'], client, core.repository_metadata(live['repository'], client),
                                            commit=source['commit'])
        instructions['baseline_verified'] = (not baseline['errors'] and
                                             baseline['instructions_sha256'] == source['instructions_sha256'])
        if not instructions['baseline_verified']:
            errors.append('Pinned instruction baseline could not be reconstructed to the stored hash')
        else:
            stored = {item['path']: item['sha256'] for item in baseline['instructions']}
            instructions['added'] = sorted(set(current_files) - set(stored))
            instructions['removed'] = sorted(set(stored) - set(current_files))
            instructions['modified'] = [{'path': path, 'stored_sha256': stored[path], 'current_sha256': current_files[path]}
                                        for path in sorted(set(stored) & set(current_files)) if stored[path] != current_files[path]]
    except core.ProtocolError as exc:
        errors.append('Could not read pinned instruction baseline: ' + str(exc))
    report['instructions'] = instructions
    policy = {'stored_approval': task['approval']['status'], 'current_approval': current['approval']['status'],
              'current_policy_state': current['provenance']['policy_state']}
    policy['changed'] = policy['stored_approval'] != policy['current_approval']
    if task['schema_version'] == '0.2':
        from .authorization import policy_hash
        policy.update(stored_policy_sha256=source['policy_sha256'], current_policy_sha256=policy_hash(current['provenance']))
        policy['changed'] = policy['changed'] or policy['stored_policy_sha256'] != policy['current_policy_sha256']
    report['policy'] = policy
    stored_urls = {item.get('url') for item in task['discovery']['duplicate_prs']}
    live_urls = {item['url'] for item in current['duplicates']}
    report['overlap'] = {'added': sorted(live_urls - stored_urls), 'removed': sorted(u for u in stored_urls - live_urls if u),
                         'scope': 'open PRs in the source repository only'}
    report['drifted'] = bool(report['issue']['changed'] or instructions['changed'] or policy['changed'] or
                             report['overlap']['added'] or report['default_branch']['stored_branch'] !=
                             report['default_branch']['current_branch'])
    report['errors'] = errors
    report['complete'] = not errors
    return report
