"""Offline local-checkout helpers. No GitHub reads, no argv execution, never evidence."""
import re
from pathlib import Path

from . import core

REVISION = re.compile(r'(?P<name>[0-9a-f]{40}|HEAD|refs/[^~^:?*\[\\\s]+)(?P<suffix>(?:[~^][0-9]{0,9})*)')
# --ignore-submodules=all: Git never starts a command inside a submodule with that submodule's own config.
DIFF = ('diff', '--no-ext-diff', '--no-textconv', '--ignore-submodules=all', '--no-renames', '--name-only', '-z')


def scope_check(task, directory, base=None):
    errors = core.validate_contract(task)
    result = {'within_scope': False, 'base_commit': None, 'changed_paths': [], 'violations': [], 'errors': errors,
              'warnings': [], 'evidence': 'A pass is not evidence and is never recorded as such; verify remains authoritative.'}
    if errors:
        return result
    try:
        head = core.open_checkout(directory)
        default = base is None
        base = result['base_commit'] = _base(task['source']['commit']) if default else _resolve(directory, base)
        try:
            core.git_read(directory, 'merge-base', '--is-ancestor', base, head)
        except core.ProtocolError:
            if default:
                result['warnings'].append('Default base source.commit is not an ancestor of HEAD; for stacked or '
                                          'rebased work pass --base REV naming the commit your change starts from')
            raise core.shallow_or(directory, core.ProtocolError(
                'git_error', 'Base commit is missing or not an ancestor of HEAD')) from None
        if core.has_gitlink(directory, head, base):  # stop before any index or worktree diff
            raise core.ProtocolError('gitlink', 'Submodule/gitlink evidence is unsupported; no submodule commands were run')
        committed = set(core.implementation_paths(directory, base, head))
        # Index, working tree and untracked files: everything a later commit could contain.
        # The index itself is the subject only for staged changes; worktree content is judged without its stat cache.
        staged = {path for path in core.git_read(directory, *DIFF, '--cached', base).split('\0') if path}
        untracked = core.untracked_paths(directory)
        if any(path.endswith('/') for path in untracked):  # an untracked nested repository: a future gitlink (FR2-03)
            raise core.ProtocolError('gitlink', 'Submodule/gitlink evidence is unsupported; no submodule commands were run')
        working = core.worktree_changes(directory, base) | untracked
        paths = committed | staged | working
        result['changed_paths'] = sorted(core.safe_text(path, 500) for path in paths)
        # G-08: each symlink is also judged by its resolved target, in the snapshot that holds it.
        links = (core.link_violations(task['scope'], committed, core.LinkView(directory, head)) +
                 core.link_violations(task['scope'], staged, core.LinkView(directory, index=True)) +
                 # Every changed path: a path committed since the base is not in worktree_changes (review SL-03).
                 core.link_violations(task['scope'], paths, core.LinkView(directory, worktree=True)))
        # An untracked .gitattributes changes how Git compares files, so it is never within scope (FR2-01).
        attributes = [{'path': core.safe_text(path, 500), 'rule': 'untracked .gitattributes changes how files are '
                       'compared; commit or remove it'} for path in sorted(core.untracked_git_behaviour_files(directory))
                      if path.rsplit('/', 1)[-1] == '.gitattributes']
        result['violations'] = sorted(core.scope_violations(task['scope'], paths) + attributes +
                                      list({(item['path'], item['rule']): item for item in links}.values()),
                                      key=lambda item: (item['path'], item['rule']))
        if default and result['violations']:
            # Report only: several commits plus violations often mean work stacked on unpublished commits.
            behind = int(core.git_read(directory, 'rev-list', '--count', base + '..' + head))
            if behind > 1:
                result['warnings'].append(
                    f'Default base source.commit {base} is {behind} commits behind HEAD and paths outside the scope '
                    'changed; if your change is stacked on other unpublished commits, pass --base naming the commit '
                    'it starts from (for example HEAD~1)')
    except core.ProtocolError as exc:
        errors.append(str(exc))
    result['within_scope'] = not errors and not result['violations']
    return result


def _base(base):
    if not isinstance(base, str) or not core.SHA.fullmatch(base):
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


def _resolve(directory, rev):
    """A well-formed base that does not resolve in a shallow clone is reported as missing history."""
    try:
        return resolve_base(directory, rev)
    except core.ProtocolError as exc:
        if isinstance(rev, str) and REVISION.fullmatch(rev):
            raise core.shallow_or(directory, exc) from None
        raise


