"""Host assertions bind scope; live GETs establish credential facts, not consent."""
from __future__ import annotations

import datetime as dt
import re
from urllib.parse import quote

from . import core


_TIMESTAMP = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})')
_LOGIN = re.compile(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?')


def timestamp(value):
    # Limit the dialect explicitly; fromisoformat accepts more on newer Pythons.
    if not isinstance(value, str) or not _TIMESTAMP.fullmatch(value):
        raise ValueError('Expected a timezone-aware RFC3339 timestamp')
    offset = value[-6:] if not value.endswith('Z') else '+00:00'
    if offset == '-00:00' or int(offset[1:3]) > 23 or int(offset[4:6]) > 59:
        raise ValueError('Invalid or unknown timezone offset')
    normalized = value[:-1] + '+00:00' if value.endswith('Z') else value
    if '.' in normalized:
        normalized = re.sub(r'\.([0-9]{1,6})(?=[+-])', lambda match: '.' + match[1].ljust(6, '0'), normalized)
    return dt.datetime.fromisoformat(normalized)


def valid_ref(value):
    return (isinstance(value, str) and 0 < len(value) <= 200 and value not in ('HEAD', '@') and
            not value.startswith(('-', '/')) and not value.endswith(('/', '.')) and
            not any(part in value for part in ('..', '@{', '//')) and
            not re.search(r'[\x00-\x20\x7f~^:?*\[\\]', value) and
            all(not part.startswith('.') and not part.endswith('.lock') for part in value.split('/')))


def positive(value):
    return type(value) is int and value > 0


def repository_identity(repository, client):
    meta = core.repository_metadata(repository, client)
    owner = core.require(meta.get('owner'), dict, 'repository owner')
    if (meta['full_name'] != repository or not positive(meta.get('id')) or not positive(owner.get('id')) or
            owner.get('login') != repository.split('/')[0] or owner.get('type') not in ('User', 'Organization')):
        raise core.ProtocolError('identity_changed', 'Repository ID, canonical name or owner is unresolved')
    return meta


def issue_identity(repository, number, client):
    issue = core.issue_data(client.request(f'repos/{repository}/issues/{number}'), number)
    if (not positive(issue.get('id')) or issue.get('repository_url') != f'https://api.github.com/repos/{repository}' or
            issue['html_url'] != f'https://github.com/{repository}/issues/{number}'):
        raise core.ProtocolError('identity_changed', 'Issue ID or canonical repository URL is unresolved')
    return issue


def policy_hash(provenance):
    return core.canonical_hash({'state': provenance['policy_state'], 'policy': provenance['policy']})


def event_hash(record):
    payload = {key: value for key, value in record.items() if key != 'event'}
    payload['event'] = {key: value for key, value in record['event'].items() if key != 'binding_sha256'}
    return core.canonical_hash(payload)


def interval(record, now):
    issued, expires = timestamp(record['issued_at']), timestamp(record['expires_at'])
    if issued > now or not issued < expires or expires - issued > dt.timedelta(hours=24):
        raise ValueError('Invalid human event interval (future, reversed or over 24 hours)')
    return issued, expires


def route_errors(task):
    """Contract-only route checks; they need no mandate or GitHub read."""
    errors = []
    source, execution = task['source'], task['execution']
    if (execution['target_repository'] != source['repository'] or execution['head_repository'] != source['repository'] or
            execution['target_repository_id'] != source['repository_id'] or execution['head_repository_id'] != source['repository_id']):
        errors.append('Only the same repository source/target/head route is supported')
    if execution['mode'] != 'repository-candidate':
        errors.append('Execution mode is pending')
    for key in ('head_ref', 'base_ref'):
        if not valid_ref(execution[key]):
            errors.append('Invalid reviewed Git ref: ' + key)
    if execution['base_ref'] != source['default_branch']:
        errors.append('Candidate base ref must match the source default branch')
    if execution['head_ref'] == execution['base_ref']:
        errors.append('Head and base refs must differ')
    return errors


def check(task, host_context, client, now):
    result = {'authorized': False, 'historical_valid': False, 'implement': False, 'create_draft': False,
              'mandate_trust': 'host-asserted', 'mandate_sha256': None,
              'credential_actor': None, 'permission': None, 'binding': None, 'actions': [],
              'errors': [], 'current_errors': [], 'source_errors': [], 'provenance': {'fetched_at': now.isoformat(), 'endpoints': []}}
    errors = result['errors']
    source, execution = task['source'], task['execution']
    try:
        result['provenance']['endpoints'].append('user')
        actor = core.require(client.request('user'), dict, 'credential actor')
        if (not positive(actor.get('id')) or actor.get('type') != 'User' or
                not isinstance(actor.get('login'), str) or not _LOGIN.fullmatch(actor['login'])):
            raise core.ProtocolError('credential_identity', 'Credential must identify a personal GitHub user')
        result['credential_actor'] = {key: actor[key] for key in ('id', 'login', 'type')}
        endpoint = f'repos/{source["repository"]}/collaborators/{quote(actor["login"], safe="")}/permission'
        result['provenance']['endpoints'].append(endpoint)
        permission = core.require(client.request(endpoint), dict, 'collaborator permission')
        user = core.require(permission.get('user'), dict, 'collaborator user')
        if (permission.get('role_name') not in ('admin', 'maintain') or not positive(user.get('id')) or
                user['id'] != actor['id'] or user.get('type') != 'User' or
                not isinstance(user.get('login'), str) or not _LOGIN.fullmatch(user['login']) or
                user['login'].casefold() != actor['login'].casefold()):  # ASCII-only, so casefold cannot fold confusables
            raise core.ProtocolError('credential_permission', 'Credential needs exact admin/maintain role and matching user ID')
        result['permission'] = {'role_name': permission['role_name'], 'user_id': user['id'], 'endpoint': endpoint}
        try:
            result['provenance']['endpoints'].append('repos/' + source['repository'])
            meta = repository_identity(source['repository'], client)
            if meta['id'] != source['repository_id'] or meta['owner']['id'] != source['owner_id']:
                raise core.ProtocolError('identity_changed', 'Reviewed repository or owner identity changed')
            result['provenance']['endpoints'].append(f'repos/{source["repository"]}/issues/{source["issue"]}')
            issue = issue_identity(source['repository'], source['issue'], client)
            if issue['id'] != source['issue_id']:
                raise core.ProtocolError('identity_changed', 'Reviewed issue identity changed')
        except core.ProtocolError as exc:
            # Observed source facts, unlike credential/mandate authority, stay visible to reports without host context.
            result['source_errors'].append(str(exc))
            raise
    except core.ProtocolError as exc:
        errors.append(str(exc))
    if host_context is None:
        errors.append('Missing human/host mandate')
        return result
    host_errors = core.schema_errors(host_context, core.host_context_schema(host_context))
    if host_errors:
        errors.extend('Host context ' + error for error in host_errors)
        return result
    mandate = host_context['mandate']
    result.update(mandate_sha256=core.canonical_hash(mandate), mandate_id=mandate['id'],
                  event_reference=mandate['event']['reference'], event_text_sha256=mandate['event']['text_sha256'],
                  actions=list(mandate['actions']))
    expected = {'contract_sha256': core.canonical_hash(task), 'source_repository_id': source['repository_id'],
                'source_owner_id': source['owner_id'], 'issue_id': source['issue_id'], 'issue_number': source['issue']}
    for key in ('target_repository', 'target_repository_id', 'head_repository', 'head_repository_id', 'head_ref', 'base_ref'):
        expected[key] = execution[key]
    for key, value in expected.items():
        if mandate[key] != value:
            errors.append('Mandate binding differs: ' + key)
    errors.extend(route_errors(task))
    if (len(set(mandate['actions'])) != len(mandate['actions']) or
            len(set(execution['requested_actions'])) != len(execution['requested_actions']) or
            not set(mandate['actions']).issubset(execution['requested_actions'])):
        errors.append('Mandate actions are duplicated or exceed reviewed requested actions')
    actor = result['credential_actor']
    if actor is None or actor['id'] != mandate['credential_actor_id']:
        errors.append('Mandate credential actor ID differs from current credential')
    if mandate['authority'] == 'owner' and mandate['credential_actor_id'] != source['owner_id']:
        errors.append('Owner authority claim does not match repository owner ID')
    if mandate['event']['binding_sha256'] != event_hash(mandate):
        errors.append('Human event binding hash differs')
    review = mandate['policy_review']
    if (review['status'] != 'clear' or review['instructions_sha256'] != source['instructions_sha256'] or
            review['policy_sha256'] != source['policy_sha256']):
        errors.append('Pinned human/host policy review is blocked, unknown or stale')
    try:
        _, expires = interval(mandate, now)
        if now >= expires:
            result['current_errors'].append('Human/host mandate has expired for new actions')
    except (ValueError, OverflowError) as exc:
        errors.append(str(exc))
    if not errors:
        result['historical_valid'] = True
        result['binding'] = {key: mandate[key] for key in ('target_repository', 'target_repository_id',
                            'head_repository', 'head_repository_id', 'head_ref', 'base_ref', 'credential_actor_id',
                            'contract_sha256', 'issued_at', 'expires_at')}
        result['binding']['mandate_sha256'] = result['mandate_sha256']
        result['authorized'] = not result['current_errors']
        result['implement'] = result['authorized'] and 'implement' in mandate['actions']
        result['create_draft'] = result['authorized'] and 'create_draft' in mandate['actions']
    return result
