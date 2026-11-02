"""Offline local-checkout helpers. No GitHub reads, no argv execution, never evidence."""
import re
from pathlib import Path

from . import core

REVISION = re.compile(r'(?P<name>[0-9a-f]{40}|HEAD|refs/[^~^:?*\[\\\s]+)(?P<suffix>(?:[~^][0-9]{0,9})*)')
DIFF = ('diff', '--no-ext-diff', '--no-textconv', '--ignore-submodules=none', '--no-renames', '--name-only', '-z')


def scope_check(task, directory, base=None):
    errors = core.validate_contract(task)
    result = {'within_scope': False, 'base_commit': None, 'changed_paths': [], 'violations': [], 'errors': errors,
              'warnings': [], 'evidence': 'A pass is not evidence and is never recorded as such; verify remains authoritative.'}
    if errors:
        return result
    try:
        core.require_worktree_root(directory)
        core.require_safe_config(directory)
        core.require_plain_index(directory)
        head = core.current_head(directory)
        default = base is None
        base = result['base_commit'] = _base(task['source']['commit']) if default else resolve_base(directory, base)
        try:
            core.git_read(directory, 'merge-base', '--is-ancestor', base, head)
        except core.ProtocolError:
            if default:
                result['warnings'].append('Default base source.commit is not an ancestor of HEAD; for stacked or '
                                          'rebased work pass --base REV naming the commit your change starts from')
            raise core.ProtocolError('git_error', 'Base commit is missing or not an ancestor of HEAD') from None
        if core.has_gitlink(directory, head, base):
            errors.append('Submodule/gitlink evidence is unsupported; no submodule commands were run')
        paths = set(core.implementation_paths(directory, base, head))
        # Index, working tree and untracked files: everything a later commit could contain.
        for args in (DIFF + ('--cached', base), DIFF + (base,), ('ls-files', '-z', '--others', '--exclude-standard')):
            paths.update(path for path in core.git_read(directory, *args).split('\0') if path)
        result['changed_paths'] = sorted(core.safe_text(path, 500) for path in paths)
        result['violations'] = sorted(core.scope_violations(task['scope'], paths), key=lambda item: item['path'])
    except core.ProtocolError as exc:
        errors.append(str(exc))
    result['within_scope'] = not errors and not result['violations']
    return result


def _base(base):
    if not isinstance(base, str) or not re.fullmatch('[0-9a-f]{40}', base):
        raise core.ProtocolError('invalid_base', 'Base must be a full lowercase 40-character commit SHA')
    return base


def resolve_base(directory, rev):
    """Resolve an exact base with the hardened Git reader; no short names, so Git's name preferences never apply."""
    if not isinstance(rev, str) or not rev or rev.startswith('-') or len(rev) > 256 or any(
            char.isspace() or not char.isprintable() for char in rev):
        raise core.ProtocolError('invalid_base', 'Base must be a full SHA, HEAD or refs/... name; it cannot be blank, '
                                 'start with "-" or contain spaces or control characters')
    match = REVISION.fullmatch(rev)
    if not match:
        raise core.ProtocolError('invalid_base', 'Base must be a full 40-character SHA, HEAD or a full ref name such as '
                                 'refs/heads/NAME or refs/tags/NAME, optionally followed by ~N or ^N; convert an '
                                 'abbreviated SHA with git rev-parse ABBREV')
    name = match['name']
    try:
        # Capture the object ID first; the suffix then applies to it, never to a second name lookup.
        # show-ref --verify is an exact lookup: an unborn HEAD fails instead of falling through to refs/*/HEAD.
        oid = (core.git_read(directory, 'show-ref', '--verify', '--hash', name)
               if name == 'HEAD' or name.startswith('refs/') else name)
        return _base(core.git_read(directory, 'rev-parse', '--verify', '--quiet',
                                   _base(oid) + match['suffix'] + '^{commit}'))
    except core.ProtocolError:
        raise core.ProtocolError('invalid_base', 'Base does not name a commit in this checkout; give a full SHA, HEAD '
                                 'or an existing refs/... name') from None


def evidence_skeleton(task, directory, base):
    """Prefill only facts Git observes; results stay unfilled so the draft cannot validate."""
    if core.validate_contract(task):
        raise core.ProtocolError('invalid_contract', 'Contract does not match its bundled schema')
    core.require_worktree_root(directory)
    core.require_safe_config(directory)
    core.require_plain_index(directory)
    head = core.current_head(directory)
    base = resolve_base(directory, base)
    try:
        core.git_read(directory, 'merge-base', '--is-ancestor', task['source']['commit'], base)
        core.git_read(directory, 'merge-base', '--is-ancestor', base, head)
    except core.ProtocolError:
        raise core.ProtocolError('base_history', 'Base must descend from source.commit and be an ancestor of HEAD') from None
    if core.has_gitlink(directory, head, base):
        raise core.ProtocolError('gitlink', 'Submodule/gitlink evidence is unsupported; no submodule commands were run')
    version = task['schema_version']
    attestation = {'status': 'pending', 'reviewer': '', 'git_head': '', 'contract_sha256': '', 'notes': ''}
    skeleton = {'schema_version': version, 'contract_sha256': core.canonical_hash(task),
                'git_head': head, 'git_tree': core.git_read(directory, 'rev-parse', head + '^{tree}'), 'base_commit': base,
                'worktree_clean': not core.git_read(directory, 'status', '--porcelain', '--untracked-files=all',
                                                    '--ignore-submodules=all'),
                'implementer': '',
                'validations': [{'id': item['id'], 'argv': item['argv'], 'status': None, 'exit_code': None,
                                 'skipped': None, 'output': '', 'started_at': '', 'finished_at': '',
                                 'tool_version': '', 'git_head': '', 'tests_run': None} for item in task['validation']],
                'criteria': [{'id': item['id'], 'status': 'pending', 'evidence': ''} for item in task['behavior_criteria']],
                'independent_review': dict(attestation, reviewed_at='') if version == '0.2' else attestation,
                'artifacts': []}
    if version == '0.1':
        skeleton['human_signoff'] = dict(attestation)
    return skeleton


def require_outside_checkout(directory, output):
    """An untracked evidence file inside the checkout would itself invalidate the evidence."""
    # --show-cdup emits only '../' components, so stripped Git output cannot alter the root path.
    root = (Path(directory).resolve() / core.git_read(directory, 'rev-parse', '--show-cdup')).resolve()
    target = Path(output).parent.resolve() / Path(output).name
    if target == root or target.is_relative_to(root):
        raise core.ProtocolError('output_in_checkout', 'Write evidence outside the checkout it describes')
