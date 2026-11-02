"""Opt-in local cache of file contents at a pinned commit (#27). Content-addressed and self-verifying.

Only one kind of read is ever served from the cache: repos/{owner}/{repo}/contents/{path}?ref={commit} for a
repository whose live metadata in this process said private: false, when a live recursive tree at that commit named
the path's blob SHA. Entries are the verified blob bytes, named by that SHA. Every hit recomputes the Git blob hash
(sha1 of "blob <len>\\0<bytes>") and must equal the live tree's SHA; anything else is deleted and read live. Trees,
metadata and every mutable read are always live. The cache is a convenience: any failure falls back to the live read.
"""
import base64
import binascii
import hashlib
import os
import re
import stat
import tempfile
from urllib.parse import quote, unquote

ENTRY_LIMIT = 8 * 1024 * 1024  # the response cap; GitHub contents responses are smaller
TOTAL_LIMIT = 256 * 1024 * 1024
PREFIX = 'blob-'
_NAME = r'[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}'
METADATA = re.compile(rf'repos/({_NAME})')
TREE = re.compile(rf'repos/({_NAME})/git/trees/([0-9a-f]{{40}})\?recursive=1')
CONTENTS = re.compile(rf'repos/({_NAME})/contents/([^?#]+)\?ref=([0-9a-f]{{40}})')
BLOB = re.compile(r'[0-9a-f]{40}')

_active = None


def blob_sha(data):
    return hashlib.sha1(b'blob %d\0' % len(data) + data).hexdigest()


def default_directory():
    base = os.environ.get('XDG_CACHE_HOME', '')
    if not os.path.isabs(base):  # the XDG specification ignores a relative value
        base = os.path.join(os.path.expanduser('~'), '.cache')
    return os.path.join(base, 'agent-contrib')


def configure(enabled, directory=None):
    global _active
    _active = Cache(directory or default_directory()) if enabled else None


def active():
    return _active


class Cache:
    def __init__(self, directory):
        self.directory = directory
        self.public = set()  # casefolded owner/repo whose live metadata said private: false
        self.blobs = {}  # (casefolded owner/repo, commit) -> {path: blob SHA} from a live, complete tree
        self.usable = None

    def lookup(self, endpoint):
        """Verified cached response for a pinned contents read, or None to read live."""
        try:
            expected, path = self._expected(endpoint)
            if expected is None:
                return None
            data = self._read(expected)
            if data is None:
                return None
            if blob_sha(data) != expected:
                self._discard(expected)
                return None
            return {'type': 'file', 'encoding': 'base64', 'content': base64.b64encode(data).decode('ascii'),
                    'sha': expected, 'size': len(data), 'path': path, 'name': path.rsplit('/', 1)[-1]}
        except Exception:  # the cache must never fail or change a command
            return None

    def observe(self, endpoint, value):
        """Learn from a successful live response; store verified contents."""
        try:
            self._observe(endpoint, value)
        except Exception:
            pass

    def _observe(self, endpoint, value):
        match = METADATA.fullmatch(endpoint)
        if match:
            name = match[1].casefold()
            public = (isinstance(value, dict) and value.get('private') is False and
                      isinstance(value.get('full_name'), str) and value['full_name'].casefold() == name)
            (self.public.add if public else self.public.discard)(name)
            return
        match = TREE.fullmatch(endpoint)
        if match:
            key = (match[1].casefold(), match[2])
            self.blobs.pop(key, None)
            if isinstance(value, dict) and value.get('truncated') is False and isinstance(value.get('tree'), list):
                self.blobs[key] = {entry['path']: entry['sha'] for entry in value['tree']
                                   if isinstance(entry, dict) and entry.get('type') == 'blob' and
                                   isinstance(entry.get('path'), str) and isinstance(entry.get('sha'), str) and
                                   BLOB.fullmatch(entry['sha'])}
            return
        expected, _ = self._expected(endpoint)
        if expected is None or not isinstance(value, dict) or value.get('encoding') != 'base64':
            return
        if value.get('sha') != expected or not isinstance(value.get('content'), str):
            return
        try:
            data = base64.b64decode(''.join(value['content'].split()), validate=True)
        except (binascii.Error, ValueError):
            return
        if len(data) <= ENTRY_LIMIT and blob_sha(data) == expected:
            self._store(expected, data)

    def _expected(self, endpoint):
        match = CONTENTS.fullmatch(endpoint)
        if not match:
            return None, None
        name, quoted, commit = match[1].casefold(), match[2], match[3]
        path = unquote(quoted)
        # Only the exact quoting core uses, so one path has one endpoint. The path is a key into the live tree's
        # blob map, never a filesystem path; entries are named by blob SHA.
        if quote(path, safe='/') != quoted or name not in self.public:
            return None, None
        return self.blobs.get((name, commit), {}).get(path), path

    def _root(self):
        """The cache directory if it is safe to use: a real directory owned by this user, not group/other writable."""
        if self.usable is None:
            self.usable = False
            try:
                uid = os.getuid()
                os.makedirs(self.directory, mode=0o700, exist_ok=True)
                info = os.lstat(self.directory)
                self.usable = (stat.S_ISDIR(info.st_mode) and info.st_uid == uid and
                               not info.st_mode & (stat.S_IWGRP | stat.S_IWOTH))
            except (OSError, AttributeError):  # no POSIX ownership: bypass
                self.usable = False
        return self.directory if self.usable else None

    def _path(self, sha):
        root = self._root()
        return os.path.join(root, PREFIX + sha) if root and BLOB.fullmatch(sha) else None

    def _read(self, sha):
        path = self._path(sha)
        if path is None:
            return None
        try:
            descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        except FileNotFoundError:
            return None
        except OSError:  # a symlink (ELOOP) or unreadable entry
            self._discard(sha)
            return None
        with os.fdopen(descriptor, 'rb') as handle:
            info = os.fstat(handle.fileno())
            # The bounded read rejects an oversized entry without reading it whole.
            data = handle.read(ENTRY_LIMIT + 1) if stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() else None
        if data is None or len(data) > ENTRY_LIMIT:
            self._discard(sha)
            return None
        return data

    def _discard(self, sha):
        path = self._path(sha)
        if path is not None:
            try:
                os.unlink(path)
            except OSError:
                pass

    def _store(self, sha, data):
        path = self._path(sha)
        if path is None:
            return
        descriptor, temporary = tempfile.mkstemp(prefix='.tmp-', dir=os.path.dirname(path))  # mode 0600
        try:
            with os.fdopen(descriptor, 'wb') as handle:
                handle.write(data)
            os.replace(temporary, path)
        except BaseException:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
        self._evict()

    def _evict(self):
        entries = []
        with os.scandir(self._root()) as listing:
            for entry in listing:
                if entry.name.startswith(PREFIX) and entry.is_file(follow_symlinks=False):
                    info = entry.stat(follow_symlinks=False)
                    entries.append((info.st_mtime, entry.name, info.st_size))
        total = sum(size for _, _, size in entries)
        for _, name, size in sorted(entries):
            if total <= TOTAL_LIMIT:
                break
            try:
                os.unlink(os.path.join(self._root(), name))
                total -= size
            except OSError:
                pass
