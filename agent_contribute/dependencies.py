"""Bounded offline dependency observations. Declarations are never executed or resolved online."""
import hashlib
import os
from pathlib import Path
import re
import stat
from urllib.parse import urlsplit

from . import core

FILES = ('package.json', 'package-lock.json', 'requirements.txt')
UNSUPPORTED = ('Cargo.toml', 'Cargo.lock', 'pyproject.toml')
GROUPS = ('dependencies', 'devDependencies', 'optionalDependencies', 'peerDependencies')
MAX_ENTRIES = 10000
MAX_STRING = 4096
NOTICE = ('Dependency candidates only; this report grants no approval, execution or publication authority. '
          'Review repository policy and any jar before choosing work. No network requests were made.')


def _invalid():
    raise core.ProtocolError('dependency_input', 'Invalid or unsupported dependency manifest structure')


def _string(value):
    if not isinstance(value, str) or not value or len(value) > MAX_STRING or any(ord(c) < 32 for c in value):
        _invalid()
    return value


def _mapping(value):
    if not isinstance(value, dict):
        _invalid()
    return value


def _safe_relative(value):
    return (bool(value) and len(value) <= 512 and not value.startswith('/') and
            not any(c in value for c in '\\%?#@&') and
            all(part not in ('', '.', '..') for part in value.split('/')) and
            not any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value))


def github_url(value):
    """Recognize a conservative explicit URL subset; never infer a repository from a package name."""
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value) or any(c in value for c in '\\%?'):
        return None
    url, separator, fragment = value.partition('#')
    if '#' in fragment:
        return None
    if url.startswith('git@github.com:'):
        path = url[len('git@github.com:'):]
    else:
        if url.startswith('git+'):
            url = url[4:]
        try:
            parsed = urlsplit(url)
        except ValueError:
            return None
        if parsed.scheme != 'https' or parsed.netloc.lower() != 'github.com':
            return None
        path = parsed.path.removeprefix('/')
    path, at, revision = path.partition('@')
    subdirectory = None
    if separator:
        if fragment.startswith('subdirectory='):
            subdirectory = fragment[len('subdirectory='):]
            if not _safe_relative(subdirectory) or ':' in subdirectory:
                return None
        elif not at:
            revision = fragment
        else:
            return None
    if (at or (separator and subdirectory is None)) and not _safe_relative(revision):
        return None
    path = path.removesuffix('.git')
    try:
        repository = core.parse_repository(path)
    except core.ProtocolError:
        return None
    return repository, revision or None, subdirectory


def _open_path(path):
    """Open each component without following links; descriptor-relative walks prevent ancestor swaps."""
    if not hasattr(os, 'O_NOFOLLOW') or os.open not in os.supports_dir_fd:
        raise OSError('Symlink-safe file reads are unavailable on this platform')
    if '..' in Path(path).parts:
        raise OSError('Parent traversal is unsupported')
    path = Path(os.path.abspath(path))
    descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for index, component in enumerate(path.parts[1:]):
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            if index < len(path.parts) - 2:
                flags |= os.O_DIRECTORY
            child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _read_at(directory, name):
    descriptor = os.open(name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=directory)
    with os.fdopen(descriptor, 'rb') as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise OSError('Expected regular manifest')
        data = handle.read(core.MAX_BYTES + 1)
    if len(data) > core.MAX_BYTES:
        raise OSError('Manifest exceeds size bound')
    return data


def _npm_groups(data, prefix=''):
    for group in GROUPS:
        for package, value in _mapping(data.get(group, {})).items():
            yield _string(package), _string(value), prefix + group + '.' + package


def _lock(data):
    version = data.get('lockfileVersion')
    if type(version) is not int or version not in (1, 2, 3):
        _invalid()
    if version in (2, 3):
        for location, record in _mapping(data.get('packages')).items():
            _mapping(record)
            if not location:
                yield from _npm_groups(record, 'packages..')
                continue
            _string(location)
            package = record.get('name', location.rsplit('node_modules/', 1)[-1])
            _string(package)
            value = record.get('resolved', record.get('version'))
            if value is None and record.get('link') is True:
                value = 'local-link'
            field = 'resolved' if 'resolved' in record else 'version'
            yield package, _string(value), f'packages.{location}.{field}'
    else:
        # Iterative traversal keeps nested v1 locks off the Python call stack.
        pending = [(_mapping(data.get('dependencies', {})), 'dependencies.')]
        while pending:
            records, prefix = pending.pop()
            for package, record in records.items():
                _string(package)
                _mapping(record)
                field = 'resolved' if 'resolved' in record else 'version'
                yield package, _string(record.get(field)), prefix + package + '.' + field
                if 'dependencies' in record:
                    pending.append((_mapping(record['dependencies']), prefix + package + '.dependencies.'))


