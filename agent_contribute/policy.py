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

REVIEW_PREREQUISITE = core.POLICY_REVIEW_PREREQUISITE
MAX_REQUESTS = 25  # source metadata + tree + 12 files, owner metadata + commit + tree + 8 files
MAX_SOURCE_FILES = 12
MAX_OWNER_FILES = 8
MAX_FILE_BYTES = 200000
MAX_SCANNED_BYTES = 1000000
MAX_HINTS = 100
MAX_UNASSESSED = 50
MAX_OMITTED = 50
# Limits after which a policy candidate or reference may be unread or unlisted; hint limits hide no source.
HIDING_LIMITS = {'requests', 'policy files', 'owner policy files', 'scanned bytes', 'unassessed entries',
                 'omitted sources not listed', 'report size: unassessed entries', 'report size: omitted sources',
                 'report size: sources not listed', 'restriction hints', 'report size: restriction hints'}
STOP_HINTS = ('possible_agent_restriction', 'possible_ai_restriction', 'possible_pr_restriction')
POLICY_KINDS = ('ai_policy', 'agent_instructions', 'contributing', 'pr_template')
EXCERPT_CHARS = 300
IDENTIFIER_CHARS = 500
MAX_REPORT_BYTES = 256 * 1024
WINDOW = 12
SCANNED_FORMATS = {'', '.md', '.markdown', '.rst', '.txt'}
# Other document formats a policy may use; listed as unsupported. Code, data and image files are not candidates.
DOCUMENT_FORMATS = {'.adoc', '.asciidoc', '.pdf', '.html', '.htm', '.docx', '.odt', '.org', '.textile', '.rtf', '.mdx'}
KIND_ORDER = ('ai_policy', 'agent_instructions', 'contributing', 'pr_template', 'community', 'readme')
NEVER_INSPECTED = ['GitHub wiki', 'websites outside the GitHub REST API', 'images and PDFs',
                   'issue, pull request and discussion comments',
                   "files in repositories other than the source and its owner's .github repository",
                   'non-Latin-script text (see per-source notes)']
OBLIGATION = ('This report is not a verdict and never shows that contributions are permitted. Read every scanned '
              'source in full, every hint in context and every unassessed reference before ranking or preparing '
              'work. Record each relevant source with its revision or content digest. A policy-relevant source you '
              'cannot read, or unknown contributor eligibility under a maintainers-only rule, is unresolved: '
              'unresolved policy blocks upstream preparation, implementation and publication. So does any limit with '
              'hides_sources true or any omitted_sources entry, until each omitted candidate is read manually or '
              'shown inapplicable. This review remains a host obligation even when every count is zero.')

AI_TERMS = {'ai', 'llm', 'llms', 'chatgpt', 'copilot', 'claude', 'cursor', 'codex', 'gemini', 'vibe', 'genai'}
AGENT_TERMS = {'agent', 'agents', 'agentic', 'autonomous', 'autonomously', 'bot', 'bots', 'automated', 'automation'}
PR_TERMS = {'pr', 'prs', 'patch', 'patches', 'contribution', 'contributions', 'contribute'}
RESTRICT_TERMS = {'not', 'no', 'never', 'nor', 'only', 'limited', 'restricted', 'closed', 'close', 'closes',
                  'reject', 'rejected', 'rejects', 'refuse', 'refused', 'refuses', 'forbid', 'forbidden', 'forbids',
                  'prohibit', 'prohibited', 'prohibits', 'ban', 'banned', 'bans', 'disallow', 'disallowed',
                  'invitation', 'invite', 'invited', 'maintainers', 'members', 'instead', 'must'}
# Who may open pull requests ("limited to maintainers", "issues instead of pull requests"); not the singular
# "a maintainer's time", which is common in permissive AI wording.
ELIGIBILITY_TERMS = {'maintainers', 'members', 'collaborators', 'limited', 'restricted', 'invitation', 'invite',
                     'invited', 'instead'}
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


def _named(name, prefixes):
    """name is a prefix exactly or followed by a separator: contributing.en.md, contributing-guide.md, ai_usage_rules.md."""
    return any(name == p or name.startswith(p) and name[len(p)] in '.-_ ' for p in prefixes)


