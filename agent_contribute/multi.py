"""Discover several repositories in one run (#13). Each keeps its own completeness, errors and provenance."""
from . import core

MAX_REPOSITORIES = 20


def read_repositories_file(path):
    """One owner/repo per line; blank lines and # comments are ignored."""
    try:
        text = core.read_regular(path, 64 * 1024).decode('utf-8')
    except (OSError, UnicodeError) as exc:
        raise core.ProtocolError('file_error', 'Cannot read bounded UTF-8 repositories file') from exc
    return [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith('#')]


def validate(repositories):
    if not 2 <= len(repositories) <= MAX_REPOSITORIES:
        raise core.ProtocolError('usage', f'Give between 2 and {MAX_REPOSITORIES} repositories for a multi-repository run')
    names = [core.parse_repository(name) for name in repositories]
    if len({name.casefold() for name in names}) != len(names):
        raise core.ProtocolError('usage', 'Repositories must be distinct')
    return names


def discover_many(repositories, client=None, *, signals=False, responsiveness=False, limit=None, welcomed_only=False):
    limit = core.validate_discovery_limit(limit)
    names = validate(repositories)
    client = client or core.GitHub()
    results, errors, candidates = [], [], []
    for name in names:
        try:
            options = {key: True for key, value in (('signals', signals), ('responsiveness', responsiveness)) if value}
            if welcomed_only:
                options['welcomed_only'] = True
            result = core.discover(name, client, **options)
        except core.ProtocolError as exc:  # one failure never aborts or completes another repository
            result = {'requested_repository': name, 'complete': False, 'errors': [str(exc)], 'issues': []}
        results.append(result)
        errors += [f'{name}: {error}' for error in result.get('errors', [])]
        for issue in result.get('issues', []) if result.get('selection', {}).get('included') is True else []:
            candidates.append({'repository': name, 'reference': issue['reference'], 'number': issue['number'],
                               'excluded': bool(issue['exclusions']), 'overlapping': bool(issue['duplicates']),
                               'low_likelihood': issue['ranking']['success_likelihood']['value'] == 'low',
                               'score': issue['signals']['score'] if signals else None,
                               'complete': issue['complete'] and result['complete'] is True})
    candidates.sort(key=lambda c: (c['excluded'], c['overlapping'], c['low_likelihood'], -(c['score'] or 0),
                                   c['repository'].casefold(), c['number']))
    result = {'repositories': results, 'complete': all(r.get('complete') is True for r in results),
            'errors': errors, 'candidates': candidates,
            'ordering': 'exclusions, overlaps, low likelihood' + (', higher signal score' if signals else '') +
                        ', then repository and issue number',
            'limits': {'max_repositories': MAX_REPOSITORIES, 'per_repository': 'same as single-repository discover'},
            'warning': 'Candidates only. Each repository is resolved separately; nothing grants execution authority.'}
    if limit is not None:
        candidates = candidates[:limit]
        references = {c['reference'] for c in candidates}
        for repository in results:
            core.limit_discovery(repository, limit, references)
        counts = {key: sum(r['display'][key] for r in results)
                  for key in ('total_issues_considered', 'returned', 'omitted', 'overlapping', 'excluded')}
        result['display'] = {'requested_limit': limit, **counts, 'truncated': counts['omitted'] > 0}
        result['candidates'] = candidates
    return result
