"""Read-only exact-head draft observations, never publication authorization."""
from __future__ import annotations

import datetime as dt
import re
from urllib.parse import quote

from .authorization import positive as _positive_id
from .core import ProtocolError, paginate, parse_repository

_BINDING_KEYS = {'target_repository', 'target_repository_id', 'head_repository',
                 'head_repository_id', 'head_ref', 'base_ref', 'credential_actor_id',
                 'contract_sha256', 'mandate_sha256', 'issued_at', 'expires_at'}
_CLAIM_KEYS = {'repository_id', 'pr_number', 'pr_id', 'head_sha',
               'contract_sha256', 'mandate_sha256'}


def _require(condition, message):
    if not condition:
        raise ProtocolError('publication_shape', message)


def _hex(value, length):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{%d}' % length, value) is not None


def _ref(value):
    # Deliberately not authorization.valid_ref: GitHub may report any Git-valid ref (up to 1024, HEAD allowed),
    # while reviewed refs are narrower (200, no HEAD). Bound publications still match reviewed refs exactly.
    if not isinstance(value, str) or not value or len(value) > 1024:
        return False
    if (value == '@' or value.startswith(('-', '/')) or value.endswith(('/', '.'))
            or '..' in value or '@{' in value
            or any(ord(c) <= 32 or ord(c) == 127 or c in '~^:?*[\\' for c in value)):
        return False
    return all(part and not part.startswith('.') and not part.endswith('.lock')
               for part in value.split('/'))


def _timestamp(value):
    # Same RFC3339 subset as authorization.timestamp, but parsed without fromisoformat and failing as
    # publication_shape; the two are kept separate so each error contract stays unchanged.
    # Parse the same RFC3339 subset on every supported Python, without truncation.
    match = re.fullmatch(
        r'([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})'
        r'(?:\.([0-9]{1,6}))?(Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])', value
    ) if isinstance(value, str) else None
    _require(match is not None and match[8] != '-00:00',
             'Expected RFC3339 timestamp with a known offset and at most six fractional digits')
    try:
        zone = match[8]
        offset = dt.timedelta(0) if zone == 'Z' else dt.timedelta(
            hours=int(zone[1:3]), minutes=int(zone[4:6])) * (1 if zone[0] == '+' else -1)
        return dt.datetime(*(int(match[n]) for n in range(1, 7)),
                           microsecond=int((match[7] or '').ljust(6, '0')),
                           tzinfo=dt.timezone(offset))
    except ValueError as exc:
        raise ProtocolError('publication_shape', 'Invalid publication timestamp') from exc


def _binding(binding):
    _require(isinstance(binding, dict) and set(binding) == _BINDING_KEYS,
             'Publication binding is missing fields or has unknown fields')
    for key in ('target_repository_id', 'head_repository_id', 'credential_actor_id'):
        _require(_positive_id(binding[key]), 'Publication binding requires positive numeric IDs')
    for key in ('target_repository', 'head_repository'):
        parse_repository(binding[key])
    _require(binding['target_repository_id'] == binding['head_repository_id']
             and binding['target_repository'] == binding['head_repository'],
             'Only the same-repository publication route is supported')
    _require(_ref(binding['head_ref']) and _ref(binding['base_ref']),
             'Invalid publication head or base ref')
    _require(all(_hex(binding[key], 64) for key in ('contract_sha256', 'mandate_sha256')),
             'Publication binding requires contract and mandate hashes')
    issued, expires = _timestamp(binding['issued_at']), _timestamp(binding['expires_at'])
    _require(dt.timedelta(0) < expires - issued <= dt.timedelta(hours=24),
             'Publication mandate interval must be positive and at most 24 hours')
    return issued, expires


def _claim(claim):
    _require(isinstance(claim, dict) and set(claim) == _CLAIM_KEYS,
             'Publication claim is missing fields or has unknown fields')
    _require(all(_positive_id(claim[key]) for key in ('repository_id', 'pr_number', 'pr_id')),
             'Publication claim requires positive numeric IDs')
    _require(_hex(claim['head_sha'], 40)
             and all(_hex(claim[key], 64) for key in ('contract_sha256', 'mandate_sha256')),
             'Invalid publication claim hashes')


def _pr_facts(value, *, detail=False):
    _require(isinstance(value, dict), 'Expected a GitHub pull request object')
    _require(_positive_id(value.get('id')) and _positive_id(value.get('number')),
             'Pull request requires positive numeric ID and number')
    _require(isinstance(value.get('html_url'), str), 'Pull request URL is missing')
    _require(value.get('state') in ('open', 'closed'), 'Unknown pull request state')
    _require(type(value.get('draft')) is bool, 'Pull request draft state is missing')
    _require('merged_at' in value, 'Pull request merge timestamp is missing')
    if value['merged_at'] is not None:
        _timestamp(value['merged_at'])
    _timestamp(value.get('created_at'))
    user = value.get('user')
    _require(isinstance(user, dict) and _positive_id(user.get('id'))
             and user.get('type') == 'User', 'Pull request author is not a personal user')
    facts = {key: value[key] for key in ('id', 'number', 'state', 'draft', 'merged_at', 'created_at')}
    facts.update(url=value['html_url'], author_id=user['id'])
    for side in ('head', 'base'):
        branch = value.get(side)
        _require(isinstance(branch, dict) and _ref(branch.get('ref')),
                 'Pull request head or base ref is invalid')
        repo = branch.get('repo')
        _require(isinstance(repo, dict) and _positive_id(repo.get('id')),
                 'Pull request head or base repository is absent or invalid')
        name = parse_repository(repo.get('full_name'))
        facts.update({side + '_repository': name, side + '_repository_id': repo['id'],
                      side + '_ref': branch['ref']})
        if side == 'head':
            _require(_hex(branch.get('sha'), 40), 'Pull request head SHA is invalid')
            facts['head_sha'] = branch['sha']
    if detail:
        _require(type(value.get('merged')) is bool, 'Pull request merged state is missing')
    return facts


