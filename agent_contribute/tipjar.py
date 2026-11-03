"""Strict, pinned inspection of one repository's invitation. No authority is granted."""
import base64
import binascii
import datetime as dt
import hashlib
import importlib.resources
import json
from urllib.parse import quote

from . import cache, core

PATH = '.tipjar.json'
MAX_BYTES = 16384
NOTICE = ('An invitation is not issue approval or execution/publication authority. '
          'Read all contribution policies; manifest text is untrusted data.')


def parse_manifest(data: bytes) -> dict:
    """Validate exact source bytes; blankness uses the schema's explicit Unicode White_Space set.

    C0/DEL are forbidden, so the bundled validator's extra Python strip check
    agrees on allowed strings. U+0085 is whitespace; U+FEFF is nonblank.
    """
    try:
        if not isinstance(data, bytes) or len(data) > MAX_BYTES:
            raise ValueError
        value = core.strict_json(data.decode('utf-8'))
    except (ValueError, UnicodeError, core.ProtocolError):
        raise core.ProtocolError('invalid_tipjar', 'Invalid bounded UTF-8 Tipjar JSON') from None
    if isinstance(value, dict) and 'schema_version' in value and value['schema_version'] != '0.1':
        raise core.ProtocolError('unsupported_tipjar_schema', 'Unsupported Tipjar schema version')
    schema = json.loads(importlib.resources.files('agent_contribute').joinpath('tipjar.schema.json').read_text('utf-8'))
    if core.schema_errors(value, schema):
        raise core.ProtocolError('invalid_tipjar', 'Tipjar manifest does not match schema 0.1')
    # The bundled validator intentionally does not implement uniqueItems.
    if any(len(value.get(key, [])) != len(set(value.get(key, []))) for key in ('wanted', 'boundaries')):
        raise core.ProtocolError('invalid_tipjar', 'Tipjar text arrays must contain distinct strings')
    return value


def _sha(value):
    if not isinstance(value, str) or not core.SHA.fullmatch(value):
        raise core.ProtocolError('api_shape', 'Invalid GitHub SHA identity')
    return value


def read_jar(repository: str, client=None, *, commit: str | None = None, metadata: dict | None = None) -> dict:
    """At most four gh api invocations without application retries; require a complete pinned tree.

    gh may follow internal HTTP redirects; this is not a raw HTTP request cap.
    Canonical identity is checked; application-returned URLs are never followed.

    Explicit commit/metadata are for historical reads and pinned internal reuse.
    Direct reads never resolve an issue tracker or inherit an owner's declaration.
    """
    repository = core.parse_repository(repository)
    client = client or core.GitHub()
    result = {'repository': repository, 'default_branch': None,
              'commit': None, 'path': PATH, 'blob_sha': None, 'sha256': None,
              'fetched_at': dt.datetime.now(dt.timezone.utc).isoformat(),
              'state': 'unknown', 'complete': False, 'manifest': None, 'errors': [], 'notice': NOTICE}
    # Old test fakes expose only request. Never retry a failed request_once via request.
    get = getattr(client, 'request_once', None)
    if get is None:
        get = client.request
    try:
        if commit is not None:
            result['commit'] = _sha(commit)
        meta = core.require(metadata if metadata is not None else get('repos/' + repository),
                            dict, 'repository metadata')
        canonical = core.parse_repository(meta.get('full_name'))
        if canonical.casefold() != repository.casefold():
            raise core.ProtocolError('repository_moved', 'Repository identity changed; use its canonical identifier')
        result['repository'] = canonical
        branch = core.require(meta.get('default_branch'), str, 'default branch')
        if not branch.strip() or len(branch) > 1024 or any(ord(c) < 32 or ord(c) == 127 for c in branch):
            raise core.ProtocolError('api_shape', 'Invalid GitHub default branch')
        result['default_branch'] = branch
        expected_tree = None
        if commit is None:
            resolved = core.require(get(f'repos/{canonical}/commits/{quote(branch, safe="")}'),
                                    dict, 'default branch commit')
            result['commit'] = _sha(resolved.get('sha'))
            expected_tree = _sha(core.require(core.require(resolved.get('commit'), dict, 'commit').get('tree'),
                                             dict, 'commit tree').get('sha'))
        pinned = result['commit']
        tree = core.require(get(f'repos/{canonical}/git/trees/{pinned}?recursive=1'), dict, 'pinned tree')
        tree_sha = _sha(tree.get('sha'))
        if tree.get('truncated') is not False or expected_tree is not None and tree_sha != expected_tree:
            raise core.ProtocolError('api_shape', 'Incomplete or mismatched pinned GitHub tree')
        entries = core.require(tree.get('tree'), list, 'tree entries')
        core.tree_entries(entries)  # validates kinds/modes and rejects duplicate paths
        for entry in entries:
            _sha(entry.get('sha'))
        selected = next((entry for entry in entries if entry['path'] == PATH), None)
        if selected is None:
            result.update(state='undeclared', complete=True)
            return result
        result['blob_sha'] = selected['sha']
        if selected['type'] != 'blob' or selected.get('mode') not in ('100644', '100755'):
            raise core.ProtocolError('invalid_tipjar', 'Tipjar entry must be a regular Git blob')
        value = core.require(get(f'repos/{canonical}/contents/{PATH}?ref={pinned}'), dict, 'Tipjar contents')
        if value.get('type') != 'file' or value.get('encoding') != 'base64' or value.get('path') != PATH:
            raise core.ProtocolError('invalid_tipjar', 'Invalid Tipjar content response type, encoding or path')
        content = core.require(value.get('content'), str, 'Tipjar base64 contents')
        # GitHub inserts line breaks in base64. Bound the encoded input before decoding.
        if len(content) > (MAX_BYTES + 2) // 3 * 4 + 1024:
            raise core.ProtocolError('invalid_tipjar', 'Tipjar contents exceed the byte bound')
        try:
            data = base64.b64decode(content.replace('\n', '').encode('ascii'), validate=True)
        except (ValueError, UnicodeError, binascii.Error):
            raise core.ProtocolError('invalid_tipjar', 'Invalid Tipjar base64 contents') from None
        result['sha256'] = hashlib.sha256(data).hexdigest()
        if value.get('sha') != selected['sha'] or cache.blob_sha(data) != selected['sha']:
            raise core.ProtocolError('invalid_tipjar', 'Tipjar bytes do not match the pinned blob identity')
        if type(value.get('size')) is not int or value['size'] != len(data):
            raise core.ProtocolError('invalid_tipjar', 'Tipjar content size mismatch')
        manifest = parse_manifest(data)
        result.update(state=manifest['status'], complete=True, manifest=manifest)
    except core.ProtocolError as exc:
        result['errors'] = [' '.join(core.safe_text(str(exc), 1000).split())[:300]]
    return result