def kind_of(path):
    """Scan kind for a policy-relevant path, judged on the full original path; or None. Not a GitHub fallback identity."""
    lowered = path.casefold()
    parts = lowered.split('/')
    name = parts[-1]
    if name == '.cursorrules' or lowered.startswith('.cursor/rules/') or name == 'llms.txt':
        return 'agent_instructions'
    if _named(name, ('agents', 'claude', 'gemini', 'copilot-instructions')):
        return 'agent_instructions'
    if _named(name, ('ai', 'llm')):
        return 'ai_policy'
    if _named(name, ('contributing', 'contribute')) or any(
            p in ('contributing', 'contributors', 'contribute', 'policy', 'policies') for p in parts[:-1]):
        return 'contributing'
    if _named(name, ('pull_request_template',)) or lowered.startswith('.github/pull_request_template/'):
        return 'pr_template'
    if _named(name, ('code_of_conduct', 'code-of-conduct', 'security', 'support', 'governance')):
        return 'community'
    if len(parts) == 1 and _named(name, ('readme',)):
        return 'readme'
    return None


def _format(path):
    name = path.rsplit('/', 1)[-1]
    return '.' + name.rsplit('.', 1)[1].casefold() if '.' in name[1:] else ''


def _clean(text):
    """safe_text without its default 100,000-character cut: callers bound sizes, and silent truncation hid
    the tail of long paragraphs (RP-14)."""
    return core.safe_text(text, len(text))


def normalize(text):
    text = _clean(html.unescape(_clean(text)))
    text = TAG.sub(' ', text)  # a tag starts with a letter, so HTML comment bodies stay and are scanned
    return NOT_CONTRACTION.sub(' not', unicodedata.normalize('NFKC', text))


def _non_latin(text):
    if text.isascii():
        return False
    return any(c.isalpha() and not (ord(c) < 0x250 or 0x1E00 <= ord(c) <= 0x1EFF or 0x2C60 <= ord(c) <= 0x2C7F or
                                    0xA720 <= ord(c) <= 0xA7FF) for c in text)


def _groups(tokens):
    found = {'ai': [], 'agent': [], 'pr': [], 'restrict': [], 'elig': []}
    for index, (_, token) in enumerate(tokens):
        if token in AI_TERMS or token.startswith('gpt'):
            found['ai'].append(index)
        if token in AGENT_TERMS:
            found['agent'].append(index)
        if token in PR_TERMS:
            found['pr'].append(index)
        if token in RESTRICT_TERMS:
            found['restrict'].append(index)
        if token in ELIGIBILITY_TERMS:
            found['elig'].append(index)
        for words, group in PHRASES.get(token, ()):
            if tuple(t for _, t in tokens[index:index + len(words)]) == words:
                found[group].append(index)
    return found


def _pair(anchors, restrict):
    """(anchor, nearest-window restriction index) for the first anchor with a restriction in range, or None."""
    for anchor in anchors:
        at = bisect.bisect_left(restrict, anchor - WINDOW)
        if at < len(restrict) and restrict[at] <= anchor + WINDOW:
            return anchor, restrict[at]
    return None


def _near(anchors, restrict):
    pair = _pair(anchors, restrict)
    return pair and pair[0]


PREDICATE_WITHIN = 170  # characters from the excerpt start within which the restriction word must end (RP-26)


