"""Repository policy report: a bounded inventory of policy-relevant files and high-recall hints. Never a verdict.

It lists what was read at pinned commits, what was referenced or found but not assessed, fixed blind spots
and attention hints. It decides nothing: the installed workflow requires the agent and the human to read
the sources and record a disposition. The instruction allow-list and instructions_sha256 are untouched.
"""
import base64
import binascii
import bisect
import hashlib
import html
import json
import posixpath
import re
import unicodedata
from urllib.parse import quote, unquote, urlsplit

from . import core

MAX_REQUESTS = 25  # source metadata + tree + 12 files, owner metadata + commit + tree + 8 files
MAX_SOURCE_FILES = 12
MAX_OWNER_FILES = 8
MAX_FILE_BYTES = 200000
MAX_SCANNED_BYTES = 1000000
MAX_HINTS = 100
MAX_UNASSESSED = 50
EXCERPT_CHARS = 300
IDENTIFIER_CHARS = 500
MAX_REPORT_BYTES = 256 * 1024
WINDOW = 12
SCANNED_FORMATS = {'', '.md', '.markdown', '.rst', '.txt'}
KIND_ORDER = ('ai_policy', 'agent_instructions', 'contributing', 'pr_template', 'community', 'readme')
HINT_ORDER = ('possible_agent_restriction', 'possible_ai_restriction', 'possible_pr_restriction', 'ai_mention')
NEVER_INSPECTED = ['GitHub wiki', 'websites outside the GitHub REST API', 'images and PDFs',
                   'issue, pull request and discussion comments',
                   "files in repositories other than the source and its owner's .github repository",
                   'non-Latin-script text (see per-source notes)']
OBLIGATION = ('This report is not a verdict and never shows that contributions are permitted. Read every scanned '
              'source in full, every hint in context and every unassessed reference before ranking or preparing '
              'work. Record each relevant source with its revision or content digest. A policy-relevant source you '
              'cannot read, or unknown contributor eligibility under a maintainers-only rule, is unresolved: '
              'unresolved policy blocks upstream preparation, implementation and publication. This review remains '
              'a host obligation even when every count is zero.')

AI_TERMS = {'ai', 'llm', 'llms', 'chatgpt', 'copilot', 'claude', 'cursor', 'codex', 'gemini', 'vibe', 'genai'}
AGENT_TERMS = {'agent', 'agents', 'agentic', 'autonomous', 'autonomously', 'bot', 'bots', 'automated', 'automation'}
PR_TERMS = {'pr', 'prs', 'patch', 'patches', 'contribution', 'contributions', 'contribute'}
RESTRICT_TERMS = {'not', 'no', 'never', 'nor', 'only', 'limited', 'restricted', 'closed', 'close', 'closes',
                  'reject', 'rejected', 'rejects', 'refuse', 'refused', 'refuses', 'forbid', 'forbidden', 'forbids',
                  'prohibit', 'prohibited', 'prohibits', 'ban', 'banned', 'bans', 'disallow', 'disallowed',
                  'invitation', 'invite', 'invited', 'maintainers', 'members', 'instead', 'must'}
PHRASES = {'artificial': [(('artificial', 'intelligence'), 'ai')],
           'large': [(('large', 'language', 'model'), 'ai'), (('large', 'language', 'models'), 'ai')],
           'machine': [(('machine', 'generated'), 'ai')],
           'pull': [(('pull', 'request'), 'pr'), (('pull', 'requests'), 'pr')],
           'merge': [(('merge', 'request'), 'pr'), (('merge', 'requests'), 'pr')]}

# Linear patterns only: bounded character classes, no quantified groups (see tests).
TOKEN = re.compile(r'[^\W_]+')
TAG = re.compile(r'</?[A-Za-z][^<>]{0,200}>')
NOT_CONTRACTION = re.compile(r"(?i)n['’]t\b")
MD_LINK = re.compile(r'\[([^\[\]]{0,2000})\]\(([^()\s]{1,2000})\)')
REF_LINK = re.compile(r'(?m)^ {0,3}\[([^\[\]\n]{1,2000})\]: {0,3}(\S{1,2000})')
RST_LINK = re.compile(r'`([^`<>]{1,2000}) <([^<>\s]{1,2000})>`_')
BARE_URL = re.compile(r'https?://[^\s<>()\[\]"\'`]{1,2000}')
POLICY_LINK = re.compile(r'(?i)contribut|polic|guideline|pull[-_ ]?request|\bpr\b|\bai\b|llm|agent|conduct|governance')
UNDERLINE = re.compile(r'[=\-~^*+#]{3,}')