def evidence_skeleton(task, directory, base):
    """Prefill only facts Git observes; results stay unfilled so the draft cannot validate."""
    if core.validate_contract(task):
        raise core.ProtocolError('invalid_contract', 'Contract does not match its bundled schema')
    head = core.open_checkout(directory)
    base = _resolve(directory, base)
    try:
        core.git_read(directory, 'merge-base', '--is-ancestor', task['source']['commit'], base)
        core.git_read(directory, 'merge-base', '--is-ancestor', base, head)
    except core.ProtocolError:
        raise core.shallow_or(directory, core.ProtocolError(
            'base_history', 'Base must descend from source.commit and be an ancestor of HEAD')) from None
    if core.has_gitlink(directory, head, base):
        raise core.ProtocolError('gitlink', 'Submodule/gitlink evidence is unsupported; no submodule commands were run')
    version = task['schema_version']
    attestation = {'status': 'pending', 'reviewer': '', 'git_head': '', 'contract_sha256': '', 'notes': ''}
    skeleton = {'schema_version': version, 'contract_sha256': core.canonical_hash(task),
                'git_head': head, 'git_tree': core.git_read(directory, 'rev-parse', head + '^{tree}'), 'base_commit': base,
                'worktree_clean': not core.worktree_dirty(directory, head),
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


MAX_LOCAL_COMMITS = 500
MAX_COMMIT_BYTES = 65536
MAX_LOCAL_BYTES = 4 * 1024 * 1024
LOCAL_NOTICE = ('Report only. Issues referenced (#N or owner/repo#N for the source repository) by commits reachable '
                'from the checkout HEAD but not from the source default-branch commit. A reference is not proof that '
                'the work is done, and no reference is not proof that it is not.')


def local_issue_references(directory, repository, base):
    """F12: unpublished local work that may already implement an issue. Hardened reads only; nothing is fetched."""
    report = {'complete': False, 'head': None, 'base': base, 'commits_scanned': 0, 'commit_limit': MAX_LOCAL_COMMITS,
              'issues': [], 'errors': [], 'notice': LOCAL_NOTICE}
    try:
        core.require_worktree_root(directory)
        core.require_safe_config(directory)
        head = report['head'] = core.current_head(directory)
        try:
            core.git_read(directory, 'cat-file', '-e', _base(base) + '^{commit}')
        except core.ProtocolError:
            raise core.ProtocolError('missing_base', f'Source default-branch commit {base} is not in this checkout; '
                                     'fetch it with your own tools (the CLI never fetches)') from None
        if core.git_read(directory, 'rev-parse', '--is-shallow-repository') != 'false':
            # A shallow boundary can hide intermediate commits while git log still succeeds (review R11-02).
            raise core.ProtocolError('shallow_checkout', 'Checkout is shallow, so local history may be missing; '
                                     'deepen it with your own tools (git fetch --unshallow) and retry')
        commits = core.git_read(directory, 'rev-list', f'--max-count={MAX_LOCAL_COMMITS + 1}', head, '^' + base).split()
        if len(commits) > MAX_LOCAL_COMMITS:
            report['errors'].append(f'More than {MAX_LOCAL_COMMITS} local commits after the source default branch; '
                                    f'only the newest {MAX_LOCAL_COMMITS} were read')
            commits = commits[:MAX_LOCAL_COMMITS]
        # Bound bytes before any message is read: object sizes first, then only commits within both limits.
        sizes = core.git_read(directory, 'cat-file', '--batch-check=%(objectname) %(objectsize)',
                              input=''.join(sha + '\n' for sha in commits)).split('\n') if commits else []
        readable, total = [], 0
        for record in sizes:
            sha, _, size = record.partition(' ')
            if not core.SHA.fullmatch(sha) or not size.isdigit():
                raise core.ProtocolError('git_error', 'Unexpected git cat-file output')
            if int(size) > MAX_COMMIT_BYTES:
                report['errors'].append(f'Commit {sha} is larger than {MAX_COMMIT_BYTES} bytes; its message was not read')
            elif total + int(size) > MAX_LOCAL_BYTES:
                report['errors'].append(f'Local commit messages exceed {MAX_LOCAL_BYTES} bytes in total; only the newest '
                                        'commits within that bound were read')
                break
            else:
                readable.append(sha)
                total += int(size)
        entries = []
        for sha, message in _raw_messages(directory, readable):
            if b'\0' in message:  # %B would stop at the NUL and silently drop later references (review R11-03)
                report['errors'].append(f'Commit {sha} has a NUL byte in its message; it was not read')
            else:
                entries.append((sha, message.decode('utf-8', errors='surrogateescape')))
        referenced = {}
        for sha, message in entries:
            for number in _issue_refs(message, repository):  # whole message: never a cut token
                commits = referenced.setdefault(number, [])
                if sha not in commits and len(commits) < 10:
                    commits.append(sha)
        report.update(commits_scanned=len(entries),
                      issues=[{'number': number, 'commits': commits} for number, commits in sorted(referenced.items())])
    except core.ProtocolError as exc:
        report['errors'].append(str(exc))
    report['complete'] = not report['errors']
    return report


def _raw_messages(directory, shas):
    """Raw commit objects (already size-bounded) through cat-file --batch; yields (sha, message bytes)."""
    if not shas:
        return
    raw = core.git_read(directory, 'cat-file', '--batch', raw=True, input=b''.join(sha.encode() + b'\n' for sha in shas))
    position = 0
    for expected in shas:
        end = raw.find(b'\n', position)
        header = raw[position:end].decode('ascii', errors='replace').split(' ')
        if end < 0 or len(header) != 3 or header[0] != expected or header[1] != 'commit' or not header[2].isdigit():
            raise core.ProtocolError('git_error', 'Unexpected git cat-file output')
        body = raw[end + 1:end + 1 + int(header[2])]
        position = end + 1 + int(header[2]) + 1
        if len(body) != int(header[2]):
            raise core.ProtocolError('git_error', 'Unexpected git cat-file output')
        yield expected, body.partition(b'\n\n')[2]


def _issue_refs(text, repository):
    qualified = re.compile(r'(?<![A-Za-z0-9_.\-/])([A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99})#([1-9][0-9]{0,9})(?![0-9A-Za-z_])')
    numbers = {int(number) for name, number in qualified.findall(text) if name.casefold() == repository.casefold()}
    bare = qualified.sub('', text)
    numbers.update(int(n) for n in re.findall(r'(?<![A-Za-z0-9_/#&])#([1-9][0-9]{0,9})(?![0-9A-Za-z_])', bare))
    return numbers