def _excerpt(text, offset, focus_end=None):
    """(excerpt, truncated). Starts about 100 characters before the anchor, but late enough that the restriction
    word (ending at focus_end) lies within the first PREDICATE_WITHIN characters, so a short view keeps it."""
    start = max(0, offset - 100)
    if focus_end is not None and focus_end - start > PREDICATE_WITHIN:
        start = max(0, focus_end - PREDICATE_WITHIN)
    limit = min(offset, focus_end) if focus_end is not None else offset
    if start and not text[start - 1].isspace() and start < limit:  # begin at the next word, never mid-word
        space = text.find(' ', start, limit)
        start = limit if space < 0 else space + 1
    collapsed = ' '.join(text[start:start + EXCERPT_CHARS * 4].split())
    return collapsed[:EXCERPT_CHARS], bool(text[:start].strip()) or len(collapsed) > EXCERPT_CHARS


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
    text = _clean(text)
    hints, non_latin = [], 0
    for line, heading, block in _paragraphs(text):
        normalized = normalize(block)
        if _non_latin(normalized):
            non_latin += 1
        matches = list(TOKEN.finditer(normalized))
        tokens = [(m.start(), m.group().casefold()) for m in matches]
        found = _groups(tokens)
        mention = min(found['ai'] + found['agent']) if found['ai'] or found['agent'] else None
        candidates = [('possible_agent_restriction', _pair(found['agent'], found['restrict'])),
                      ('possible_ai_restriction', _pair(found['ai'], found['restrict'])),
                      ('possible_pr_restriction', _pair(found['pr'], found['restrict'])),
                      ('ai_mention', None if mention is None else (mention, None))]
        for kind, pair in candidates:
            if pair is not None:
                anchor, restriction = pair
                excerpt, truncated = _excerpt(normalized, matches[anchor].start(),
                                              None if restriction is None else matches[restriction].end())
                hints.append({'kind': kind, 'line': line, 'heading': core.safe_text(heading, 120),
                              'untrusted_excerpt': excerpt, 'excerpt_truncated': truncated,
                              'ai_context': bool(found['ai'] or found['agent']),
                              'eligibility': kind == 'possible_pr_restriction' and
                              _near(found['pr'], found['elig']) is not None})
    return {'hints': hints, 'links': _links(text), 'non_latin_paragraphs': non_latin}


