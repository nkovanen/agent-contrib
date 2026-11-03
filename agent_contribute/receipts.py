"""Public PR snapshots and offline impact. Observations never establish authority."""
import datetime as dt
import importlib.resources
import json
import os
from pathlib import Path
import re
import stat

from . import core, remote

MAX_FILES = 100
MAX_BYTES = 64 * 1024
NOTICE = ('Editable recorded observations, not signed proof or authenticated contributions. '
          'No claim about agent involvement, tests, quality, consent or permission. '
          'Counts describe only the supplied snapshots, not current GitHub state.')
REFRESH = 'Run tipjar receipt for this PR with a new output path; snapshots never refresh automatically.'
TIME = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z')


def _require(condition, message):
    if not condition:
        raise core.ProtocolError('invalid_receipt', message)


def _timestamp(value):
    _require(isinstance(value, str) and TIME.fullmatch(value), 'Expected a UTC timestamp with known precision')
    try:
        return dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise core.ProtocolError('invalid_receipt', 'Invalid calendar timestamp') from exc


def _schema():
    return json.loads(importlib.resources.files('agent_contribute').joinpath('receipt.schema.json').read_text('utf-8'))


def validate(receipt, *, now=None):
    """Closed shape plus relational facts; the same rules apply to live and offline data."""
    _require(not core.schema_errors(receipt, _schema()), 'Unsupported or malformed receipt schema')
    observed = _timestamp(receipt['observed_at'])
    _require(observed <= (now or dt.datetime.now(dt.timezone.utc)), 'Observation timestamp is in the future')
    repository, pr = receipt['repository']['full_name'], receipt['pull_request']
    _require(pr['number'] <= 9999999999, 'Pull request number exceeds the reference bound')
    _require(pr['url'] == f"https://github.com/{repository}/pull/{pr['number']}", 'Noncanonical pull request URL')
    endpoints = [f'repos/{repository}', f"repos/{repository}/pulls/{pr['number']}"]
    _require(receipt['provenance']['endpoints'] == endpoints, 'Mismatching snapshot provenance')
    for side in ('head', 'base'):
        ref = pr[side]['ref']
        _require(ref == core.safe_text(ref) and not any(c.isspace() for c in ref), 'Unsafe or malformed branch ref')
    merge = pr['merge']
    merged = merge['merged']
    expected = 'merged' if merged else 'closed' if merge['closed_at'] else 'draft' if pr['draft'] else 'open'
    _require(pr['state'] == expected, 'Inconsistent pull request state')
    _require((merge['merged_at'] is not None) == merged, 'Inconsistent merge timestamp')
    _require((merge['merged_by'] is not None) == merged, 'Inconsistent merge actor')
    if merged:
        _require(not pr['draft'], 'A merged pull request cannot be a draft')
        _require(merge['closed_at'] is not None and merge['commit_sha'] is not None, 'Missing merge facts')
    for key in ('merged_at', 'closed_at'):
        if merge[key] is not None:
            _require(_timestamp(merge[key]) <= observed, 'Event timestamp is after observation')
    if merged:
        _require(_timestamp(merge['merged_at']) <= _timestamp(merge['closed_at']), 'Merge occurs after closure')
    return observed


def _author(value):
    value = core.require(value, dict, 'PR author')
    return {key: value.get(key) for key in ('id', 'login', 'type')}


