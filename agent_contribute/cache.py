"""Opt-in local cache of file contents at a pinned commit (#27). Content-addressed and self-verifying.

Only one kind of read is ever served from the cache: repos/{owner}/{repo}/contents/{path}?ref={commit} for a
repository whose live metadata in this process said private: false and visibility: public, when a live
recursive tree at that commit named the path's blob SHA. Entries are the verified blob bytes, named by that SHA. Every hit recomputes the Git blob hash
(sha1 of "blob <len>\\0<bytes>") and must equal the live tree's SHA; anything else is deleted and read live. Trees,
metadata and every mutable read are always live. The cache is a convenience: any failure falls back to the live read.
"""
import base64
import binascii
import errno
import hashlib
import os
import re
import secrets
import stat
import time
from urllib.parse import quote, unquote

ENTRY_LIMIT = 8 * 1024 * 1024  # the response cap; GitHub contents responses are smaller
TOTAL_LIMIT = 256 * 1024 * 1024
PREFIX = 'blob-'
_NAME = r'[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}'
METADATA = re.compile(rf'repos/({_NAME})')
COMMIT = re.compile(rf'repos/({_NAME})/commits/([^?#]+)')
TREE = re.compile(rf'repos/({_NAME})/git/trees/([0-9a-f]{{40}})\?recursive=1')
CONTENTS = re.compile(rf'repos/({_NAME})/contents/([^?#]+)\?ref=([0-9a-f]{{40}})')
BLOB = re.compile(r'[0-9a-f]{40}')
ENTRY = re.compile(PREFIX + r'[0-9a-f]{40}')  # eviction touches only valid entry names
TEMPORARY = re.compile(r'\.tmp-[0-9a-f]{32}')  # our own in-progress store files
STALE_TEMPORARY = 3600  # seconds; an older temporary file is left over from a crashed store

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
    if _active is not None:
        _active.close()
    _active = Cache(directory or default_directory()) if enabled else None


def active():
    return _active


class Cache:
    def __init__(self, directory):
        self.directory = directory
        self.public = set()  # casefolded owner/repo whose live metadata said private: false, visibility: public
        self.commit_trees = {}  # (repository, commit) -> canonical tree from a live commit object
        self.blobs = {}  # (casefolded owner/repo, commit or tree) -> {path: blob SHA} from a live, complete tree
        self._fd, self._checked = None, False

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
            # Both fields must agree: internal repositories report private: false with visibility: internal.
            public = (isinstance(value, dict) and value.get('private') is False and
                      value.get('visibility') == 'public' and
                      isinstance(value.get('full_name'), str) and value['full_name'].casefold() == name)
            (self.public.add if public else self.public.discard)(name)
            return
        match = COMMIT.fullmatch(endpoint)
        if match:
            if isinstance(value, dict):
                commit = value.get('sha')
                tree = value.get('commit', {}).get('tree', {}).get('sha')
                if (isinstance(commit, str) and BLOB.fullmatch(commit) and
                        isinstance(tree, str) and BLOB.fullmatch(tree) and
                        (not BLOB.fullmatch(match[2]) or match[2] == commit)):
                    self.commit_trees[(match[1].casefold(), commit)] = tree
            return
        match = TREE.fullmatch(endpoint)
        if match:
            key = (match[1].casefold(), match[2])
            self.blobs.pop(key, None)
            if isinstance(value, dict) and value.get('truncated') is False and isinstance(value.get('tree'), list):
                from . import core  # deferred: core imports this module
                try:  # one malformed entry makes the whole tree uncacheable, so every content read stays live
                    kinds = [kind for _, kind in core.tree_entries(value['tree'])]
                except core.ProtocolError:
                    return
                self.blobs[key] = {entry['path']: entry['sha'] for entry, kind in zip(value['tree'], kinds)
                                   if kind == 'blob' and isinstance(entry.get('sha'), str) and
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
        tree = self.commit_trees.get((name, commit))
        return self.blobs.get((name, commit), self.blobs.get((name, tree), {})).get(path), path

    def _root(self):
        """A descriptor for the checked cache directory, or None to bypass the cache. Every entry operation is
        relative to this descriptor, so renaming or replacing the directory's name later cannot redirect them."""
        if not self._checked:
            self._checked = True
            try:
                self._fd = _open_directory(self.directory)
            except (OSError, AttributeError, ValueError):  # unsafe ancestor, no POSIX ownership or no dir_fd support
                self._fd = None
        return self._fd

    def close(self):
        if self._fd is not None:
            os.close(self._fd)
        self._fd, self._checked = None, True

    def _name(self, sha):
        return PREFIX + sha if self._root() is not None and BLOB.fullmatch(sha) else None

    def _read(self, sha):
        name = self._name(sha)
        if name is None:
            return None
        try:
            # Nonblocking, so a FIFO or device entry cannot stall the read; fstat then admits only a regular file.
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self._fd)
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
        name = self._name(sha)
        if name is not None:
            try:
                os.unlink(name, dir_fd=self._fd)
            except OSError:
                pass

    def _store(self, sha, data):
        name = self._name(sha)
        if name is None:
            return
        temporary = '.tmp-' + secrets.token_hex(16)
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self._fd)
        try:
            with os.fdopen(descriptor, 'wb') as handle:
                handle.write(data)
            os.rename(temporary, name, src_dir_fd=self._fd, dst_dir_fd=self._fd)  # atomic replace on POSIX
        except BaseException:
            try:
                os.unlink(temporary, dir_fd=self._fd)
            except OSError:
                pass
            raise
        self._evict()

    def _evict(self):
        entries, pending, stale_before = [], 0, time.time() - STALE_TEMPORARY
        with os.scandir(self._fd) as listing:
            for entry in listing:
                try:
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    if ENTRY.fullmatch(entry.name):
                        info = entry.stat(follow_symlinks=False)
                        entries.append((info.st_mtime, entry.name, info.st_size))
                    elif TEMPORARY.fullmatch(entry.name):
                        info = entry.stat(follow_symlinks=False)
                        if info.st_mtime < stale_before:  # orphaned by a crashed store
                            os.unlink(entry.name, dir_fd=self._fd)
                        else:  # possibly a concurrent store in progress: it counts, but is not ours to delete
                            pending += info.st_size
                except FileNotFoundError:  # another invocation evicted it meanwhile; it no longer counts
                    continue
        total = pending + sum(size for _, _, size in entries)
        for _, name, size in sorted(entries):
            if total <= TOTAL_LIMIT:
                break
            try:
                os.unlink(name, dir_fd=self._fd)
            except FileNotFoundError:  # already gone, so it no longer counts either
                pass
            except OSError:
                continue
            total -= size


