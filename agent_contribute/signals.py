"""Opt-in deterministic ranking signals from data discover already read. Heuristics, never approval."""
import datetime as dt
import re

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
    return {'value': 'found' if hints else 'none', 'hints': [core.safe_text(h, 500) for h in hints],
            'explanation': (f'{len(hints)} path(s) named in the issue exist in the snapshot tree' if hints else
                            'No path or unique file name in the issue matches the snapshot tree')}


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


def issue_signals(issue, paths, now):
    text = issue['title'] + '\n' + issue['body']
    signals = {'code_location': location_hints(text, paths), 'acceptance_clarity': acceptance_clarity(issue['body']),
               'activity': activity(issue, now), 'maintainer': maintainer_signal(issue)}
    signals['score'] = ((signals['code_location']['value'] == 'found') +
                        {'high': 2, 'medium': 1, 'low': 0}[signals['acceptance_clarity']['value']] +
                        (signals['maintainer']['value'] == 'maintainer'))
    return signals