def kind_of(path):
    """Scan kind for a policy-relevant path, or None. Not a GitHub fallback identity."""
    lowered = path.casefold()
    parts = lowered.split('/')
    name = parts[-1]
    stem = name.rsplit('.', 1)[0] if '.' in name[1:] else name
    if name == '.cursorrules' or lowered.startswith('.cursor/rules/'):
        return 'agent_instructions'
    if stem in ('agents', 'claude', 'copilot-instructions'):
        return 'agent_instructions'
    if (stem in ('ai', 'ai_policy', 'ai-policy', 'ai_usage', 'ai-usage', 'ai_usage_policy') or
            stem.startswith('llm') and 'polic' in stem or stem.startswith(('ai_policy', 'ai-policy'))):
        return 'ai_policy'
    if stem in ('contributing', 'contribute') or any(p in ('contributing', 'contributors', 'contribute', 'policy',
                                                             'policies') for p in parts[:-1]):
        return 'contributing'
    if stem == 'pull_request_template' or lowered.startswith('.github/pull_request_template/'):
        return 'pr_template'
    if stem in ('code_of_conduct', 'security', 'support', 'governance'):
        return 'community'
    if len(parts) == 1 and stem == 'readme':
        return 'readme'
    return None


def _format(path):
    name = path.rsplit('/', 1)[-1]
    return '.' + name.rsplit('.', 1)[1].casefold() if '.' in name[1:] else ''


def normalize(text):
    text = core.safe_text(html.unescape(core.safe_text(text)))
    text = TAG.sub(' ', text)  # a tag starts with a letter, so HTML comment bodies stay and are scanned
    return NOT_CONTRACTION.sub(' not', unicodedata.normalize('NFKC', text))


def _non_latin(text):
    if text.isascii():
        return False
    return any(c.isalpha() and not (ord(c) < 0x250 or 0x1E00 <= ord(c) <= 0x1EFF or 0x2C60 <= ord(c) <= 0x2C7F or
                                    0xA720 <= ord(c) <= 0xA7FF) for c in text)


def _groups(tokens):
    found = {'ai': [], 'agent': [], 'pr': [], 'restrict': []}
    for index, (_, token) in enumerate(tokens):
        if token in AI_TERMS or token.startswith('gpt'):
            found['ai'].append(index)
        if token in AGENT_TERMS:
            found['agent'].append(index)
        if token in PR_TERMS:
            found['pr'].append(index)
        if token in RESTRICT_TERMS:
            found['restrict'].append(index)
        for words, group in PHRASES.get(token, ()):
            if tuple(t for _, t in tokens[index:index + len(words)]) == words:
                found[group].append(index)
    return found


def _near(anchors, restrict):
    for anchor in anchors:
        at = bisect.bisect_left(restrict, anchor - WINDOW)
        if at < len(restrict) and restrict[at] <= anchor + WINDOW:
            return anchor
    return None


def _excerpt(text, offset):
    start = max(0, offset - 100)
    if start and not text[start - 1].isspace():  # begin at the next word, never mid-word
        space = text.find(' ', start, offset)
        start = offset if space < 0 else space + 1
    return ' '.join(text[start:start + EXCERPT_CHARS * 4].split())[:EXCERPT_CHARS]


def _paragraphs(text):
    """(first line, heading, text) blocks split on blank lines and Markdown/RST headings; headings are blocks too."""
    lines = text.split('\n')
    blocks, current, start, heading = [], [], 0, ''
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        underlined = (stripped and index + 1 < len(lines) and UNDERLINE.fullmatch(lines[index + 1].strip()) and
                      not UNDERLINE.fullmatch(stripped))
        if stripped.startswith('#') or underlined:
            if current:
                blocks.append((start, heading, '\n'.join(current)))
                current = []
            heading = ' '.join(stripped.lstrip('#').split())[:120]
            blocks.append((index + 1, heading, stripped))
            index += 2 if underlined else 1
            continue
        if not stripped:
            if current:
                blocks.append((start, heading, '\n'.join(current)))
                current = []
        else:
            if not current:
                start = index + 1
            current.append(line)
        index += 1
    if current:
        blocks.append((start, heading, '\n'.join(current)))
    return blocks


