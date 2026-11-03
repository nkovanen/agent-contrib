"""One bounded public code-search batch; every invitation is verified independently."""
import copy
import datetime as dt
import re
from urllib.parse import urlencode

from . import core, tipjar

QUERY = 'filename:.tipjar.json path:/'
NOTICE = ('Only verified welcome observations are selectable. An invitation is not issue approval or '
          'execution/publication authority; read all contribution policies. Snapshots are not atomic.')
LIMITATIONS = [
    'One page of at most ten indexed hits; not a global census or fair rotation.',
    'Legacy code search omits repositories (especially forks); indexing may lag.',
    'Search has a separate quota; core budget snapshots do not measure it.',
    'gh may follow internal redirects; counters measure invocations, not raw HTTP requests.',
    'Find reads are uncached, including with --cache. Visibility can change after verification.']


def validate_owner(owner):
    if owner is not None and (not isinstance(owner, str) or
                              not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}', owner)):
        raise core.ProtocolError('usage', 'Expected a GitHub owner login (1-39 ASCII letters, digits or hyphens)')
    return owner


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _positive(value):
    return type(value) is int and value > 0


def _identity(meta):
    core.require(meta, dict, 'repository')
    name = core.parse_repository(meta.get('full_name'))
    owner = core.require(meta.get('owner'), dict, 'repository owner')
    if (not _positive(meta.get('id')) or not _positive(owner.get('id')) or
            not isinstance(owner.get('login'), str) or
            not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}', owner['login']) or
            owner['login'].casefold() != name.split('/')[0].casefold()):
        raise core.ProtocolError('api_shape', 'Invalid repository identity')
    return (meta['id'], name.casefold(), owner['id'], owner['login'].casefold())


def _observation(disposition='unknown', reason='invalid_hit', candidate=None):
    return {'repository': candidate['repository']['full_name'] if candidate else None,
            'repository_id': candidate['repository']['id'] if candidate else None,
            'disposition': disposition, 'reason': reason, 'verified_at': None, 'jar': None}


def _search_candidates(client, owner):
    query = QUERY + (' user:' + owner if owner is not None else '')
    search = dict(query=query, page=1, per_page=10, total_count=None, incomplete_results=None,
                  returned_count=None, truncated=None, short_page=None)
    report = dict(format='find-jars-report/1', fetched_at=_now(), owner=owner, search=search,
                  coverage={'exhaustive': False, 'limitations': list(LIMITATIONS)}, observations=[],
                  complete=False, errors=[], requests={'search': 0, 'core': 0}, notice=NOTICE)
    try:
        data = core.require(client.request_once('search/code?' + urlencode(
            {'q': query, 'per_page': 10, 'page': 1})), dict, 'search response')
        total, incomplete, items = data.get('total_count'), data.get('incomplete_results'), data.get('items')
        if (type(total) is not int or total < 0 or type(incomplete) is not bool or
                not isinstance(items, list) or len(items) > 10 or total < len(items)):
            raise core.ProtocolError('api_shape', 'Invalid search envelope')
    except core.ProtocolError:
        report['errors'] = ['search_failed']
        return [], report
    search.update(total_count=total, incomplete_results=incomplete, returned_count=len(items),
                  truncated=total > len(items), short_page=len(items) < min(total, 10))
    if incomplete:
        report['errors'].append('search_incomplete')
    if search['short_page']:
        report['errors'].append('short_page')
    records = []
    for hit in items:
        meta = hit.get('repository') if isinstance(hit, dict) else None
        meta = meta if isinstance(meta, dict) else {}
        partial_id = meta.get('id') if _positive(meta.get('id')) else None
        try:
            partial_name = core.parse_repository(meta.get('full_name')).casefold()
        except core.ProtocolError:
            partial_name = None
        record = {'hit': hit, 'identity': None, 'partial_id': partial_id, 'partial_name': partial_name,
                  'observation': _observation(), 'conflict': False}
        records.append(record)
        try:
            core.require(hit, dict, 'search hit')
            identity = _identity(hit.get('repository'))
            record['identity'] = identity
            meta = hit['repository']
            if type(meta.get('private')) is not bool:
                raise core.ProtocolError('api_shape', 'Invalid visibility')
            if meta['private']:
                record['observation'] = _observation('excluded', 'private')
                continue
            if hit.get('name') != tipjar.PATH or hit.get('path') != tipjar.PATH:
                record['observation'] = _observation('excluded', 'nonroot_path', hit)
                continue
            if not isinstance(hit.get('sha'), str) or not core.SHA.fullmatch(hit['sha']):
                raise core.ProtocolError('api_shape', 'Invalid indexed blob')
            if owner is not None and identity[3] != owner.casefold():
                record['observation'] = _observation('excluded', 'owner_filter', hit)
                continue
            record['observation'] = _observation('unknown', 'pending_verification', hit)
        except core.ProtocolError:
            pass
    # Compare the entire page before any repository read. Every exact duplicate of a
    # conflicting record is invalid too; numeric ids and names must map one-to-one.
    for i, left in enumerate(records):
        a = left['identity']
        for right in records[i + 1:]:
            b = right['identity']
            same_repo = (left['partial_id'] is not None and left['partial_id'] == right['partial_id'] or
                         left['partial_name'] is not None and left['partial_name'] == right['partial_name'])
            owner_conflict = a is not None and b is not None and (a[2] == b[2]) != (a[3] == b[3])
            if owner_conflict or same_repo and (a is None or b is None or a != b or
                    any(left['hit'].get(key) != right['hit'].get(key) for key in ('sha', 'name', 'path')) or
                    left['hit']['repository'].get('private') != right['hit']['repository'].get('private')):
                left['conflict'] = right['conflict'] = True
    candidates, seen = [], set()
    for record in records:
        identity, obs = record['identity'], record['observation']
        if record['conflict']:
            obs = _observation('unknown', 'conflicting_hits')
        elif identity is not None:
            if identity in seen:
                continue
            seen.add(identity)
        index = len(report['observations'])
        report['observations'].append(obs)
        if obs['reason'] == 'pending_verification':
            candidates.append({'identity': identity, 'index': index})
    return candidates, report