def observe(reference, client=None):
    """Two fixed bounded GETs. A missing fact raises before any local save."""
    repository, number = core.parse_issue(reference)
    client = client or core.GitHub()
    metadata = core.require(client.request(f'repos/{repository}'), dict, 'repository')
    name, rid = remote.repository(metadata, 'repository')
    _require(name == repository, 'Use the exact canonical repository name')
    _require(metadata.get('private') is False and metadata.get('visibility') == 'public',
             'Receipts support only repositories explicitly observed public')
    pr = core.require(client.request(f'repos/{repository}/pulls/{number}'), dict, 'pull request')
    _require(remote.positive(pr.get('number'), 'pull request number') == number, 'Pull request number mismatch')
    base = core.require(pr.get('base'), dict, 'pull request base')
    _require(remote.repository(base.get('repo'), 'base repository') == (name, rid), 'Base repository identity mismatch')
    _require(base['repo'].get('private') is False and base['repo'].get('visibility') == 'public',
             'PR base repository is not explicitly public')
    head = core.require(pr.get('head'), dict, 'pull request head')
    state = remote.choice(pr.get('state'), {'open', 'closed'}, 'pull request state')
    draft = remote.flag(pr.get('draft'), 'draft flag')
    merged = remote.flag(pr.get('merged'), 'merged flag')
    _require(not merged or state == 'closed', 'Merged pull request is not closed')
    _require(all(key in pr for key in ('merged_at', 'closed_at', 'merge_commit_sha', 'merged_by')), 'Missing merge facts')
    _require((pr['closed_at'] is not None) == (state == 'closed'), 'Closure does not match live state')
    receipt = {'schema_version': '0.1', 'kind': 'tipjar-receipt', 'trust': 'recorded-observation-not-proof',
               'observed_at': dt.datetime.now(dt.timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z'),
               'repository': {'id': rid, 'full_name': name},
               'pull_request': {'id': pr.get('id'), 'number': number, 'url': pr.get('html_url'),
                                'author': _author(pr.get('user')), 'state': 'merged' if merged else
                                'closed' if state == 'closed' else 'draft' if draft else 'open', 'draft': draft,
                                'head': {key: head.get(key) for key in ('sha', 'ref')},
                                'base': {key: base.get(key) for key in ('sha', 'ref')},
                                'merge': {'merged': merged, 'merged_at': pr['merged_at'], 'closed_at': pr['closed_at'],
                                          'commit_sha': pr['merge_commit_sha'], 'merged_by':
                                          _author(pr['merged_by']) if pr['merged_by'] is not None else None}},
               'provenance': {'source': 'github-rest-get', 'endpoints':
                              [f'repos/{repository}', f'repos/{repository}/pulls/{number}'], 'non_atomic': True},
               'refresh': REFRESH}
    validate(receipt)
    return receipt


def _read(path):
    """Refuse symlinks and nonregular files; open directories without following links on POSIX."""
    path = Path(path)
    if not path.is_absolute():
        path = Path.cwd() / path
    descriptor = None
    try:
        nofollow = getattr(os, 'O_NOFOLLOW', 0)
        flags = os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | nofollow
        if os.open in os.supports_dir_fd and nofollow:
            descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
            for part in path.parts[1:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | nofollow, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            leaf = os.open(path.name, flags, dir_fd=descriptor)
        else:
            for part in (*reversed(path.parents), path):
                if stat.S_ISLNK(part.lstat().st_mode):
                    raise OSError('Symlink path')
            before = path.lstat()
            leaf = os.open(path, flags)
            if (before.st_dev, before.st_ino) != (os.fstat(leaf).st_dev, os.fstat(leaf).st_ino):
                os.close(leaf)
                raise OSError('Input changed while opening')
        with os.fdopen(leaf, 'rb') as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
                raise OSError('Input must be a bounded regular file')
            data = handle.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise OSError('Input exceeds size limit')
        return core.strict_json(data.decode('utf-8'))
    except (OSError, UnicodeError) as exc:
        raise core.ProtocolError('receipt_file', 'Cannot read receipt: require a non-symlink UTF-8 regular file '
                                 'of at most 64 KiB') from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def load(path):
    """Load one bounded local receipt and validate it before exposing its data."""
    receipt = _read(path)
    validate(receipt)
    return receipt


def impact(paths):
    """Deduplicate validated editable observations. Invalid input rejects the entire summary."""
    _require(isinstance(paths, (list, tuple)) and 1 <= len(paths) <= MAX_FILES, 'Provide 1–100 receipt files')
    latest, snapshots, repositories, names, identities, routes = {}, {}, {}, {}, {}, {}
    now = dt.datetime.now(dt.timezone.utc)
    for path in paths:
        receipt = _read(path)
        observed = validate(receipt, now=now)
        repo, pr = receipt['repository'], receipt['pull_request']
        rid, pid, name = repo['id'], pr['id'], repo['full_name']
        _require(repositories.setdefault(rid, name) == name and names.setdefault(name.casefold(), rid) == rid,
                 'Conflicting repository identities; refresh consistently after a rename or transfer')
        binding = (rid, pr['number'], pr['author']['id'])
        _require(identities.setdefault(pid, binding) == binding, 'Conflicting pull request identity or author')
        route = (rid, pr['number'])
        _require(routes.setdefault(route, pid) == pid, 'Conflicting pull request IDs for one repository and number')
        key = (rid, pid)
        _require(snapshots.setdefault((*key, observed), receipt) == receipt,
                 'Conflicting snapshots at the same observation time')
        previous = latest.get(key)
        if previous is None or observed > previous[0]:
            latest[key] = (observed, receipt)
    selected = [latest[key][1] for key in sorted(latest)]
    counts = {'open': 0, 'closed': 0, 'merged': 0}
    for receipt in selected:
        state = receipt['pull_request']['state']
        counts['open' if state == 'draft' else state] += 1
    return {'complete': True, 'trust': 'self-reported recorded observations', 'input_files': len(paths),
            'unique_prs': len(selected), 'repositories_represented': len(repositories), 'counts': counts,
            'receipts': selected, 'warning': NOTICE}