def _links(text):
    starts = [0] + [m.end() for m in re.finditer('\n', text)]
    seen, links = set(), []
    for pattern, text_group in ((MD_LINK, 1), (REF_LINK, 1), (RST_LINK, 1), (BARE_URL, None)):
        for match in pattern.finditer(text):
            url = match.group(0).rstrip('.,;:!?') if text_group is None else match.group(2)
            label = '' if text_group is None else ' '.join(match.group(text_group).split())
            if url in seen or not POLICY_LINK.search(url[:IDENTIFIER_CHARS] + ' ' + label[:EXCERPT_CHARS]):
                continue
            seen.add(url)
            links.append({'url': url, 'link_text': label[:EXCERPT_CHARS] or None,
                          'line': bisect.bisect_right(starts, match.start())})
    return links


def scan(text, path):
    """Hints, policy-like links and the count of non-Latin paragraphs for one source text."""
    text = core.safe_text(text, MAX_FILE_BYTES * 5)
    hints, non_latin = [], 0
    for line, heading, block in _paragraphs(text):
        normalized = normalize(block)
        if _non_latin(normalized):
            non_latin += 1
        tokens = [(m.start(), m.group().casefold()) for m in TOKEN.finditer(normalized)]
        found = _groups(tokens)
        candidates = [('possible_agent_restriction', _near(found['agent'], found['restrict'])),
                      ('possible_ai_restriction', _near(found['ai'], found['restrict'])),
                      ('possible_pr_restriction', _near(found['pr'], found['restrict'])),
                      ('ai_mention', min(found['ai'] + found['agent']) if found['ai'] or found['agent'] else None)]
        for kind, anchor in candidates:
            if anchor is not None:
                hints.append({'kind': kind, 'line': line, 'heading': core.safe_text(heading, 120),
                              'untrusted_excerpt': _excerpt(normalized, tokens[anchor][0])})
    return {'hints': hints, 'links': _links(text), 'non_latin_paragraphs': non_latin}


class _Report:
    def __init__(self, client):
        self.client, self.requests, self.skipped = client, 0, 0
        self.sources, self.texts, self.unassessed, self.limits = [], [], [], {}
        self.seen, self.keys = set(), []  # every identity noted; identities of retained entries (aligned)
        self.scanned_bytes = 0

    def get(self, endpoint):
        if self.requests >= MAX_REQUESTS:
            self.skipped += 1
            raise _Limit()
        self.requests += 1
        return self.client.request(endpoint)

    def note(self, what, reason, origin=None, line=None, link_text=None, key=None):
        """key is the full identity (repository and path, or URL); the displayed what may be shortened."""
        what = core.safe_text(str(what), len(str(what)))
        key = key or what
        if key in self.seen:
            return
        self.seen.add(key)
        if len(self.unassessed) >= MAX_UNASSESSED:  # count, do not retain: bounded memory and linear time (RP-16)
            self.limit('unassessed entries')
            return
        self.keys.append(key)
        self.unassessed.append({'what': what[:IDENTIFIER_CHARS], 'reason': reason, 'from': origin, 'line': line,
                                'link_text': core.safe_text(link_text, EXCERPT_CHARS) if link_text else None,
                                'what_truncated': len(what) > IDENTIFIER_CHARS})

    def limit(self, name, count=1):
        self.limits[name] = self.limits.get(name, 0) + count

    def tree(self, repository, commit):
        data = core.require(self.get(f'repos/{repository}/git/trees/{commit}?recursive=1'), dict, 'tree')
        entries = core.require(data.get('tree'), list, 'tree entries')
        if data.get('truncated') is not False:
            raise core.ProtocolError('partial_tree', 'Repository tree is truncated')
        blobs = {}
        for entry in entries:
            core.require(entry, dict, 'tree entry')
            if entry.get('type') == 'blob':
                blobs[core.require(entry.get('path'), str, 'tree path')] = entry.get('sha')
        return blobs

    def add(self, origin, repository, path, commit, digest, kind, text):
        if self.scanned_bytes + len(text) > MAX_SCANNED_BYTES:
            self.limit('scanned bytes')
            return
        self.scanned_bytes += len(text)
        result = scan(text, path)
        notes = ([f'paragraphs with non-Latin script not assessed: {result["non_latin_paragraphs"]}']
                 if result['non_latin_paragraphs'] else [])
        self.sources.append({'origin': origin, 'repository': repository, 'path': core.safe_text(path, IDENTIFIER_CHARS),
                             'commit': commit, 'sha256': digest, 'kind': kind or 'instruction', 'notes': notes})
        self.texts.append((path, result))

    def fetch(self, origin, repository, commit, path, blob, kind):
        shown = core.safe_text(path, IDENTIFIER_CHARS)
        try:
            value = core.require(self.get(f'repos/{repository}/contents/{quote(path, safe="/")}?ref={commit}'),
                                 dict, 'file')
            if value.get('encoding') != 'base64':
                raise core.ProtocolError('file_encoding', 'not base64')
            data = base64.b64decode(''.join(core.require(value.get('content'), str, 'content').split()), validate=True)
        except _Limit:
            self.note(shown if origin == 'repository' else f'{repository}:{shown}', 'not read: request limit')
            return
        except (core.ProtocolError, ValueError, binascii.Error):
            self.note(shown if origin == 'repository' else f'{repository}:{shown}', 'read failed')
            return
        label = shown if origin == 'repository' else f'{repository}:{shown}'
        if len(data) > MAX_FILE_BYTES:
            self.note(label, 'exceeds 200 kB')
        elif not _pinned(blob, value.get('sha'), data):
            self.note(label, 'content did not match the pinned tree entry')
        else:
            try:
                text = data.decode('utf-8')
            except UnicodeError:
                self.note(label, 'not UTF-8 text')
                return
            self.add(origin, repository, path, commit, hashlib.sha256(data).hexdigest(), kind, text)

    def read_candidates(self, origin, repository, commit, blobs, skip, cap, limit_name, allowed=lambda path: True):
        found = []
        for path, blob in blobs.items():
            kind = kind_of(core.safe_text(path, IDENTIFIER_CHARS))
            if kind is None or path in skip or not allowed(path) or origin != 'repository' and kind == 'readme':
                continue
            if _format(path) not in SCANNED_FORMATS:
                self.note(core.safe_text(path, IDENTIFIER_CHARS) if origin == 'repository' else
                          f'{repository}:{core.safe_text(path, IDENTIFIER_CHARS)}', 'unsupported format')
                continue
            found.append((KIND_ORDER.index(kind), path, blob, kind))
        found.sort()
        for _, path, blob, kind in found[:cap]:
            self.fetch(origin, repository, commit, path, blob, kind)
        if len(found) > cap:
            self.limit(limit_name, len(found) - cap)


