"""Schema 0.2 same-repository candidate lifecycle; all GitHub operations are reads."""
from __future__ import annotations

import copy
import datetime as dt

from . import authorization, cigate, core, dispositions, draft_updates


def prepare_v2(inspected, client):
    from .tipjar import preparation_errors
    jar_errors = preparation_errors(inspected.get('tipjar'))
    if jar_errors:
        raise core.ProtocolError('tipjar_blocked', '; '.join(jar_errors))
    source = inspected['source']
    proposed = inspected.get('proposed_target_repository', source['repository'])
    if proposed != source['repository']:
        if isinstance(proposed, str) and proposed.casefold() == source['repository'].casefold():
            # Refuse rather than rebind: a 0.2 task names exactly the spelling that was requested and reviewed.
            raise core.ProtocolError('case_mismatch', 'Schema 0.2 requires the canonical repository spelling '
                                     + source['repository'] + '; inspect that reference again')
        raise core.ProtocolError('unsupported_route', 'Schema 0.2 supports only a same-repository candidate; use 0.1 for forks')
    if not inspected['complete']:
        raise core.ProtocolError('refresh_incomplete', 'Cannot bind a new task to incomplete source reads')
    meta = authorization.repository_identity(source['repository'], client)
    issue = authorization.issue_identity(source['repository'], source['issue'], client)
    if core.issue_hash(issue) != source['issue_sha256'] or issue['html_url'] != source['issue_url']:
        raise core.ProtocolError('source_changed', 'Issue changed while preparing task; inspect again')
    task = copy.deepcopy(core.prepare(inspected))
    task['schema_version'] = '0.2'
    task['source'].update(repository_id=meta['id'], owner_id=meta['owner']['id'], issue_id=issue['id'],
                          policy_sha256=authorization.policy_hash(inspected['provenance']))
    task['execution'] = {'mode': 'pending', 'target_repository': source['repository'], 'target_repository_id': meta['id'],
                         'head_repository': source['repository'], 'head_repository_id': meta['id'],
                         'head_ref': '', 'base_ref': source['default_branch'], 'requested_actions': []}
    for duplicate in task['discovery']['duplicate_prs']:
        duplicate['repository'] = source['repository']
    task['questions'][-1] = 'Review exact refs/actions, then obtain a separate human/host mandate bound to this contract hash.'
    return task


# Exact-head history is read only under a valid mandate; say so rather than implying it was read.
HISTORY_UNCHECKED = 'Exact-head PR history not checked: requires a valid mandate'


def check_publication(binding, publication_claim, expected_head, client):
    # Lazy import keeps legacy users independent of the new publication boundary.
    from .pr_identity import check_publication as check
    return check(binding, publication_claim, expected_head, client)


def check_updated_publication(binding, publication_claim, from_head, expected_head, client):
    from .pr_identity import check_updated_publication as check
    return check(binding, publication_claim, from_head, expected_head, client)


def independent_review(task, evidence, now):
    result = {'valid': False, 'status': 'pending', 'errors': [], 'trust': 'self-attested'}
    if evidence is None:
        return result
    if core.schema_errors(evidence, core.bundled_schema('evidence', '0.2')):
        return dict(result, status='invalid', errors=['Evidence schema is invalid'])
    review = evidence['independent_review']
    errors = result['errors']
    if (review['status'] != 'passed' or not review['reviewer'].strip() or not review['notes'].strip() or
            review['reviewer'].strip().casefold() == evidence['implementer'].strip().casefold() or
            review['git_head'] != evidence['git_head'] or review['contract_sha256'] != core.canonical_hash(task)):
        errors.append('Independent review is pending, failed, same implementer or stale')
    try:
        reviewed_at = authorization.timestamp(review['reviewed_at'])
        if reviewed_at > now or any(reviewed_at < authorization.timestamp(v['finished_at']) for v in evidence['validations']):
            raise ValueError('Review must follow final validations and not be in the future')
    except (ValueError, OverflowError) as exc:
        errors.append(str(exc))
    result.update(valid=not errors, status='passed' if not errors else 'invalid')
    return result


