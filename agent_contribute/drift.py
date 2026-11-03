"""Read-only drift report for a prepared contract (#16). It never rewrites the contract."""
import hashlib

from . import core, policy as policy_report

# Current-report reasons that mean the inventory itself could not be read completely.
POLICY_READ_FAILURES = {'repository tree not read', 'read failed', 'content did not match the pinned tree entry'}


def _sha(text):
    return hashlib.sha256(text.encode('utf-8', errors='surrogateescape')).hexdigest()


def drift(task, client=None, policy_sha256=None):
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
    # A different tracker, issue URL or (0.2) numeric identity is a different source, even with equal content.
    report['source'] = {'stored_repository': source['repository'], 'current_repository': live['repository'],
                        'stored_issue_url': source['issue_url'], 'current_issue_url': live['issue_url']}
    report['source']['changed'] = source['repository'] != live['repository'] or source['issue_url'] != live['issue_url']
    if task['schema_version'] == '0.2':
        from .authorization import issue_identity, repository_identity
        report['source']['stored_identity'] = {key: source[key] for key in ('repository_id', 'owner_id', 'issue_id')}
        try:
            meta = repository_identity(live['repository'], client)
            identity = {'repository_id': meta['id'], 'owner_id': meta['owner']['id'],
                        'issue_id': issue_identity(live['repository'], source['issue'], client)['id']}
        except core.ProtocolError as exc:
            errors.append('Could not resolve current source identity: ' + str(exc))
            identity = None
        report['source']['current_identity'] = identity
        report['source']['changed'] |= identity is not None and identity != report['source']['stored_identity']
    report['default_branch'] = {'stored_branch': source['default_branch'], 'current_branch': live['default_branch'],
                                'stored_commit': source['commit'], 'current_commit': live['commit'],
                                'advanced': source['commit'] != live['commit'],
                                'note': 'Informational; an advanced branch alone is not drift'}
    current_files = {item['path']: item['sha256'] for item in current['instructions']}
    instructions = {'changed': live['instructions_sha256'] != source['instructions_sha256'],
                    'baseline_verified': False, 'added': [], 'removed': [], 'modified': []}
    baseline = None
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
    from . import tipjar
    before = baseline.get('tipjar') if baseline is not None else None
    after = current.get('tipjar')
    jar_changed = None if not before or not before['complete'] or not after or not after['complete'] else not tipjar.same_declaration(before, after)
    report['tipjar'] = {'baseline': before, 'current': after, 'changed': jar_changed}
    if jar_changed is None:
        errors.append('Tipjar declaration baseline/current read unresolved')
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
    policy_changed = False
    if policy_sha256 is not None:
        report['repository_policy_drift'] = _policy_drift(policy_sha256, current, baseline, source, client, errors)
        policy_changed = report['repository_policy_drift']['policy_drifted'] is True
    report['drifted'] = bool(jar_changed or report['source']['changed'] or report['issue']['changed'] or instructions['changed'] or policy['changed'] or
                             report['overlap']['added'] or report['default_branch']['stored_branch'] !=
                             report['default_branch']['current_branch'] or policy_changed)
    report['errors'] = errors
    report['complete'] = not errors
    return report


def _policy_drift(expected, current, baseline, source, client, errors):
    """Compare the reviewed policy inventory hash with the inventory at the current default-branch commit (N1).

    Per-source deltas need a baseline: the inventory rebuilt at the contract's pinned commit must reproduce the
    recorded hash. The owner .github repository is read at its current tip, so it may not; then only the hash
    comparison is reported, never invented deltas."""
    now = policy_report.for_inspected(current, client)
    incomplete = not now['tipjar']['complete'] or now['limits_hide_sources'] or any(item['reason'] in POLICY_READ_FAILURES for item in now['unassessed'])
    result = {'expected_sha256': expected, 'current_sha256': now['inventory_sha256'],
              'policy_drifted': None if incomplete else now['inventory_sha256'] != expected,
              'limits_hide_sources': now['limits_hide_sources'], 'baseline_verified': False,
              'current_inventory_format': now['inventory_format'],
              'recorded_inventory_format': now['inventory_format'] if now['inventory_sha256'] == expected else None,
              'added': None, 'removed': None, 'changed': None,
              'note': 'The hash covers policy source bytes, unassessed references and limits. Re-read every changed '
                      'source and repeat the policy review before any authorization or publication.'}
    if incomplete:
        errors.append('Policy inventory read is incomplete or limited; policy drift is unknown')
    if baseline is not None and not baseline['errors']:
        hashes = {}
        then = policy_report.report(source['repository'], source['commit'], baseline['instructions'], client,
                                    default_branch=source['default_branch'], hashes=hashes)
        # The same pinned snapshot hashed under another known format identifies the recorded hash's format.
        fmt = next((fmt for fmt, digest in sorted(hashes.items(), reverse=True) if digest == expected), None)
        result['baseline_verified'] = fmt is not None
        if fmt is not None:
            result['recorded_inventory_format'] = fmt
    current = result['current_inventory_format']
    if result['recorded_inventory_format'] not in (None, current):
        result['note'] += (f' The recorded hash is inventory format {result["recorded_inventory_format"]} of the same '
                           f'pinned snapshot; the current report is format {current}, so the hashes cannot match. '
                           'Re-review and record the new inventory_sha256.')
    if not result['baseline_verified']:
        result['note'] += (f' No per-source deltas: the baseline rebuilt at the pinned commit (inventory format '
                           f'{current}) does not reproduce the recorded hash. It may come from a different inventory '
                           'format (another agent-contrib version), the owner .github repository may have moved, or '
                           'the review used another snapshot.')
        return result
    old, new = _inventory_entries(then), _inventory_entries(now)
    result['added'] = [dict(new[i], identity_sha256=i) for i in sorted(set(new) - set(old))]
    result['removed'] = [dict(old[i], identity_sha256=i) for i in sorted(set(old) - set(new))]
    result['changed'] = [{'identity_sha256': i, 'what': new[i]['what'],
                          'stored': {k: old[i][k] for k in ('state', 'fingerprint')},
                          'current': {k: new[i][k] for k in ('state', 'fingerprint')}}
                         for i in sorted(set(old) & set(new))
                         if (old[i]['state'], old[i]['fingerprint']) != (new[i]['state'], new[i]['fingerprint'])]
    return result


def _inventory_entries(rep):
    """identity -> {what, state, fingerprint} for every inventoried candidate, read or unread (RP-28): scanned
    sources by content SHA-256, unread files and omissions by pinned Git blob id, references by identity alone."""
    entries = {}
    for s in rep['sources_scanned']:
        what = s['path'] if s['origin'] == 'repository' else f"{s['repository']}:{s['path']}"
        entries.setdefault(s['identity_sha256'], {'what': what, 'state': 'scanned', 'fingerprint': s['sha256']})
    for u in rep['unassessed']:
        entries.setdefault(u['identity_sha256'], {'what': u['what'], 'state': 'unassessed: ' + u['reason'],
                                                  'fingerprint': u['blob_sha']})
    for o in rep['omitted_sources']:
        owner = o['repository'].rsplit('/', 1)[-1] == '.github'  # owner .github entries display with their repository
        what = f"{o['repository']}:{o['path']}" if owner else o['path']
        entries.setdefault(o['identity_sha256'], {'what': what, 'state': 'omitted: ' + o['reason'],
                                                  'fingerprint': o['blob_sha']})
    return entries

