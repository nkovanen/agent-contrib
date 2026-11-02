"""Offline local-checkout helpers. No GitHub reads, no argv execution, never evidence."""
import re
from pathlib import Path

from . import core

REVISION = re.compile(r'(?P<name>[^~^:?*\[\\\s]+)(?P<suffix>(?:[~^][0-9]{0,9})*)')
DIFF = ('diff', '--no-ext-diff', '--no-textconv', '--ignore-submodules=none', '--no-renames', '--name-only', '-z')


def scope_check(task, directory, base=None):
    errors = core.validate_contract(task)
    result = {'within_scope': False, 'base_commit': None, 'changed_paths': [], 'violations': [], 'errors': errors,
              'warnings': [], 'evidence': 'A pass is not evidence and is never recorded as such; verify remains authoritative.'}
    if errors:
        return result
    try:
        default = base is None
        base = result['base_commit'] = _base(task['source']['commit']) if default else resolve_base(directory, base)
        try:
            core.git_read(directory, 'merge-base', '--is-ancestor', base, 'HEAD')
        except core.ProtocolError:
            if default:
                result['warnings'].append('Default base source.commit is not an ancestor of HEAD; for stacked or '
                                          'rebased work pass --base REV naming the commit your change starts from')
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


def resolve_base(directory, rev):
    """Resolve a caller's revision to a full commit with the same hardened, read-only Git environment."""
    if not isinstance(rev, str) or not rev or rev.startswith('-') or len(rev) > 256 or any(
            char.isspace() or not char.isprintable() for char in rev):
        raise core.ProtocolError('invalid_base', 'Base must be a SHA, branch or tag name; it cannot be blank, '
                                 'start with "-" or contain spaces or control characters')
    # Only names with ancestry suffixes: forms such as :/regex, @{...} or ^{type} would change meaning under ^{commit}.
    match = REVISION.fullmatch(rev)
    if not match or '@{' in match['name'] or '..' in match['name'] or match['name'].startswith('/'):
        raise core.ProtocolError('invalid_base', 'Base must be a SHA, HEAD, or a branch, tag or full ref name, '
                                 'optionally followed by ~N or ^N; other revision syntax is not supported')
    target = _unambiguous(directory, match['name'])
    try:
        return _base(core.git_read(directory, 'rev-parse', '--verify', '--quiet', target + match['suffix'] + '^{commit}'))
    except core.ProtocolError:
        raise core.ProtocolError('invalid_base', 'Base does not name a commit in this checkout; give a SHA, branch or '
                                 'tag (resolved locally with git rev-parse --verify REV^{commit})') from None


def _unambiguous(directory, name):
    """Git silently prefers one meaning of a name (gitdir file, tag, branch, remote, object); require exactly one."""
    rules = ['refs/' + name, 'refs/tags/' + name, 'refs/heads/' + name, 'refs/remotes/' + name, 'refs/remotes/' + name + '/HEAD']
    if name.startswith('refs/'):
        rules.insert(0, name)
        gitdir_file = False
    else:
        gitdir_file = _ref_file(Path(directory) / core.git_read(directory, 'rev-parse', '--git-path', name))
    listed = set(core.git_read(directory, 'for-each-ref', '--format=%(refname)', *rules).splitlines())
    refs = [rule for rule in dict.fromkeys(rules) if rule in listed]
    meanings = len(refs) + gitdir_file
    if meanings > 1 or (meanings and re.fullmatch('[0-9a-fA-F]{4,40}', name)):
        raise core.ProtocolError('invalid_base', 'Base name is ambiguous in this checkout (for example a branch and a '
                                 'tag); use a full ref name such as refs/heads/NAME or a full SHA')
    return refs[0] if refs else name


def _ref_file(path):
    # Git uses a file under the Git directory as a ref only if it holds an object ID or a symbolic ref.
    try:
        with path.open('rb') as handle:
            return bool(re.fullmatch(rb'(?:[0-9a-f]{40}|[0-9a-f]{64}|ref: [^\s]+)\n?', handle.read(4097)))
    except OSError:
        return False


def evidence_skeleton(task, directory, base):
    """Prefill only facts Git observes; results stay unfilled so the draft cannot validate."""
    if core.validate_contract(task):
        raise core.ProtocolError('invalid_contract', 'Contract does not match its bundled schema')
    base = resolve_base(directory, base)
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