def _pinned(blob, reported, data):
    """The returned bytes are the tree's blob: both SHA fields agree and the Git blob SHA-1 of the bytes matches."""
    if not isinstance(blob, str) or not re.fullmatch('[0-9a-f]{40}', blob) or reported != blob:
        return False
    return hashlib.sha1(b'blob %d\x00' % len(data) + data).hexdigest() == blob


class _Limit(Exception):
    pass


def _owner(state, repository):
    owner = repository.split('/')[0]
    name = f'{owner}/.github'
    if repository.casefold() == name.casefold():
        return None
    try:
        meta = core.require(state.get(f'repos/{name}'), dict, 'owner .github metadata')
        branch = core.require(meta.get('default_branch'), str, 'owner default branch')
        commit = core.require(core.require(state.get(f'repos/{name}/commits/{quote(branch, safe="")}'), dict,
                                           'owner commit').get('sha'), str, 'owner commit sha')
        if not re.fullmatch('[0-9a-f]{40}', commit):
            raise core.ProtocolError('api_shape', 'Invalid owner commit')
        blobs = state.tree(name, commit)
    except _Limit:
        state.note(name, 'not read: request limit')
        return None
    except core.ProtocolError:
        state.note(name, 'owner .github repository not found or inaccessible')
        return None
    located = lambda path: '/' not in path or path.split('/')[0] in ('.github', 'docs')
    state.read_candidates('owner-github', name, commit, blobs, set(), MAX_OWNER_FILES, 'owner policy files', located)
    return name, commit, branch


def _assessed(url, base_repository, base_path, refs, scanned):
    """True when a link points at a file this report scanned at the same revision."""
    target = url.split('#', 1)[0].split('?', 1)[0]
    if not target:
        return True  # an in-page anchor
    parts = urlsplit(target)
    if parts.scheme or parts.netloc:
        if parts.netloc.casefold() != 'github.com':
            return False
        segments = unquote(parts.path).strip('/').split('/', 3)
        if len(segments) < 4 or segments[2] != 'blob':
            return False
        repository, rest = '/'.join(segments[:2]), segments[3]
        for ref in refs.get(repository.casefold(), ()):
            if rest.startswith(ref + '/') and (repository.casefold(), rest[len(ref) + 1:]) in scanned:
                return True
        return False
    if target.startswith(('mailto:', 'tel:')):
        return False
    path = unquote(target)
    path = posixpath.normpath(path.lstrip('/') if path.startswith('/') else posixpath.join(posixpath.dirname(base_path), path))
    return (base_repository.casefold(), path) in scanned


