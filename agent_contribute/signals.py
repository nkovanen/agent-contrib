"""Opt-in deterministic signals. Issue signals use data discover already read; repository
responsiveness makes one extra closed-PR read. Heuristics, never approval."""
import datetime as dt
import functools
import re
import statistics

from . import core

SCAN_LIMIT = 65536
MAX_HINTS = 20
# One character class with a fixed bound: linear scanning, no backtracking.
TOKEN = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_./-]{0,299}')
MARKERS = {'checklist': re.compile(r'(?m)^[ \t]{0,8}[-*] \[[ xX]\]'),
           'expected/actual sections': re.compile(r'(?im)^[ \t#>*_]{0,8}(expected|actual)\b'),
           'reproduction steps': re.compile(r'(?i)\b(steps to reproduce|to reproduce|reproduction)\b'),
           'code block': re.compile(r'```')}
MAINTAINER_ASSOCIATIONS = {'OWNER', 'MEMBER', 'COLLABORATOR'}
# One unbounded class: each match is a complete run, never cut short. module_hint validates the segments.
# Identifier characters outside \w (combining marks, ℘, ·) are not matched; _adjoins refuses such names whole.
MODULE_TOKEN = re.compile(r'[\w.:]+')
MODULE_SEPARATOR = re.compile(r'::|\.')
MAX_SEGMENTS = 16
MAX_TOKEN = 300
RUST_PREFIXES = {'crate', 'self', 'super'}
PACKAGE_FILES = {'__init__.py', 'mod.rs'}
AMBIGUOUS = object()
MIN_EXTERNAL = 5


@functools.lru_cache(maxsize=1)
def module_index(paths):
    """Module suffix -> its single file, or AMBIGUOUS. One build per tree.

    Only queryable suffixes are stored: 2 to MAX_SEGMENTS segments and at most MAX_TOKEN characters,
    so memory stays linear in the tree size however deep its paths are.
    """
    index = {}
    for path in paths:
        parts = path.split('/')
        name = parts[-1]
        if '.' not in name.lstrip('.'):
            continue
        stem = name.rsplit('.', 1)[0]
        keys = [parts[:-1] + [stem]]
        if name in PACKAGE_FILES or stem == 'index':
            keys.append(parts[:-1])
        for key in keys:
            for start in range(max(0, len(key) - MAX_SEGMENTS), len(key) - 1):
                suffix = '/'.join(key[start:])
                if len(suffix) <= MAX_TOKEN:
                    index[suffix] = path if index.get(suffix, path) == path else AMBIGUOUS
    return index


def _adjoins(char):
    """A neighbour that would extend an identifier (including marks \\w misses) or place the token in a path."""
    return bool(char) and (char in './\\:-' or ('a' + char).isidentifier())


def module_hint(token, index):
    segments = MODULE_SEPARATOR.split(token)
    if not all(segment.isidentifier() for segment in segments):
        return None
    if '::' in token and segments[0] in RUST_PREFIXES:
        segments = segments[1:]
    if len(segments) > MAX_SEGMENTS or len('/'.join(segments)) > MAX_TOKEN:
        # Refuse the whole name: only then is every prefix within the index bounds, so a longer (or ambiguous)
        # module can never be skipped in favour of a shorter, different one.
        return None
    # The longest prefix naming any module decides; trailing segments are members. Never fall back past ambiguity.
    for end in range(len(segments), 1, -1):
        match = index.get('/'.join(segments[:end]))
        if match is not None:
            return None if match is AMBIGUOUS else match
    return None


def location_hints(text, paths):
    if paths is None:
        return {'value': 'unknown', 'hints': [],
                'explanation': 'Repository tree was not read completely; locations are unverified'}
    known = set(paths)
    basenames = {}
    for path in paths:
        basenames.setdefault(path.rsplit('/', 1)[-1], []).append(path)
    hints = []
    for token in dict.fromkeys(TOKEN.findall(text[:SCAN_LIMIT])):
        token = token.rstrip('.')
        if '/' in token:
            # Stack frames carry absolute prefixes; try each repository-relative suffix.
            parts = token.split('/')
            match = next(('/'.join(parts[i:]) for i in range(len(parts)) if '/'.join(parts[i:]) in known), None)
        else:
            candidates = basenames.get(token, []) if '.' in token else []
            match = candidates[0] if len(candidates) == 1 else None
        if match and match not in hints:
            hints.append(match)
            if len(hints) == MAX_HINTS:
                break
    if len(hints) < MAX_HINTS:
        index = None
        for found in MODULE_TOKEN.finditer(text, 0, SCAN_LIMIT):
            # Refuse partial tokens: inside a longer identifier or path, or cut by the scan limit.
            if _adjoins(text[found.start() - 1:found.start()]) or _adjoins(text[found.end():found.end() + 1]):
                continue
            token = found.group().rstrip('.:')
            if '.' not in token and '::' not in token:
                continue
            index = index if index is not None else module_index(tuple(paths))
            match = module_hint(token, index)
            if match and match not in hints:
                hints.append(match)
                if len(hints) == MAX_HINTS:
                    break
    return {'value': 'found' if hints else 'none', 'hints': [core.safe_text(h, 500) for h in hints],
            'explanation': (f'{len(hints)} path(s) or module name(s) in the issue match the snapshot tree' if hints else
                            'No path, unique file name or module name in the issue matches the snapshot tree')}


