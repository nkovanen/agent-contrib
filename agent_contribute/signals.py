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


def named_paths_missing(text, known):
    """Repository-relative file paths the issue names that the snapshot tree lacks; a staleness cue, never a gate."""
    scan, missing = text[:SCAN_LIMIT], []
    for found in TOKEN.finditer(scan):
        token, start = found.group().rstrip('.'), found.start()
        if len(found.group()) == 300:
            continue  # possibly cut by the token bound
        before = scan[max(0, start - 3):start]
        outer = before[:-2][-1:] if before.endswith('./') else before[:-1][-1:]
        if before.endswith('.') or before.endswith('./'):
            if outer and (outer.isalnum() or outer in '_./-:'):
                continue  # ../traversal, a domain or another token's tail
            token = '.' + token if before.endswith('.') else token
        elif before[-1:] and (before[-1:] in '/-:' or before[-1:].isalnum()):
            continue  # absolute path, URL or part of a longer word
        parts = token.split('/')
        if (len(parts) < 2 or '..' in parts or '' in parts or '.' in parts[0].lstrip('.') or
                not re.fullmatch(r'[^.].*\.[A-Za-z0-9]{1,10}', parts[-1])):
            continue
        if token not in known and token not in missing:  # exact path; suffix matching is for hints only
            missing.append(token)
            if len(missing) == MAX_HINTS:
                break
    return [core.safe_text(path, 500) for path in missing]