ACL_ATTRIBUTES = {'system.posix_acl_access', 'system.posix_acl_default'}


def _has_acl(descriptor):
    """Any doubt counts as an ACL: only a listing without POSIX ACL attributes, or a filesystem without xattr
    support (ENOTSUP), rules one out. Without os.listxattr the cache is disabled."""
    try:
        return bool(ACL_ATTRIBUTES & set(os.listxattr(descriptor)))
    except OSError as exc:
        return exc.errno != errno.ENOTSUP


def _check_ancestor(descriptor, uid):
    """Another account able to rename entries in an ancestor makes the cache unsafe. Each ancestor must be owned by
    root or the user and not group- or other-writable; the one exception is a root-owned sticky directory (/tmp).
    A non-root-owned ancestor must also carry no POSIX ACL, which could grant another account write access."""
    info = os.fstat(descriptor)
    shared = info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    if info.st_uid not in (0, uid) or (shared and not (info.st_uid == 0 and info.st_mode & stat.S_ISVTX)):
        raise PermissionError('Unsafe cache ancestor')
    if info.st_uid != 0 and _has_acl(descriptor):
        raise PermissionError('Cache ancestor carries a POSIX ACL')


def _open_child(name, parent, create=False):
    """Open one directory component relative to its parent, never following a symlink. Only the cache directory
    itself is created (0700), after every ancestor passed, so a refused run leaves nothing behind."""
    if create:
        try:
            os.mkdir(name, 0o700, dir_fd=parent)
        except FileExistsError:
            pass
    return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)


def _open_directory(directory):
    """Walk every component of the absolute cache path from / with O_NOFOLLOW, so no symlink anywhere in the chain
    is followed, checking each ancestor. The cache directory itself must be the user's, mode 0700 exactly and
    without a POSIX ACL. Any doubt disables the cache; it is never an error."""
    if not all(function in os.supports_dir_fd for function in (os.open, os.stat, os.unlink, os.rename, os.mkdir)) or (
            os.scandir not in os.supports_fd) or not hasattr(os, 'listxattr'):
        raise ValueError('No dir_fd or xattr support: the cache is disabled')
    uid = os.getuid()
    parts = [part for part in os.path.abspath(directory).split(os.sep) if part]
    if not parts:
        raise ValueError('The cache directory cannot be the filesystem root')
    current = os.open(os.sep, os.O_RDONLY | os.O_DIRECTORY)
    try:
        _check_ancestor(current, uid)
        for part in parts[:-1]:
            following = _open_child(part, current)
            os.close(current)
            current = following
            _check_ancestor(current, uid)
        root = _open_child(parts[-1], current, create=True)
    finally:
        os.close(current)
    info = os.fstat(root)
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or stat.S_IMODE(info.st_mode) != 0o700 or
            _has_acl(root)):
        os.close(root)
        raise PermissionError('Cache directory is not a private 0700 directory of this user')
    return root