def acceptance_clarity(text):
    found = [name for name, pattern in MARKERS.items() if pattern.search(text[:SCAN_LIMIT])]
    value = 'high' if len(found) >= 2 else 'medium' if found else 'low'
    return {'value': value, 'markers': found,
            'explanation': 'Structure found: ' + ', '.join(found) if found else 'No checklist, expected/actual, reproduction steps or code block'}


def _days(value, now):
    try:
        return max(0, (now - dt.datetime.fromisoformat(value.replace('Z', '+00:00'))).days)
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None


def _count(value):
    return value if type(value) is int and value >= 0 else None


def activity(issue, now):
    reactions = issue.get('reactions')
    value = {'age_days': _days(issue.get('created_at'), now), 'updated_days': _days(issue.get('updated_at'), now),
             'comments': _count(issue.get('comments')),
             'reactions': _count(reactions.get('total_count')) if isinstance(reactions, dict) else None}
    return {'value': value, 'explanation': 'From the issue list payload; missing or malformed fields are null'}


def maintainer_signal(issue):
    association = issue.get('author_association')
    # Type first: remote lists/objects are unhashable and must degrade to unknown, not crash.
    value = ('unknown' if not isinstance(association, str) else
             'maintainer' if association in MAINTAINER_ASSOCIATIONS else 'other')
    return {'value': value, 'explanation': 'Issue author association is ' +
            (core.safe_text(association, 40) if isinstance(association, str) else 'not reported')}


def _timestamp(value):
    try:
        parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (AttributeError, TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else None


def responsiveness(repository, client):
    """Opt-in repository-level report from one page of recently closed PRs. A sample, never full history."""
    endpoint = f'repos/{repository}/pulls?state=closed&sort=updated&direction=desc&per_page=100'
    report = {'repository': repository, 'endpoint': endpoint, 'complete': False, 'value': 'unknown',
              'sample_size': None, 'external_closed': None, 'external_merged': None, 'external_merge_rate': None,
              'median_days_to_close': None, 'minimum_external': MIN_EXTERNAL, 'errors': []}
    if repository is None:
        report.update(endpoint=None, errors=['Discovery did not complete a source snapshot; closed PRs were not read'],
                      explanation='Responsiveness is unknown because discovery did not resolve the source repository')
        return report
    try:
        page = client.request(endpoint)
        if not isinstance(page, list) or len(page) > 100:
            raise core.ProtocolError('api_shape', 'Expected one bounded closed-PR list page')
        days, merged, numbers = [], 0, set()
        for pr in page:
            if not isinstance(pr, dict) or not isinstance(pr.get('user'), dict):
                raise core.ProtocolError('api_shape', 'Closed PR entry lacks a user object')
            # Like paginate, a repeated identity means the page is not a trustworthy sample.
            if type(pr.get('number')) is not int or pr['number'] < 1 or pr['number'] in numbers:
                raise core.ProtocolError('api_shape', 'Closed PR number is missing, malformed or repeated')
            numbers.add(pr['number'])
            kind, association = pr['user'].get('type'), pr.get('author_association')
            created, closed = _timestamp(pr.get('created_at')), _timestamp(pr.get('closed_at'))
            if not isinstance(kind, str) or not isinstance(association, str):
                raise core.ProtocolError('api_shape', 'Closed PR author type or association is malformed')
            if created is None or closed is None or closed < created:
                raise core.ProtocolError('api_shape', 'Closed PR timestamps are missing or inconsistent')
            if 'merged_at' not in pr:
                raise core.ProtocolError('api_shape', 'Closed PR merge state is missing')
            merged_at = None if pr['merged_at'] is None else _timestamp(pr['merged_at'])
            if pr['merged_at'] is not None and (merged_at is None or not created <= merged_at <= closed):
                raise core.ProtocolError('api_shape', 'Closed PR merge timestamp is malformed or outside its lifetime')
            if kind == 'Bot' or association in MAINTAINER_ASSOCIATIONS:
                continue
            days.append((closed - created).total_seconds() / 86400)
            merged += merged_at is not None
    except core.ProtocolError as exc:
        report['errors'] = [str(exc)]
        report['explanation'] = 'Closed pull requests could not be read completely; responsiveness is unknown'
        return report
    report.update(complete=True, sample_size=len(page), external_closed=len(days), external_merged=merged)
    if len(days) < MIN_EXTERNAL:
        report.update(value='insufficient', explanation=(
            f'{len(days)} external PR(s) among the {len(page)} most recently updated closed PRs; '
            f'at least {MIN_EXTERNAL} are needed for a rate'))
        return report
    report.update(value='measured', external_merge_rate=round(merged / len(days), 3),
                  median_days_to_close=round(statistics.median(days), 1), explanation=(
                      f'{merged} of {len(days)} external PRs among the {len(page)} most recently updated closed PRs '
                      'were merged. External excludes OWNER, MEMBER, COLLABORATOR and bot authors. One-page sample, '
                      'not full history; a heuristic, never approval'))
    return report


def issue_signals(issue, paths, now):
    text = issue['title'] + '\n' + issue['body']
    signals = {'code_location': location_hints(text, paths), 'acceptance_clarity': acceptance_clarity(issue['body']),
               'activity': activity(issue, now), 'maintainer': maintainer_signal(issue)}
    signals['score'] = ((signals['code_location']['value'] == 'found') +
                        {'high': 2, 'medium': 1, 'low': 0}[signals['acceptance_clarity']['value']] +
                        (signals['maintainer']['value'] == 'maintainer'))
    return signals