def _metadata(meta, candidate, branch=None):
    # Suppress all data when a response reports private, including moved identities.
    if isinstance(meta, dict) and (meta.get('private') is True or meta.get('visibility') == 'private'):
        return 'private'
    if _identity(meta) != candidate['identity']:
        raise core.ProtocolError('api_shape', 'Repository identity changed')
    for field in ('private', 'archived', 'disabled'):
        if type(meta.get(field)) is not bool:
            raise core.ProtocolError('api_shape', 'Invalid repository eligibility')
    if meta.get('visibility') != 'public':
        raise core.ProtocolError('api_shape', 'Unknown visibility')
    if meta['archived'] or meta['disabled']:
        return 'archived' if meta['archived'] else 'disabled'
    default = meta.get('default_branch')
    if (not isinstance(default, str) or not default or len(default) > 1024 or
            re.search(r'[\x00-\x20\x7f~^:?*\[\\]', default) or default == '@' or
            '..' in default or '@{' in default or default.endswith('.') or
            any(not part or part.startswith('.') or part.endswith('.lock') for part in default.split('/')) or
            branch is not None and default != branch):
        raise core.ProtocolError('api_shape', 'Invalid or changed default branch')
    return None


class _Reads:
    def __init__(self, client):
        # A shallow client copy preserves the caller's cache preference and transport.
        self.client = copy.copy(client) if hasattr(client, 'use_cache') else client
        if hasattr(self.client, 'use_cache'):
            self.client.use_cache = False
        self.counts = {'search': 0, 'core': 0}

    def request_once(self, endpoint):
        self.counts['search' if endpoint.startswith('search/code?') else 'core'] += 1
        return self.client.request_once(endpoint)


def find_jars(client=None, *, owner=None):
    """Verify a partial batch; never select unknowns or treat invitations as authority."""
    validate_owner(owner)
    reads = _Reads(client or core.GitHub(use_cache=False))
    candidates, report = _search_candidates(reads, owner)
    for candidate in candidates:
        obs = report['observations'][candidate['index']]
        endpoint = 'repos/' + obs['repository']
        try:
            meta = reads.request_once(endpoint)
            exclusion = _metadata(meta, candidate)
            obs['verified_at'] = _now()
            if exclusion:
                obs.update(disposition='excluded', reason=exclusion)
                if exclusion == 'private':
                    obs.update(repository=None, repository_id=None)
                continue
            jar = tipjar.read_jar(obs['repository'], reads, metadata=meta)
            if jar['complete'] and jar['state'] == 'welcome':
                final = reads.request_once(endpoint)
                exclusion = _metadata(final, candidate, meta['default_branch'])
                obs['verified_at'] = _now()
                if exclusion:
                    obs.update(disposition='excluded', reason=exclusion)
                    if exclusion == 'private':
                        obs.update(repository=None, repository_id=None)
                    continue
            # Only complete reader reports enter public output, unchanged.
            if not jar['complete']:
                obs.update(disposition='unknown', reason='jar_unverified')
            else:
                obs.update(jar=jar, disposition=jar['state'], reason='verified_' + jar['state'])
        except core.ProtocolError:
            obs.update(disposition='unknown', reason='metadata_unverified', jar=None)
    report['requests'] = reads.counts
    report['complete'] = not report['errors'] and all(
        obs['disposition'] != 'unknown' for obs in report['observations'])
    return report
