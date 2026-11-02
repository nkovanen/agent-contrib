"""Opt-in, report-only commit-signature observations (#18, part). Never verifies a signature, never affects readiness.

No signature program is ever run: no gpg, ssh-keygen, verify-commit or log --show-signature, all of which honour
repository-configured programs. Local reads are plumbing (merge-base, rev-list, cat-file) through core.git_read.
"""
import datetime as dt
from urllib.parse import quote

from . import core, remote

MAX_COMMITS = 1000
SIGNATURE_HEADERS = (b'gpgsig ', b'gpgsig-sha256 ')
# GitHub's documented commit verification reasons; anything else is reported as unrecognized, never echoed.
REASONS = {'valid', 'unsigned', 'unknown_key', 'bad_email', 'unverified_email', 'no_user', 'expired_key',
           'not_signing_key', 'unknown_signature_type', 'malformed_signature', 'invalid', 'gpgverify_error',
           'gpgverify_unavailable', 'bad_cert', 'ocsp_pending'}
NOTICE = ('Observation only, not approval: it changes no gate or exit status. GitHub "verified" means a signature '
          'matched a key registered to a GitHub account; it does not show who wrote, tested, reviewed or approved the '
          'work. Ruleset bypass actors and classic branch protection are not visible.')
LOCAL_NOTICE = ('Header presence only. Nothing is verified locally, and any commit can carry a forged signature '
                'header.')


def _timestamp(value):
    try:
        parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (AttributeError, TypeError, ValueError):
        return False
    return parsed.tzinfo is not None


def github_verification(client, target, head):
    part = {'complete': False, 'verified': None, 'reason': None, 'verified_at': None, 'errors': [],
            'verified_means': 'GitHub matched the signature to a key registered to an account; not approval, '
                              'authorship, review or test execution'}
    try:
        data = core.require(client.request(f'repos/{target}/git/commits/{head}'), dict, 'commit')
        if remote.sha(data.get('sha'), 'commit sha') != head:
            remote.bad('commit (different commit returned)')
        details = core.require(data.get('verification'), dict, 'commit verification')
        verified = remote.flag(details.get('verified'), 'verification flag')
        reason = remote.text(details.get('reason'), 'verification reason')
        verified_at = remote.text(details.get('verified_at'), 'verification time', nullable=True)
        if verified_at is not None and not _timestamp(verified_at):
            remote.bad('verification time')
        if verified != (reason == 'valid'):  # GitHub reports verified exactly when the reason is valid
            remote.bad('verification flag and reason')
    except core.ProtocolError as exc:
        hint = ' (a head that is not pushed to the target yet cannot be observed)' if exc.code != 'api_shape' else ''
        part['errors'] = [str(exc) + hint]
        return part
    part.update(complete=True, verified=verified, reason=reason if reason in REASONS else 'unrecognized',
                verified_at=verified_at)
    return part


def required_signatures(client, target, branch):
    part = {'complete': False, 'branch': core.safe_text(branch, 200), 'required': None, 'ruleset_ids': None,
            'classic_branch_protection': 'not_observed', 'errors': []}
    listing = core.paginate(client, f'repos/{target}/rules/branches/{quote(branch, safe="")}',
                            key=lambda rule: f"{rule.get('type')}\0{rule.get('ruleset_id')}")
    errors = list(listing['errors'])
    ids = []
    try:
        for rule in listing['items']:
            kind = remote.text(rule.get('type'), 'rule type')
            identity = remote.positive(rule.get('ruleset_id'), 'ruleset ID')
            if kind == 'required_signatures':
                ids.append(identity)
    except core.ProtocolError as exc:
        errors.append(str(exc))
    if errors:  # paginate reports every incomplete read as an error
        part['errors'] = errors
        return part
    part.update(complete=True, required=bool(ids), ruleset_ids=sorted(set(ids)))
    return part


def local_commits(directory, base, head):
    part = {'complete': False, 'commits': None, 'with_header': None, 'without_header': None, 'limit': MAX_COMMITS,
            'errors': [], 'notice': LOCAL_NOTICE}
    try:
        if not isinstance(base, str) or not core.SHA.fullmatch(base):
            raise core.ProtocolError('evidence', 'Evidence base_commit is not a full commit SHA')
        if core.git_read(directory, 'merge-base', base, head) != base:
            raise core.ProtocolError('evidence', 'Evidence base_commit is not an ancestor of git_head')
        listed = core.git_read(directory, 'rev-list', '--reverse', '--max-count', str(MAX_COMMITS + 1),
                               base + '..' + head).split()
        if len(listed) > MAX_COMMITS:
            raise core.ProtocolError('limit', f'More than {MAX_COMMITS} commits in base_commit..git_head; not observed')
        commits = []
        for sha in listed:
            if not core.SHA.fullmatch(sha):
                raise core.ProtocolError('git_error', 'Git listed an invalid commit ID')
            # Raw bytes with literal LF structure: headers end at the first empty line, and continuation lines
            # (leading space) never start with a header name. No decoding and no CR conversion.
            headers = core.git_read(directory, 'cat-file', 'commit', sha, raw=True).split(b'\n\n', 1)[0].split(b'\n')
            present = any(line.startswith(SIGNATURE_HEADERS) for line in headers)
            commits.append({'sha': sha, 'signature_header': 'present' if present else 'absent'})
    except core.ProtocolError as exc:
        part['errors'] = [str(exc)]
        return part
    signed = sum(commit['signature_header'] == 'present' for commit in commits)
    part.update(complete=True, commits=commits, with_header=signed, without_header=len(commits) - signed)
    return part


def observe(task, evidence, repo_dir=None, client=None):
    execution = task.get('execution') or {}
    target = execution.get('target_repository') or task['source']['repository']
    branch = execution.get('base_ref') or task['source']['default_branch']
    result = {'repository': target, 'head_sha': None, 'complete': False, 'github_verification': None,
              'required_signatures': None, 'local_commits': {'status': 'not_requested'}, 'errors': [],
              'notice': NOTICE}
    head = evidence.get('git_head') if isinstance(evidence, dict) else None
    if not isinstance(head, str) or not core.SHA.fullmatch(head):
        result['errors'].append('No valid evidence git_head to observe')
        return result
    try:
        core.parse_repository(target)
    except core.ProtocolError as exc:
        result['errors'].append(str(exc))
        return result
    result['head_sha'] = head
    client = client or core.GitHub()
    parts = {'github_verification': github_verification(client, target, head),
             'required_signatures': required_signatures(client, target, branch)}
    if repo_dir is not None:
        parts['local_commits'] = local_commits(repo_dir, evidence.get('base_commit'), head)
    result.update(parts)
    result['errors'] = [f'{name}: {error}' for name, part in parts.items() for error in part['errors']]
    result['complete'] = all(part['complete'] for part in parts.values())
    return result