class _Report:
    def __init__(self, client):
        self.client, self.requests, self.skipped = client, 0, 0
        self.sources, self.texts, self.unassessed, self.limits = [], [], [], {}
        self.seen, self.keys = set(), []  # every identity noted; identities of retained entries (aligned)
        self.omitted, self.scanned = [], set()  # scanned: original (repository, path) identities
        self.scanned_bytes = 0

    def get(self, endpoint):
        if self.requests >= MAX_REQUESTS:
            self.skipped += 1
            raise _Limit()
        self.requests += 1
        return self.client.request(endpoint)

    def note(self, what, reason, origin=None, line=None, link_text=None, key=None):
        """key is the original identity (repository and path, or URL); what is display text, possibly altered."""
        raw = str(what)
        what = core.safe_text(raw, len(raw))
        key = key or raw
        if key in self.seen:
            return
        self.seen.add(key)
        if len(self.unassessed) >= MAX_UNASSESSED:  # count, do not retain: bounded memory and linear time (RP-16)
            self.limit('unassessed entries')
            return
        self.keys.append(key)
        self.unassessed.append({'what': what[:IDENTIFIER_CHARS], 'reason': reason, 'from': origin, 'line': line,
                                'link_text': core.safe_text(link_text, EXCERPT_CHARS) if link_text else None,
                                'what_truncated': len(what) > IDENTIFIER_CHARS, 'what_sanitized': what != raw,
                                'identity_sha256': _identity(key)})

    def omit(self, repository, path, kind, reason):
        """A policy candidate a limit kept unread: named (bounded), never only counted (RP-19)."""
        if len(self.omitted) >= MAX_OMITTED:
            self.limit('omitted sources not listed')
            return
        self.omitted.append({'repository': repository, **_display(path), 'kind': kind or 'instruction',
                             'reason': reason, 'identity_sha256': _identity((repository.casefold(), path))})

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

    def add(self, origin, repository, path, commit, digest, kind, text, size):
        """size is the source's UTF-8 byte count, the unit of the 1 MB scan bound (RP-18)."""
        if self.scanned_bytes + size > MAX_SCANNED_BYTES:
            self.limit('scanned bytes')
            self.omit(repository, path, kind, 'scan byte limit')
            return
        self.scanned_bytes += size
        result = scan(text, path)
        notes = ([f'paragraphs with non-Latin script not assessed: {result["non_latin_paragraphs"]}']
                 if result['non_latin_paragraphs'] else [])
        self.sources.append({'origin': origin, 'repository': repository, **_display(path),
                             'identity_sha256': _identity((repository.casefold(), path)),
                             'commit': commit, 'sha256': digest, 'kind': kind or 'instruction', 'notes': notes})
        self.scanned.add((repository.casefold(), path))
        self.texts.append((path, result))

    def fetch(self, origin, repository, commit, path, blob, kind):
        label, key = (path if origin == 'repository' else f'{repository}:{path}'), (repository.casefold(), path)
        try:
            value = core.require(self.get(f'repos/{repository}/contents/{quote(path, safe="/")}?ref={commit}'),
                                 dict, 'file')
            if value.get('encoding') != 'base64':
                raise core.ProtocolError('file_encoding', 'not base64')
            data = base64.b64decode(''.join(core.require(value.get('content'), str, 'content').split()), validate=True)
        except _Limit:
            self.omit(repository, path, kind, 'request limit')
            return
        except (core.ProtocolError, ValueError, binascii.Error):
            self.note(label, 'read failed', key=key)
            return
        if len(data) > MAX_FILE_BYTES:
            self.note(label, 'exceeds 200 kB', key=key)
        elif not _pinned(blob, value.get('sha'), data):
            self.note(label, 'content did not match the pinned tree entry', key=key)
        else:
            try:
                text = data.decode('utf-8')
            except UnicodeError:
                self.note(label, 'not UTF-8 text', key=key)
                return
            self.add(origin, repository, path, commit, hashlib.sha256(data).hexdigest(), kind, text, len(data))

    def read_candidates(self, origin, repository, commit, blobs, skip, cap, limit_name, allowed=lambda path: True):
        found = []
        for path, blob in blobs.items():
            kind = kind_of(core.safe_text(path, len(path)))  # classify the full path, display it shortened (RP-17)
            if (kind is None or path in skip or not allowed(path) or origin != 'repository' and kind == 'readme' or
                    _format(path) not in SCANNED_FORMATS | DOCUMENT_FORMATS):
                continue
            if _format(path) not in SCANNED_FORMATS:
                self.note(path if origin == 'repository' else f'{repository}:{path}', 'unsupported format',
                          key=(repository.casefold(), path))
                continue
            # Nested security/governance files are read after top-level ones and rank lower; never skipped (RP-25).
            found.append((KIND_ORDER.index(kind), kind == 'community' and not _top_level(path), path, blob, kind))
        found.sort()
        for _, _, path, blob, kind in found[:cap]:
            self.fetch(origin, repository, commit, path, blob, kind)
        for _, _, path, _, kind in found[cap:]:
            self.omit(repository, path, kind, 'file limit')
        if len(found) > cap:
            self.limit(limit_name, len(found) - cap)


def _identity(key):
    """SHA-256 of an original identity: [repository, path] as read from GitHub, or a URL string."""
    return core.canonical_hash(key if isinstance(key, str) else list(key))


def _display(path):
    """Display fields for a path: sanitized, shortened, and flags saying either happened."""
    shown = core.safe_text(path, len(path))
    return {'path': shown[:IDENTIFIER_CHARS], 'path_truncated': len(shown) > IDENTIFIER_CHARS,
            'path_sanitized': shown != path}


def _top_level(path):
    """Root, .github/ or docs/: where security, support, governance and conduct files are usually policy (N-04)."""
    parts = path.split('/')
    return len(parts) == 1 or len(parts) == 2 and parts[0].casefold() in ('.github', 'docs')


def _tier(hint, source):
    """Attention order: agent, PR eligibility rules, AI, PR hints with AI context, PR hints in policy files, other PR
    hints, restrictions from nested security/governance files (RP-25: lower, never dropped), mentions."""
    source_kind = source['kind']
    if hint['kind'] not in STOP_HINTS:
        return 7
    if source_kind == 'community' and not _top_level(source['path']):
        return 6
    if hint['kind'] != 'possible_pr_restriction':
        return {'possible_agent_restriction': 0, 'possible_ai_restriction': 2}[hint['kind']]
    if hint['eligibility']:
        return 1
    return 3 if hint['ai_context'] else 4 if source_kind in POLICY_KINDS else 5