def _relative_what(url, base_path):
    """(target, relative): an absolute URL as is, or a link path resolved inside the linking repository."""
    if urlsplit(url).scheme or url.startswith('//'):
        return url, False
    target = unquote(url.split('#', 1)[0].split('?', 1)[0])
    return posixpath.normpath(target.lstrip('/') if target.startswith('/') else
                              posixpath.join(posixpath.dirname(base_path), target)), True


def report(repository, commit, instructions, client, *, default_branch=None):
    """Read-only policy report for the issue source repository at its observed commit; never raises on reads."""
    state = _Report(client)
    if default_branch is None:
        try:
            default_branch = core.require(core.require(state.get(f'repos/{repository}'), dict, 'metadata')
                                          .get('default_branch'), str, 'default branch')
        except (core.ProtocolError, _Limit):
            default_branch = None
    loaded = set()
    for item in instructions:
        loaded.add(item['path'])
        state.add('repository', repository, item['path'], commit, item['sha256'], kind_of(item['path']), item['untrusted_text'])
    try:
        blobs = state.tree(repository, commit)
    except (core.ProtocolError, _Limit):
        state.note(repository, 'repository tree not read')
        blobs = {}
    state.read_candidates('repository', repository, commit, blobs, loaded, MAX_SOURCE_FILES, 'policy files')
    owner = _owner(state, repository)
    refs = {repository.casefold(): [r for r in (commit, default_branch) if r]}
    if owner:
        refs[owner[0].casefold()] = [owner[1], owner[2]]
    scanned = {(s['repository'].casefold(), s['path']) for s in state.sources}
    hints = []
    for index, (source, (path, result)) in enumerate(zip(state.sources, state.texts)):
        hints += [dict(hint, source=index) for hint in result['hints']]
        for link in result['links']:
            origin = f'{source["repository"]}:{source["path"]}'
            try:
                if not _assessed(link['url'], source['repository'], path, refs, scanned):
                    target, relative = _relative_what(link['url'], path)
                    shown = target if not relative or source['repository'] == repository else f'{source["repository"]}:{target}'
                    state.note(shown, 'referenced, not assessed', origin, link['line'], link['link_text'],
                               key=(source['repository'].casefold(), target) if relative else link['url'])
            except ValueError:  # e.g. 'https://[' or a netloc that NFKC-normalizes to a delimiter
                state.note(link['url'], 'malformed reference, not assessed', origin, link['line'], link['link_text'])
    if state.skipped:
        state.limit('requests', state.skipped)
    hints.sort(key=lambda hint: (HINT_ORDER.index(hint['kind']), hint['source'], hint['line']))
    if len(hints) > MAX_HINTS:
        state.limit('hints', len(hints) - MAX_HINTS)
    result = {'report': 'policy-report/1', 'review_obligation': OBLIGATION, 'sources_scanned': state.sources,
              'unassessed': state.unassessed, 'limits_reached': [],
              'never_inspected': list(NEVER_INSPECTED),
              'hints': [dict(hint, id=f'H{n}') for n, hint in enumerate(hints[:MAX_HINTS], 1)],
              'reads': {'requests': state.requests, 'limit': MAX_REQUESTS}}
    while True:
        result['limits_reached'] = [{'limit': name, 'not_reported': count} for name, count in sorted(state.limits.items())]
        result['inventory_sha256'] = core.canonical_hash({
            'sources': sorted([{k: s[k] for k in ('origin', 'repository', 'path', 'sha256')} for s in result['sources_scanned']],
                              key=lambda s: (s['origin'], s['repository'], s['path'])),
            # Full identities, not the shortened display text (RP-20); state.keys is aligned with retained entries.
            'unassessed': sorted(json.dumps(key) for key in state.keys[:len(result['unassessed'])]),
            'limits_reached': result['limits_reached']})
        if len(json.dumps(result, ensure_ascii=True).encode()) <= MAX_REPORT_BYTES:
            return result
        if result['hints']:
            result['hints'].pop()
        elif result['unassessed']:
            result['unassessed'].pop()
        else:
            return result
        state.limit('report size')


def for_inspected(inspected, client):
    """The report for an inspect result's issue source at its observed commit."""
    source = inspected['source']
    return report(source['repository'], source['commit'], inspected['instructions'], client,
                  default_branch=source['default_branch'])
