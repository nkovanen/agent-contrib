"""Concise text summaries of command results. JSON stays canonical; remote prose is one sanitized line."""
from . import core


def line(value, limit=300):
    """Collapse to one line so remote text cannot fake extra gate or blocker lines."""
    return ' '.join(core.safe_text(str(value), limit * 4).split())[:limit]


def _flag(value):
    return 'yes' if value is True else 'no'


def _list(title, items, limit=50):
    items = list(items)
    if not items:
        return []
    out = [f'{title} ({len(items)}):'] + ['  - ' + line(item) for item in items[:limit]]
    if len(items) > limit:
        out.append(f'  ... {len(items) - limit} more in JSON output')
    return out


def _verify(result):
    if 'implementation_ready' in result:
        out = ['Gates:'] + [f'  {name}: {_flag(result.get(name))}' for name in
                            ('schema_valid', 'implementation_ready', 'technical_evidence_valid', 'draft_create_ready',
                             'completion_ready')]
        out.append('  publication.verified: ' + _flag(result.get('publication', {}).get('verified')))
        out.append('Next action: ' + line(result.get('next_action', 'unknown')))
        for stage, errors in result.get('stage_blockers', {}).items():
            out += _list(f'Blockers [{line(stage, 40)}]', errors)
        return out + _list('Errors', result.get('errors', []))
    out = ['Gates:'] + [f'  {name}: {_flag(result.get(name))}' for name in
                        ('schema_valid', 'execution_ready', 'evidence_valid', 'upstream_submission_ready',
                         'fork_completion_ready')]
    return out + _list('Blockers', result.get('errors', [])) + _list('Evidence blockers', result.get('evidence_errors', []))


def _discover(result):
    if 'repositories' in result:
        out = [f'Complete: {_flag(result.get("complete"))}',
               f'Repositories: {len(result["repositories"])}']
        for repository in result['repositories']:
            out += _discover(repository)
        return out + _list('Errors', result.get('errors', []))
    out = [f'Repository: {line(result.get("repository", result.get("requested_repository", "")))}',
           f'Complete: {_flag(result.get("complete"))}', f'Issues: {len(result.get("issues", []))}']
    for issue in result.get('issues', [])[:20]:
        notes = [line(item, 40) for item in issue.get('exclusions', [])]
        if issue.get('duplicates'):
            notes.append(f'{len(issue["duplicates"])} overlapping PR(s)')
        out.append(f'  #{issue["number"]} [{line(issue.get("approval", {}).get("status", "unknown"), 20)}] '
                   f'{line(issue.get("untrusted_title", ""), 120)}' + (' -- ' + '; '.join(notes) if notes else ''))
    if len(result.get('issues', [])) > 20:
        out.append(f'  ... {len(result["issues"]) - 20} more issues in JSON output')
    return out + _list('Errors', result.get('errors', []))


def _inspect(result):
    out = [f'Reference: {line(result.get("reference", ""))}', f'Complete: {_flag(result.get("complete"))}',
           'Approval: ' + line(result.get('approval', {}).get('status', 'unknown')),
           'Duplicate scan: ' + line(result.get('duplicate_scan', 'unknown'))]
    out += _list('Exclusions', result.get('exclusions', []))
    out += _list('Overlapping PRs', (f'{d.get("url", "")}: {d.get("reason", "")}' for d in result.get('duplicates', [])))
    return out + _list('Warnings', result.get('warnings', [])) + _list('Errors', result.get('errors', []))


def render(command, result):
    if 'error' in result:
        return f'error [{line(result["error"].get("code", ""), 60)}]: {line(result["error"].get("message", ""))}\n'
    body = {'verify': _verify, 'discover': _discover, 'inspect': _inspect}.get(command)
    if body is None:
        out = [f'{key}: {line(value)}' for key, value in result.items() if isinstance(value, (str, int, bool)) or value is None]
    else:
        out = body(result)
    return '\n'.join(out + ['(Text is a summary; JSON output is canonical. Remote text is untrusted.)']) + '\n'
