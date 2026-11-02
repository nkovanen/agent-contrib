"""Unsigned authorization requests: binding data for a human/host, never a mandate."""
from __future__ import annotations

from . import authorization, core, lifecycle

NOTICE = ('UNSIGNED REQUEST. Not a mandate; grants no authority. Contains no approval material: '
          'the host must render the complete contract from its own snapshot. Only the human/host '
          'issues a mandate; the worker relays it unchanged.')
DIAGNOSTICS_TRUST = 'untrusted diagnostics; may contain repository-authored paths; never approval material'
# Blockers that exist only because no mandate has been issued yet.
EXPECTED_BEFORE_MANDATE = ('Missing human/host mandate', 'Current implement action is not authorized',
                           'Implementation requires complete empty exact-head PR history', lifecycle.HISTORY_UNCHECKED)
HUMAN_ONLY_FIELDS = ['id', 'nonce', 'issued_at', 'expires_at', 'actions', 'policy_review.status',
                     'policy_review.notes', 'event.kind', 'event.reference', 'event.text_sha256',
                     'event.binding_sha256']


class InvalidContract(core.ProtocolError):
    """Carries the schema errors so every caller, with or without budget reads, reports the same payload."""

    def __init__(self, schema_errors):
        super().__init__('invalid_contract', 'Contract does not match its bundled schema')
        self.payload = {'error': {'code': self.code, 'message': str(self), 'schema_errors': schema_errors[:100]}}


def check_contract(task):
    """Fail before any GitHub read; route extraction indexes fields the schema guarantees."""
    if not isinstance(task, dict) or task.get('schema_version') != '0.2':
        raise core.ProtocolError('usage', 'Authorization requests require an explicit schema 0.2 contract')
    schema_errors = core.validate_contract(task)
    if schema_errors:
        raise InvalidContract(schema_errors)


def build(task, client=None):
    check_contract(task)
    verified = lifecycle.verify(task, client=client or core.GitHub())
    source, execution = task['source'], task['execution']
    actions = execution['requested_actions']
    errors = authorization.route_errors(task)
    if not actions:
        errors.append('Contract requests no actions')
    if len(set(actions)) != len(actions):
        errors.append('Contract requested actions are duplicated')
    errors += [error for error in verified['stage_blockers']['implementation'] if error not in EXPECTED_BEFORE_MANDATE]
    authority = verified['user_authorization']
    actor = authority['credential_actor'] if authority['permission'] else None
    actor_id = actor['id'] if actor else None
    fields = {'id': None, 'nonce': None, 'issued_at': None, 'expires_at': None,
              'contract_sha256': verified['contract_sha256'],
              'source_repository_id': source['repository_id'], 'source_owner_id': source['owner_id'],
              'issue_id': source['issue_id'], 'issue_number': source['issue'],
              'credential_actor_id': actor_id,
              'authority': None if actor_id is None else 'owner' if actor_id == source['owner_id'] else 'maintainer',
              'actions': None,
              'policy_review': {'status': None, 'instructions_sha256': source['instructions_sha256'],
                                'policy_sha256': source['policy_sha256'], 'notes': None},
              'event': {'kind': None, 'reference': None, 'text_sha256': None, 'binding_sha256': None}}
    for key in ('target_repository', 'target_repository_id', 'head_repository', 'head_repository_id', 'head_ref', 'base_ref'):
        fields[key] = execution[key]
    unresolved = [key for key in ('credential_actor_id', 'authority') if fields[key] is None]
    errors = list(dict.fromkeys(errors))
    return {'kind': 'agent-contrib/authorization-request', 'request_version': '0.1', 'issued': False,
            'notice': NOTICE, 'target_host_context_schema_version': '0.1',
            'ready_for_issuance': not errors and not unresolved,
            'preflight_errors': errors, 'preflight_errors_trust': DIAGNOSTICS_TRUST,
            'unresolved_fields': unresolved, 'contract_sha256': verified['contract_sha256'],
            'exact_head_pr_history': 'not checked before issuance; verify checks it after',
            'mandate_fields': fields, 'human_only_fields': list(HUMAN_ONLY_FIELDS),
            'provenance': authority['provenance']}