def _pinned(blob, reported, data):
    """The returned bytes are the tree's blob: both SHA fields agree and the Git blob SHA-1 of the bytes matches."""
    if not isinstance(blob, str) or reported != blob:
        return False  # the SHA-1 comparison below also rejects a malformed or non-lowercase identity
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
        if len(item['path']) >= IDENTIFIER_CHARS:  # core stores instruction paths shortened to 500 characters
            state.note(item['path'], 'instruction path may be shortened by core; identity unresolved')
        state.add('repository', repository, item['path'], commit, item['sha256'], kind_of(item['path']),
                  item['untrusted_text'], len(item['untrusted_text'].encode('utf-8')))
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
    scanned = state.scanned
    hints = []
    for index, (source, (path, result)) in enumerate(zip(state.sources, state.texts)):
        hints += [dict(hint, source=index, tier=_tier(hint, source)) for hint in result['hints']]
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
    hints.sort(key=lambda hint: (hint['tier'], hint['source'], hint['line']))
    for hint in hints[MAX_HINTS:]:  # mentions go first; a dropped stop-class hint is a hiding limit (N-04)
        state.limit('restriction hints' if hint['kind'] in STOP_HINTS else 'hints')
    hints = [{k: v for k, v in hint.items() if k not in ('tier', 'ai_context', 'eligibility')} for hint in hints[:MAX_HINTS]]
    result = {'report': 'policy-report/1', 'review_obligation': OBLIGATION, 'sources_scanned': state.sources,
              'unassessed': state.unassessed, 'omitted_sources': state.omitted, 'limits_reached': [],
              'limits_hide_sources': False,
              'never_inspected': list(NEVER_INSPECTED),
              'hints': [dict(hint, id=f'H{n}') for n, hint in enumerate(hints, 1)],
              'reads': {'requests': state.requests, 'limit': MAX_REQUESTS}}
    while True:
        result['limits_reached'] = [{'limit': name, 'not_reported': count, 'hides_sources': name in HIDING_LIMITS}
                                    for name, count in sorted(state.limits.items())]
        result['limits_hide_sources'] = bool(result['omitted_sources']) or any(
            item['hides_sources'] for item in result['limits_reached'])
        result['inventory_sha256'] = core.canonical_hash({
            # Original identities, never display text, which may be shortened or sanitized (RP-23).
            'sources': sorted([s['origin'], s['identity_sha256'], s['sha256']] for s in result['sources_scanned']),
            # Full identities, not the shortened display text (RP-20); state.keys is aligned with retained entries.
            'unassessed': sorted(json.dumps(key) for key in state.keys[:len(result['unassessed'])]),
            'omitted_sources': sorted([o['identity_sha256'], o['reason']] for o in result['omitted_sources']),
            'limits_reached': result['limits_reached']})
        if len(json.dumps(result, ensure_ascii=True).encode()) <= MAX_REPORT_BYTES:
            return result
        # Shrink until the serialized report fits, recording every reduction (RP-18).
        long_paths = [s for s in result['sources_scanned'] if len(s['path']) > 80]
        if result['hints']:
            dropped = result['hints'].pop()
            state.limit('report size: restriction hints' if dropped['kind'] in STOP_HINTS else 'report size: hints')
        elif result['unassessed']:
            result['unassessed'].pop()
            state.limit('report size: unassessed entries')
        elif result['omitted_sources']:
            result['omitted_sources'].pop()
            state.limit('report size: omitted sources')
        elif long_paths:
            for source in long_paths:
                source.update(path=source['path'][:80], path_truncated=True)
            state.limit('report size: shortened paths', len(long_paths))
        elif result['sources_scanned']:
            result['sources_scanned'].pop()
            state.limit('report size: sources not listed')
        else:
            return result


def for_inspected(inspected, client):
    """The report for an inspect result's issue source at its observed commit."""
    source = inspected['source']
    return report(source['repository'], source['commit'], inspected['instructions'], client,
                  default_branch=source['default_branch'])