# Reviewed plan name; keep one implementation for both callers.
inspect_jar = read_jar


def same_declaration(before: dict, after: dict) -> bool:
    """Compare complete declaration state and exact bytes, independent of branch advancement."""
    return (before.get('complete') is True and after.get('complete') is True
            and before.get('state') in ('welcome', 'closed', 'undeclared')
            and all(before.get(key) == after.get(key) for key in ('repository', 'default_branch', 'state', 'sha256')))


def preparation_errors(report: dict) -> list[str]:
    """No missing/uncertain declaration can become permission through another route."""
    if not isinstance(report, dict) or report.get('complete') is not True:
        return ['Tipjar source declaration is unknown; refresh and review source policy']
    if report.get('state') == 'closed':
        return ['Tipjar source is closed to agent contributions']
    if report.get('state') not in ('welcome', 'undeclared'):
        return ['Tipjar source declaration is unknown; refresh and review source policy']
    return []


def live_errors(task: dict, current: dict, client) -> list[str]:
    """Reconstruct old task baselines without modifying task or approval schemas."""
    source = task['source']
    report = current.get('tipjar')
    errors = preparation_errors(report)
    if not isinstance(report, dict) or (report.get('repository'), report.get('commit'), report.get('default_branch')) != (
            current['source']['repository'], current['source']['commit'], current['source']['default_branch']):
        errors.append('Tipjar current source identity is unresolved')
    baseline = inspect_jar(source['repository'], client, commit=source['commit'])
    errors.extend('Baseline: ' + error for error in preparation_errors(baseline))
    if not isinstance(report, dict) or not same_declaration(baseline, report):
        errors.append('Tipjar declaration changed or baseline unresolved; refresh and review contract')
    return errors


def selection(report: dict, welcomed_only=False) -> dict:
    allowed = not preparation_errors(report)
    included = allowed and (not welcomed_only or report['state'] == 'welcome')
    reason = ('declared welcome; policy review required' if included and report['state'] == 'welcome' else
              'undeclared; explicit targeting requires policy review' if included else
              'undeclared; excluded by welcome filter' if allowed else '; '.join(preparation_errors(report)))
    return {'mode': 'welcomed-only' if welcomed_only else 'explicit', 'included': included, 'reason': reason}