def human_signoff(task, context, evidence, authority, publication, review, now):
    result = {'valid': False, 'status': 'pending', 'trust': 'host-asserted', 'errors': [], 'sha256': None}
    if not isinstance(context, dict) or 'final_signoff' not in context:
        return result
    schema = core.host_context_schema(context)
    if core.schema_errors(context, schema):
        return dict(result, status='invalid', errors=['Host context schema is invalid'])
    record = context['final_signoff']
    errors = core.schema_errors(record, schema['properties']['final_signoff'])
    result.update(status='invalid', errors=errors)
    if errors:
        return result
    result['sha256'] = core.canonical_hash(record)
    if evidence is None or core.schema_errors(evidence, core.bundled_schema('evidence', '0.2')):
        errors.append('Final signoff requires valid final evidence')
        return result
    expected = {'contract_sha256': core.canonical_hash(task), 'mandate_sha256': authority['mandate_sha256'],
                'git_head': evidence['git_head'], 'review_sha256': core.canonical_hash(evidence['independent_review'])}
    actor = authority['credential_actor']
    for key, value in expected.items():
        if record[key] != value:
            errors.append('Final signoff is stale: ' + key)
    if actor is None or actor['id'] != record['credential_actor_id']:
        errors.append('Final signoff credential actor differs')
    if record['event']['binding_sha256'] != authorization.event_hash(record):
        errors.append('Final human event binding hash differs')
    mandate = context.get('mandate', {})
    if (record['id'] == mandate.get('id') or record['nonce'] == mandate.get('nonce') or
            record['event']['reference'] == mandate.get('event', {}).get('reference')):
        errors.append('Final signoff must be a distinct later human event')
    try:
        issued, expires = authorization.interval(record, now)
        own_pr = publication.get('own_pr')
        if (now >= expires or not own_pr or issued < authorization.timestamp(own_pr['created_at']) or
                issued < authorization.timestamp(evidence['independent_review']['reviewed_at'])):
            raise ValueError('Final signoff must be current and follow publication and independent review')
    except (ValueError, OverflowError) as exc:
        errors.append(str(exc))
    if not review['valid']:
        errors.append('Final signoff requires valid independent review')
    result.update(valid=not errors, status='passed' if not errors else 'invalid')
    return result


def without_own(duplicates, own):
    if own is None:
        return list(duplicates)
    return [item for item in duplicates if not (item['repository'] == own['repository'] and
            item['number'] == own['number'] and item['url'] == own['url'])]