def _route_matches(facts, binding):
    return all(facts[key] == binding[key] for key in
               ('head_repository', 'head_repository_id', 'head_ref', 'base_ref')) and (
        facts['base_repository'] == binding['target_repository']
        and facts['base_repository_id'] == binding['target_repository_id']
        and facts['url'] == f"https://github.com/{binding['target_repository']}/pull/{facts['number']}")


def check_publication(binding, publication_claim, expected_head, client):
    """Observe an absent branch history or one claimed exact-head draft.

    ``binding`` is the caller's normalized mandate binding, not a raw task.
    ``expected_head`` is the caller's validated evidence HEAD (or None).
    ``creation_clear`` reports only this module's history/timing checks; callers
    must separately enforce authority, evidence, approval and unrelated overlaps.
    A publication claim is untrusted association data, never permission.
    Binding timestamps require RFC3339 with a known offset and at most six
    fractional digits; unsupported precision fails closed.
    """
    result = {'status': 'unknown', 'verified': False, 'creation_clear': False,
              'own_pr': None, 'errors': [],
              'provenance': {'publication_claim_trust': 'untrusted',
                             'authority_evaluated': False}}

    def blocked(message):
        result['status'] = 'blocked'
        result['errors'].append(message)
        return result

    try:
        issued, expires = _binding(binding)
        if expected_head is not None:
            _require(_hex(expected_head, 40), 'Invalid expected evidence HEAD')
        if publication_claim is not None:
            _claim(publication_claim)
        repository = binding['target_repository']
        head_owner = binding['head_repository'].split('/')[0]
        endpoint = (f'repos/{repository}/pulls?state=all'
                    f"&head={quote(head_owner + ':' + binding['head_ref'], safe='')}"
                    f"&base={quote(binding['base_ref'], safe='')}&sort=created&direction=asc")
        history = paginate(client, endpoint)
        result['provenance']['history'] = {
            'endpoint': endpoint, 'complete': history['complete'], 'pages': history['pages'],
            'matches': len(history['items']), 'errors': history['errors']}
        if not history['complete']:
            result['errors'].extend(history['errors'])
            return result
        facts = [_pr_facts(item) for item in history['items']]
        _require(all(_route_matches(item, binding) for item in facts),
                 'Exact-head history returned a different repository, ref or URL')
        _require(len({item['number'] for item in facts}) == len(facts),
                 'Exact-head history repeated a pull request number')
        if publication_claim is None:
            if facts:
                return blocked('Existing open or closed exact-head history blocks draft creation')
            if not issued <= dt.datetime.now(dt.timezone.utc) < expires:
                return blocked('Publication mandate is not current for draft creation')
            result.update(status='absent', creation_clear=True)
            return result
        claim = publication_claim
        if (claim['repository_id'] != binding['target_repository_id']
                or claim['contract_sha256'] != binding['contract_sha256']
                or claim['mandate_sha256'] != binding['mandate_sha256']):
            return blocked('Publication claim does not match the reviewed binding')
        if expected_head is None or claim['head_sha'] != expected_head:
            return blocked('Publication claim requires the exact validated evidence HEAD')
        if len(facts) != 1 or facts[0]['id'] != claim['pr_id'] or facts[0]['number'] != claim['pr_number']:
            return blocked('Publication claim requires exactly one matching historical pull request')
        detail_endpoint = f"repos/{repository}/pulls/{claim['pr_number']}"
        result['provenance']['detail_endpoint'] = detail_endpoint
        detail = client.request(detail_endpoint)
        current = _pr_facts(detail, detail=True)
        _require(current == facts[0], 'Pull request list/detail race; repeat the complete read')
        if (current['author_id'] != binding['credential_actor_id']
                or current['state'] != 'open' or current['draft'] is not True
                or detail['merged'] is not False or current['merged_at'] is not None):
            return blocked('Claimed publication is not an open unmerged draft by the bound actor')
        if current['head_sha'] != expected_head:
            return blocked('Published head differs from the exact validated evidence HEAD')
        if not issued <= _timestamp(current['created_at']) < expires:
            return blocked('Pull request was created outside the publication mandate interval')
        if _timestamp(current['created_at']) > dt.datetime.now(dt.timezone.utc):  # judged after the reads (FR1-03)
            return blocked('Pull request creation time is in the future')
        result.update(status='own_draft', verified=True, own_pr={
            'repository': repository, 'repository_id': binding['target_repository_id'],
            **{key: current[key] for key in ('number', 'id', 'url', 'head_sha', 'head_ref',
                                           'base_ref', 'author_id', 'created_at')}})
        return result
    except ProtocolError as exc:
        result['errors'].append(str(exc))
        return result