def location_hints(text, paths):
    if paths is None:
        return {'value': 'unknown', 'hints': [], 'named_paths_missing': [],
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
            'named_paths_missing': named_paths_missing(text, known),
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


# Report-only ranking demotions (E-08, E-09). Label phrases match whole words of the lower-cased label name, with
# punctuation and separators read as spaces, so 'Status: On-Hold' matches 'on hold' but 'blockedness' matches nothing.
# A phrase right after a negation ('not blocked', 'non breaking') does not match. The major-version group needs an
# explicit bucket: the label, or its last ':' or '/' part, is exactly a bucket name (R8-01: 'v5-compat' is not one).
DEMOTING_LABELS = (
    ('on hold or deferred', ('icebox', 'on hold', 'blocked', 'deferred', 'postponed', 'frozen')),
    ('needs a decision or design discussion', ('needs decision', 'needs design', 'needs discussion', 'discussion',
                                               'question', 'rfc', 'proposal')),
    ('not planned or not this project', ('not planned', 'out of scope', 'upstream', 'third party', 'wont do')),
    ('major-version or breaking-change bucket', ()))
NEGATIONS = ('non', 'not', 'no', 'un')
MAJOR_BUCKET = re.compile(r'breaking(?: changes?)?|v[0-9]{1,3}(?: x)?')
META_TITLE = re.compile(r'(?i)^\W{0,3}(?:meta|wip|tracking|tracker|roadmap|rfc|umbrella|epic)\s{0,3}[]:)-]|'
                        r'\b(?:meta|tracking|umbrella) issue\b|\broadmap\b|\bfeatures? list\b')
DEMOTION = 2


def _words(name):
    return ' ' + ' '.join(re.sub(r'[^a-z0-9]+', ' ', name.casefold().replace("'", '')).split()) + ' '


def demotions(issue):
    reasons, meta = [], bool(META_TITLE.search(issue['title'][:300]))
    labels = [label['name'] for label in issue.get('labels') or [] if isinstance(label, dict) and isinstance(label.get('name'), str)]
    for group, phrases in DEMOTING_LABELS:
        for name in labels:
            words = _words(name)
            bucket = _words(re.split(r'[:/]', name)[-1])
            if any(' ' + phrase + ' ' in words and not any(f' {negation} {phrase} ' in words for negation in NEGATIONS)
                   for phrase in phrases) or (not phrases and MAJOR_BUCKET.fullmatch(bucket.strip())):
                reasons.append(f'label "{core.safe_text(name, 100)}": {group}')
                break
    if meta:
        reasons.append('title: meta, tracking, roadmap or work-in-progress item; maintainer authorship not counted')
    return {'value': 'demoted' if reasons else 'none', 'reasons': reasons}, meta, [core.safe_text(n, 100) for n in labels[:100]]


def issue_signals(issue, paths, now):
    text = issue['title'] + '\n' + issue['body']
    demotion, meta, labels = demotions(issue)
    signals = {'code_location': location_hints(text, paths), 'acceptance_clarity': acceptance_clarity(issue['body']),
               'activity': activity(issue, now), 'maintainer': maintainer_signal(issue), 'labels': labels,
               'demotion': demotion}
    score = ((signals['code_location']['value'] == 'found') +
             {'high': 2, 'medium': 1, 'low': 0}[signals['acceptance_clarity']['value']] +
             (signals['maintainer']['value'] == 'maintainer' and not meta))
    signals['score'] = max(0, score - DEMOTION * len(demotion['reasons']))
    return signals


# discover --signals --check-top N: the existing ownership readers, bounded, for the top N candidates only.
CHECK_TOP_MAX = 5
CHECK_PAGES = 1
CHECK_PR_DETAILS = 4
CHECK_READ_CAP = 30
CHECK_TOP_NOTICE = ('Report only. Only the top N candidates were read (first timeline and comment page, at most '
                    f'{CHECK_PR_DETAILS} cross-referenced PR details each, one GitHub GET per read without retries, '
                    f'{CHECK_READ_CAP} in all); a demoted one moves below every other '
                    'candidate that is not excluded or overlapping. An '
                    'incomplete or clean check is unknown, never proof that an issue is free or unfixed.')


# A ranking demotion needs a stricter claim than the report-only ownership patterns (review R8-03): first person,
# about this issue ('this' or 'it'), by a non-maintainer, outside code, quotes and blockquotes.
RANKING_CLAIMS = re.compile(r"(?i)\bI(?:'m| am)\s{1,3}(?:currently\s{1,3}|now\s{1,3})?working on (?:this|it)\b(?!\s{0,3}#)|"
                            r"\bI(?:'ll| will)\s{1,3}take (?:this|it)\b|\bcan I\s{1,3}(?:work on|take|pick up) (?:this|it)\b|"
                            r"(?m:^[ \t]{0,8}/assign\b)|\bassign (?:this |it )?(?:to )?me\b")
QUOTED = re.compile(r'(?s)```.*?```|~~~.*?~~~|`[^`\n]*`|(?m:^[ \t]{0,3}>.*$)|"[^"\n]*"|\u201c[^\u201d\n]*\u201d')


def ranking_claim(comment):
    from .ownership import STALE_DAYS
    age = comment['age_days']
    return (comment['author_association'] not in MAINTAINER_ASSOCIATIONS and age is not None and age <= STALE_DAYS and
            bool(RANKING_CLAIMS.search(QUOTED.sub(' ', comment['body'][:SCAN_LIMIT]))))


class _ReadCap:
    def __init__(self, client, cap):
        self.client, self.cap, self.reads = client, cap, 0

    def request(self, endpoint):
        if self.reads >= self.cap:
            raise core.ProtocolError('read_cap', f'Total --check-top read cap of {self.cap} reached')
        self.reads += 1
        # One transport attempt per counted read: GitHub.request would retry transient errors up to three times.
        return getattr(self.client, 'request_once', self.client.request)(endpoint)


def assignees(issue):
    return [core.safe_text(user['login'], 100) for user in (issue.get('assignees') or [])[:10]
            if isinstance(user, dict) and isinstance(user.get('login'), str)]


def check_top(result, client, n, now):
    """Check only the top n; demote on precise detectors only: a merged same-repository PR with an exact reference,
    a strict unquoted first-person claim by a non-maintainer no older than ownership.STALE_DAYS, or an assignee."""
    from .ownership import ownership_signals
    source, capped, head = result['repository'], _ReadCap(client, CHECK_READ_CAP), result['issues'][:n]
    for issue in head:
        before = capped.reads
        comments = []
        report = ownership_signals(source, issue['number'], capped, now, max_pages=CHECK_PAGES,
                                   max_pr_details=CHECK_PR_DETAILS, comments_out=comments)
        fixed = [pr['url'] for pr in report['resolution_signals']['possibly_already_fixed']
                 if pr['repository'].casefold() == source.casefold()]
        claims = [comment for comment in comments if ranking_claim(comment)]
        reasons = (['possibly already fixed by a merged same-repository PR: ' + ', '.join(fixed[:3])] if fixed else []) + (
            [f'claimed in a comment by {claims[0]["author"]} {claims[0]["age_days"]} days ago'] if claims else []) + (
            ['assigned to ' + ', '.join(issue['signals']['assignees'][:3])] if issue['signals']['assignees'] else [])
        issue['top_check'] = {'complete': report['complete'], 'errors': list(dict.fromkeys(report['errors'])),
                              'reads': capped.reads - before, 'demotions': reasons}
    # Known-bad below unknown, through the one discover sort key shared with --repo-dir local work: a demoted issue
    # moves below every other candidate but stays above excluded or overlapping issues; nothing below the top n is read.
    result['issues'].sort(key=lambda item: core.issue_order(item, True))
    result['ordering'] = core.KNOWN_BAD_ORDERING
    return {'requested': n, 'checked': len(head), 'reads': capped.reads, 'read_cap': CHECK_READ_CAP,
            'complete': all(item['top_check']['complete'] for item in head), 'notice': CHECK_TOP_NOTICE}
