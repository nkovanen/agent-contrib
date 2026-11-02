"""Offline local-checkout helpers. No GitHub reads, no argv execution, never evidence."""
import re
from pathlib import Path

from . import core

DIFF = ('diff', '--no-ext-diff', '--no-textconv', '--ignore-submodules=none', '--no-renames', '--name-only', '-z')


def scope_check(task, directory, base=None):
    errors = core.validate_contract(task)
    result = {'within_scope': False, 'base_commit': None, 'changed_paths': [], 'violations': [], 'errors': errors,
              'evidence': 'A pass is not evidence and is never recorded as such; verify remains authoritative.'}
    if errors:
        return result
    try:
        core.require_worktree_root(directory)
        base = result['base_commit'] = _base(task['source']['commit'] if base is None else base)
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


def _base(base):
    if not isinstance(base, str) or not re.fullmatch('[0-9a-f]{40}', base):
        raise core.ProtocolError('invalid_base', 'Base must be a full lowercase 40-character commit SHA')
    return base


def evidence_skeleton(task, directory, base):
    """Prefill only facts Git observes; results stay unfilled so the draft cannot validate."""
    if core.validate_contract(task):
        raise core.ProtocolError('invalid_contract', 'Contract does not match its bundled schema')
    base = _base(base)
    core.require_worktree_root(directory)
    try:
        core.git_read(directory, 'merge-base', '--is-ancestor', task['source']['commit'], base)
        core.git_read(directory, 'merge-base', '--is-ancestor', base, 'HEAD')
    except core.ProtocolError:
        raise core.ProtocolError('base_history', 'Base must descend from source.commit and be an ancestor of HEAD') from None
    if core.has_gitlink(directory, 'HEAD', base):
        raise core.ProtocolError('gitlink', 'Submodule/gitlink evidence is unsupported; no submodule commands were run')
    version = task['schema_version']
    attestation = {'status': 'pending', 'reviewer': '', 'git_head': '', 'contract_sha256': '', 'notes': ''}
    skeleton = {'schema_version': version, 'contract_sha256': core.canonical_hash(task),
                'git_head': core.git_read(directory, 'rev-parse', 'HEAD'),
                'git_tree': core.git_read(directory, 'rev-parse', 'HEAD^{tree}'), 'base_commit': base,
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