def _requirements(text):
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        match = re.fullmatch(r'([A-Za-z0-9][A-Za-z0-9._-]*(?:\[[A-Za-z0-9,._-]+\])?)\s*@\s*(\S+)(?:\s+;.*)?', line)
        if match:
            yield match[1], _string(match[2]), f'line:{number}'
        else:
            name = re.match(r'[A-Za-z0-9][A-Za-z0-9._-]*', line)
            registry = re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*(?:\[[A-Za-z0-9,._-]+\])?(?:\s*[~!<>=].*)?(?:\s*;.*)?', line)
            yield (name[0] if name else f'(unparsed line {number})'), ('registry' if registry else None), f'line:{number}'


def report(path):
    """Read only the fixed supported filenames, or one explicitly selected supported file."""
    directory = None
    try:
        descriptor = _open_path(path)
        mode = os.fstat(descriptor).st_mode
        if stat.S_ISDIR(mode):
            directory = descriptor
            names = FILES
            unsupported = [name for name in UNSUPPORTED
                           if _exists(directory, name)]
        else:
            os.close(descriptor)
            name = Path(path).name
            if name not in FILES:
                raise core.ProtocolError('dependency_input', 'Select a project directory or a supported manifest filename')
            directory = _open_path(Path(path).parent)
            names, unsupported = (name,), []
        sources, dependencies, repositories = [], [], []
        seen = set()
        for name in names:
            if len(names) > 1 and not _exists(directory, name):
                continue
            raw = _read_at(directory, name)
            text = raw.decode('utf-8')
            if name.endswith('.json'):
                data = _mapping(core.strict_json(text))
                declarations = _npm_groups(data) if name == 'package.json' else _lock(data)
                ecosystem = 'npm'
            else:
                declarations, ecosystem = _requirements(text), 'python'
            sources.append({'path': name, 'sha256': hashlib.sha256(raw).hexdigest()})
            for package, value, field in declarations:
                _string(package)
                if len(dependencies) >= MAX_ENTRIES or len(field) > MAX_STRING:
                    _invalid()
                target = github_url(value) if value else None
                repository, revision, subdirectory = target or (None, None, None)
                if target:
                    status, reason = 'github', 'explicit_github_url'
                    if repository.casefold() not in seen:
                        repositories.append(repository)
                        seen.add(repository.casefold())
                elif value is None:
                    status, reason = 'unsupported', 'unsupported_requirement_syntax'
                elif 'github.com' in value.lower():
                    status, reason = 'unresolved', 'unsafe_or_unsupported_github_url'
                elif '://' in value or value.startswith('git@'):
                    status, reason = 'unsupported', 'non_github_source'
                else:
                    status, reason = 'unresolved', 'registry_or_nonexplicit_source'
                dependencies.append({'package': package, 'ecosystem': ecosystem, 'source_file': name,
                                     'field': field, 'status': status, 'reason': reason,
                                     'repository': repository, 'revision': revision, 'subdirectory': subdirectory})
        if not sources and not unsupported:
            raise core.ProtocolError('dependency_input', 'No supported manifests found; no recursive scan was performed')
        return {'schema_version': '0.1', 'complete': not unsupported,
                'resolution_complete': not unsupported and all(d['status'] == 'github' for d in dependencies),
                'sources': sources, 'unsupported_files': unsupported, 'repositories': repositories,
                'dependencies': dependencies, 'warning': NOTICE}
    except (OSError, UnicodeError) as exc:
        raise core.ProtocolError('dependency_input', 'Cannot read bounded UTF-8 regular manifests without symlinks') from exc
    finally:
        if directory is not None:
            os.close(directory)


def _exists(directory, name):
    try:
        os.stat(name, dir_fd=directory, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False
