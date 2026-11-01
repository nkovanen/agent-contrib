"""Offline local-checkout helpers. No GitHub reads, no argv execution, never evidence."""
import re

from . import core

DIFF = ('diff', '--no-ext-diff', '--no-textconv', '--ignore-submodules=none', '--no-renames', '--name-only', '-z')


def scope_check(task, directory, base=None):
    errors = core.validate_contract(task)
    result = {'within_scope': False, 'base_commit': None, 'changed_paths': [], 'violations': [], 'errors': errors,
              'evidence': 'A pass is not evidence and is never recorded as such; verify remains authoritative.'}
    if errors:
        return result
    base = task['source']['commit'] if base is None else base
    if not isinstance(base, str) or not re.fullmatch('[0-9a-f]{40}', base):
        errors.append('Base must be a full lowercase 40-character commit SHA')
        return result
    result['base_commit'] = base
    try:
        try:
            core.git_read(directory, 'merge-base', '--is-ancestor', base, 'HEAD')
        except core.ProtocolError:
            raise core.ProtocolError('git_error', 'Base commit is missing or not an ancestor of HEAD') from None
        if core.has_gitlink(directory, 'HEAD', base):
            errors.append('Submodule/gitlink evidence is unsupported; no submodule commands were run')
        paths = set(core.implementation_paths(directory, base))
        # Index, working tree and untracked files: everything a later commit could contain.
        for args in (DIFF + ('--cached', base), DIFF + (base,), ('ls-files', '-z', '--others', '--exclude-standard')):
            paths.update(path for path in core.git_read(directory, *args).split('\0') if path)
        result['changed_paths'] = sorted(core.safe_text(path, 500) for path in paths)
        result['violations'] = sorted(core.scope_violations(task['scope'], paths), key=lambda item: item['path'])
    except core.ProtocolError as exc:
        errors.append(str(exc))
    result['within_scope'] = not errors and not result['violations']
    return result