def verify(task, evidence=None, repo_dir=None, host_context=None, client=None):
    errors = core.validate_contract(task)
    result = {'schema_version': '0.2', 'schema_valid': not errors,
              'repository_approval': {'status': 'unknown', 'reason': 'Not refreshed'},
              'user_authorization': {}, 'implementation_ready': False, 'technical_evidence_valid': False,
              'independent_review': {'valid': False, 'status': 'pending', 'errors': []},
              'draft_create_ready': False,
              'publication': {'status': 'unknown', 'verified': False, 'creation_clear': False,
                              'own_pr': None, 'errors': [], 'provenance': {}},
              'human_signoff': {'valid': False, 'status': 'pending', 'errors': []},
              'completion_ready': False, 'next_action': 'resolve_blockers', 'errors': errors,
              'evidence_errors': [], 'stage_blockers': {}, 'blocking_duplicates': [],
              'evidence_trust': 'self-attested; identity and truth are not authenticated',
              'mandate_trust': 'host-asserted', 'mandate_sha256': None, 'final_signoff_sha256': None}
    if errors:
        return result
    client = client or core.GitHub()
    now = dt.datetime.now(dt.timezone.utc)
    digest = core.canonical_hash(task)
    source = task['source']
    result.update(contract_sha256=digest, source_identity={key: source[key] for key in
                  ('repository', 'repository_id', 'owner_id', 'issue', 'issue_id')}, live_complete=False)
    errors.extend(core.reviewed_contract_errors(task, '0.2'))
    # Contract-only route checks hold with or without a mandate (A2-02); authorization.check repeats them for its
    # own historical validity, so its copies are not listed twice below.
    route = authorization.route_errors(task)
    errors.extend(route)
    current = None
    live_duplicates = []
    scan_ids = {}
    try:
        current = core.inspect_issue(source['repository'] + '#' + str(source['issue']), client, pr_ids=scan_ids)
        if 'source' not in current:
            raise core.ProtocolError('refresh_incomplete', 'Current issue/source could not be read completely')
        result.update(repository_approval=current['approval'], live_complete=current['complete'],
                      live_provenance=current['provenance'])
        if not current['complete']:
            errors.append('Live discovery is incomplete')
            errors.extend(current['errors'])
        if current['approval']['status'] == 'unknown':
            errors.append('Repository approval policy is unresolved')
        if current['exclusions']:
            errors.append('Live issue is excluded: ' + ', '.join(current['exclusions']))
        for key in ('issue_sha256', 'instructions_sha256', 'default_branch', 'repository', 'issue_url'):
            if source[key] != current['source'][key]:
                errors.append('Source changed; refresh and review contract: ' + key)
        if source['policy_sha256'] != authorization.policy_hash(current['provenance']):
            errors.append('Source policy state/content changed; refresh and review contract')
        status = core.compare_relation(client, source['repository'], current['source']['commit'], source['commit'])
        if status not in ('behind', 'identical'):
            errors.append('Reviewed source commit is not in current source default-branch history: ' +
                          core.base_relation(task, source['commit'], current['source']['commit'], status))
        live_duplicates = [dict(item, repository=source['repository']) for item in current['duplicates']]
    except core.ProtocolError as exc:
        errors.append('Live GitHub refresh failed: ' + str(exc))
    authority = authorization.check(task, host_context, client, now)
    result.update(user_authorization=authority, mandate_sha256=authority['mandate_sha256'])
    historical_errors = list(errors) + [error for error in authority['errors'] if error not in route]
    from .tipjar import live_errors
    jar_errors = live_errors(task, current, client) if current and 'source' in current else ['Tipjar source refresh unresolved']
    action_errors = historical_errors + authority['current_errors'] + jar_errors
    disposition, waived, observed = None, set(), []
    if isinstance(host_context, dict) and host_context.get('schema_version') == '0.2':
        if core.schema_errors(host_context, core.host_context_schema(host_context)):
            disposition = dict(dispositions.report(), status='invalid', errors=['Host context schema is invalid'])
        else:
            disposition, waived, observed = dispositions.evaluate(task, host_context, authority, current, client,
                                                                  dt.datetime.now(dt.timezone.utc), scan_ids)
    # A disposition only ever removes the disposed topical entries; anything it observed blocks.
    waived_items = [item for item in live_duplicates + task['discovery']['duplicate_prs']
                    if item.get('repository') == source['repository'] and item['number'] in waived]
    all_duplicates = [item for item in live_duplicates + task['discovery']['duplicate_prs']
                      if item not in waived_items] + observed
    result['duplicates'] = live_duplicates + [item for item in observed if item.get('observed_in')]
    implementation_errors = list(action_errors)
    if not authority['implement']:
        implementation_errors.append('Current implement action is not authorized')
    if all_duplicates:
        implementation_errors.append('Issue overlaps an open or unresolved prepared PR')
    if evidence is None:
        result['evidence_errors'] = ['No technical execution evidence provided']
    else:
        result['evidence_errors'] = core.check_evidence(task, evidence, repo_dir, digest,
            current_commit=current['source']['commit'] if current and 'source' in current else None,
            client=client, schema_version='0.2', attestations=())
        result['technical_evidence_valid'] = not result['evidence_errors']
    review = independent_review(task, evidence, now)
    result['independent_review'] = review
    publication = result['publication']
    unchecked = HISTORY_UNCHECKED
    # A host-context 0.2 draft_update record replaces creation-head recognition with the update path (#21 slice 2):
    # with a record present the draft at the creation head is never recognized, so no completion can bypass it.
    update, live_head = None, None
    if isinstance(host_context, dict) and host_context.get('schema_version') == '0.2' and 'draft_update' in host_context:
        update = draft_updates.evaluate(task, host_context, authority, now)
    if authority['historical_valid'] and update is None:
        claim = host_context.get('publication')
        head = evidence['git_head'] if result['technical_evidence_valid'] else None
        publication = check_publication(authority['binding'], claim, head, client)
        result['publication'] = publication
    elif authority['historical_valid'] and update['status'] != 'invalid':
        record = host_context['draft_update']
        head = evidence['git_head'] if result['technical_evidence_valid'] else None
        publication, live_head = check_updated_publication(authority['binding'], host_context.get('publication'),
                                                           record['from_head'], head, client)
        if publication['verified']:
            publication['errors'].extend(draft_updates.technical_errors(task, record, evidence, repo_dir))
        result['publication'] = publication
    if publication['status'] != 'absent' or not publication['creation_clear'] or publication['errors']:
        implementation_errors.append('Implementation requires complete empty exact-head PR history'
                                     if authority['historical_valid'] else unchecked)
    result['implementation_ready'] = not implementation_errors
    stage_errors = historical_errors + jar_errors + result['evidence_errors'] + review['errors']
    if not review['valid'] and not review['errors']:
        stage_errors.append('Independent review is pending')
    if not {'implement', 'create_draft'}.issubset(authority['actions']):
        stage_errors.append('Both implement and create_draft actions must be authorized')
    own = publication['own_pr'] if publication['verified'] else None
    if own is not None and scan_ids.get(own['number']) != own['id']:
        # The open scan must list the own draft with the same numeric ID before it is exempted (FR1-02).
        publication['errors'].append('Open-PR scan and exact-head history disagree on the draft pull request '
                                     'identity; repeat the complete read')
        own = None
    blocking = without_own(all_duplicates, own)
    result['blocking_duplicates'] = blocking
    post_errors = stage_errors + publication['errors']
    if blocking:
        post_errors.append('Unresolved overlapping PRs remain')
    identity_verified = publication['verified']
    publication['identity_verified'] = identity_verified
    publication['verified'] = bool(identity_verified and not post_errors)
    publication['stage_errors'] = post_errors
    draft_errors = stage_errors + authority['current_errors'] + publication['errors']
    if all_duplicates:
        draft_errors.append('Issue overlaps an open or unresolved prepared PR')
    if not authority['implement'] or not authority['create_draft']:
        draft_errors.append('Current implement/create_draft actions are not authorized')
    if not publication['creation_clear']:
        draft_errors.append('Exact-head PR history does not permit creation' if authority['historical_valid'] else unchecked)
    result['draft_create_ready'] = not draft_errors and not identity_verified
    ci_blockers = []
    if cigate.requirements(task):  # opt-in; read before the expiry judgements below (#17)
        result['ci_gate'], ci_blockers = cigate.evaluate(task, evidence, repo_dir, publication, client)
    # Judge final sign-off expiry after every blocking read, never at the start of verification.
    signoff = human_signoff(task, host_context, evidence, authority, publication, review,
                            dt.datetime.now(dt.timezone.utc))
    if update is not None and signoff['valid']:
        try:  # the CLI-visible half of host rule 6: a sign-off must postdate the update round
            if authorization.timestamp(host_context['final_signoff']['issued_at']) <= authorization.timestamp(
                    host_context['draft_update']['issued_at']):
                signoff = dict(signoff, valid=False, status='invalid',
                               errors=signoff['errors'] + ['Final signoff must follow the draft update round'])
        except (ValueError, OverflowError, KeyError, TypeError):
            signoff = dict(signoff, valid=False, status='invalid',
                           errors=signoff['errors'] + ['Final signoff must follow the draft update round'])
    result['human_signoff'] = signoff
    result['final_signoff_sha256'] = signoff['sha256']
    completion_errors = list(post_errors) + signoff['errors']
    if not publication['verified']:
        completion_errors.append('An exact-head published draft is not fully verified')
    if not signoff['valid']:
        completion_errors.append('Final human signoff is pending or invalid')
    completion_errors += ci_blockers
    result['completion_ready'] = not completion_errors
    result['stage_blockers'] = {'implementation': implementation_errors,
                                'draft': [] if publication['verified'] else draft_errors,
                                'completion': completion_errors}
    result['errors'] = list(dict.fromkeys(historical_errors + authority['current_errors'] + jar_errors))
    if publication['verified']:
        result['next_action'] = 'none'
    elif result['draft_create_ready']:
        result['next_action'] = 'create_draft'
    elif result['implementation_ready']:
        result['next_action'] = 'implement'
    if disposition is not None:
        # Judge expiry again after every blocking read; a waiver that expired meanwhile fails closed.
        expired = dispositions.expiry_errors(host_context['overlap_dispositions'], dt.datetime.now(dt.timezone.utc)) \
            if disposition['status'] == 'evaluated' else []
        if expired and disposition['waived']:
            disposition.update(status='invalid', waived=[])
            result['blocking_duplicates'] = result['blocking_duplicates'] + waived_items
            for stage in ('implementation', 'draft', 'completion'):
                result['stage_blockers'][stage].append(expired[0])
            result.update(implementation_ready=False, draft_create_ready=False, completion_ready=False,
                          next_action='resolve_blockers')
            result['publication']['verified'] = False
        disposition['errors'] = list(dict.fromkeys(disposition['errors'] + expired))
        result['overlap_dispositions'] = disposition
        result['waived_duplicates'] = disposition['waived']
    if update is not None:
        # Currency is judged again after every blocking read; recognition itself does not need a current record.
        now_after = dt.datetime.now(dt.timezone.utc)
        current = draft_updates.evaluate(task, host_context, authority, now_after)['current']
        result['draft_update'] = draft_updates.finish(dict(update, current=current), result['publication'],
                                                      live_head, evidence, now_after)
    return result
