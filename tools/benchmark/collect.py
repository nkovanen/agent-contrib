"""Collect a benchmark snapshot: a repository's issues open at a cutoff T, labelled by their outcome.

    python tools/benchmark/collect.py owner/repo --cutoff 2026-03-01T00:00:00Z --horizon-days 90 \\
        --output tools/benchmark/data/owner__repo__2026-03-01.json [--bodies-out /outside/checkout/bodies.json]

Read-only: every request is a fixed `gh api --method GET` through agent_contribute.core.GitHub.
Reads are bounded: repository metadata, one commit and one tree read, at most --max-search-pages
pages per search query (four queries), one timeline (at most 5 pages) per kept issue, and one
events read (at most 2 pages) per PR whose title can create an overlap, to confirm it was open at T.
Refuses to run before the horizon has ended."""
import argparse
import datetime as dt
import json
import pathlib
import sys
import time
from urllib.parse import quote

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from agent_contribute import core  # noqa: E402
import benchlib  # noqa: E402

SEARCH_PAUSE = 2.2  # the search API allows 30 requests per minute


class Counting:
    def __init__(self, client):
        self.client, self.reads, self.searches = client, 0, 0

    def request(self, endpoint):
        if endpoint.startswith('search/'):
            if self.searches:
                time.sleep(SEARCH_PAUSE)
            self.searches += 1
        self.reads += 1
        return self.client.request(endpoint)


def search(client, query, max_pages, notes):
    items = []
    for page in range(1, max_pages + 1):
        data = core.require(client.request(f'search/issues?q={quote(query, safe="")}&sort=created&order=asc'
                                           f'&per_page=100&page={page}'), dict, 'search result')
        batch = core.require(data.get('items'), list, 'search items')
        items.extend(batch)
        if data.get('incomplete_results') is not False:
            notes.append(f'Search reported incomplete results: {query}')
        if len(batch) < 100:
            return items
    notes.append(f'Search capped at {max_pages} pages: {query}')
    return items


def timeline(client, repository, number, notes):
    events = []
    for page in range(1, 6):
        batch = core.require(client.request(f'repos/{repository}/issues/{number}/timeline?per_page=100&page={page}'),
                             list, 'timeline page')
        events.extend(batch)
        if len(batch) < 100:
            return events
    notes.append(f'Timeline of #{number} exceeds 5 pages; issue excluded')
    return None


def pr_events(client, repository, number):
    events = []
    for page in range(1, 3):
        batch = core.require(client.request(f'repos/{repository}/issues/{number}/events?per_page=100&page={page}'),
                             list, 'issue events page')
        events.extend(batch)
        if len(batch) < 100:
            return events
    return None


def overlapping_prs(repository, issues, prs):
    """PR numbers whose title (as the replay will see it) overlaps some kept issue's title."""
    index = core.index_prs([{'number': pr['number'], 'title': pr['title'], 'html_url': pr['html_url'],
                             'body': None, 'head': None} for pr in prs])
    found = set()
    for issue in issues:
        found.update(item['number'] for item in core.duplicate_prs(
            repository, {'number': issue['number'], 'title': issue['title'], 'body': ''}, index))
    return found


def collect(repository, cutoff, horizon_days, client, *, max_issues, max_search_pages):
    if benchlib.when(cutoff) + dt.timedelta(days=horizon_days) > dt.datetime.now(dt.timezone.utc):
        raise SystemExit('The horizon has not ended yet: outcomes would not be mature')
    if max_issues <= 0 or max_search_pages <= 0 or horizon_days <= 0:
        raise SystemExit('Bounds must be positive')
    notes = []
    meta = core.repository_metadata(repository, client)
    branch = meta['default_branch']
    commits = core.require(client.request(f'repos/{repository}/commits?sha={quote(branch, safe="")}'
                                          f'&until={quote(cutoff, safe="")}&per_page=1'), list, 'commits')
    commit = core.require(core.require(commits[0], dict, 'commit').get('sha'), str, 'commit sha') if commits else None
    if commit is None:
        raise core.ProtocolError('api_shape', 'No commit before the cutoff')
    tree = core.require(client.request(f'repos/{repository}/git/trees/{commit}?recursive=1'), dict, 'tree')
    paths = [entry['path'] for entry in tree.get('tree', []) if entry.get('type') == 'blob']
    day = cutoff
    open_query = f'repo:{repository} created:<={day}'
    found = {}
    for kind in ('issue', 'pr'):
        for state in ('is:open', f'closed:>{day}'):
            for item in search(client, f'{open_query} is:{kind} {state}', max_search_pages, notes):
                found.setdefault(kind, {})[item['number']] = item
    prs = [{'number': item['number'], 'title': item['title'], 'created_at': item['created_at'],
            'html_url': f'https://github.com/{repository}/pull/{item["number"]}'}
           for item in sorted(found.get('pr', {}).values(), key=lambda item: item['number'])]
    candidates = sorted(found.get('issue', {}).values(), key=lambda item: item['created_at'], reverse=True)
    if len(candidates) > max_issues:
        notes.append(f'{len(candidates)} issues open at the cutoff; kept the {max_issues} most recently created')
        candidates = candidates[:max_issues]
    issues, bodies, dropped = [], {}, 0
    for item in sorted(candidates, key=lambda item: item['number']):
        events = timeline(client, repository, item['number'], notes)
        if events is None:
            continue
        record = benchlib.evidence(events, item)
        if not benchlib.classify(record, cutoff, horizon_days, repository)['open_at_cutoff']:
            dropped += 1
            continue
        issue = benchlib.reconstruct(item, events, cutoff)
        issue['evidence'] = record
        issues.append(issue)
        bodies[str(item['number'])] = item.get('body') or ''
    if dropped:
        notes.append(f'{dropped} issues were closed at the cutoff (reopened only after it) and were dropped')
    # PR membership and titles at T matter only where a PR can create an overlap; verify those.
    relevant = overlapping_prs(repository, issues, prs)
    verified, removed = [], 0
    for pr in prs:
        if pr['number'] not in relevant:
            verified.append(dict(pr, membership_verified=False))
            continue
        events = pr_events(client, repository, pr['number'])
        if events is None:
            notes.append(f'PR #{pr["number"]} events exceed 2 pages; kept unverified')
            verified.append(dict(pr, membership_verified=False))
            continue
        state = benchlib.pr_at_cutoff(pr, events, cutoff)
        if not state['open']:
            removed += 1
            continue
        verified.append(dict(pr, title=state['title'], membership_verified=True))
    prs = verified
    if removed:
        notes.append(f'{removed} PRs were closed at the cutoff (reopened later) and were removed')
    snapshot = {'format': benchlib.FORMAT, 'repository': repository, 'default_branch': branch,
                'cutoff': cutoff, 'horizon_days': horizon_days,
                'collected_at': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),
                'commit_at_cutoff': commit, 'tree_paths': paths, 'tree_truncated': tree.get('truncated') is not False,
                'open_prs_at_cutoff': prs,
                'issues': issues, 'notes': notes,
                'source': {'api': 'https://api.github.com', 'repository_url': f'https://github.com/{repository}'},
                'provenance': ('Public GitHub metadata (issue and PR titles, label names, timestamps, author '
                               'associations, file paths) with source URLs for attribution; no bodies or logins. '
                               'Content rights remain with their authors (GitHub Terms of Service); this is not '
                               'a licence grant and the harness MIT licence does not cover it.')}
    return snapshot, bodies


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('repository')
    parser.add_argument('--cutoff', required=True, help='RFC 3339 UTC time, e.g. 2026-03-01T00:00:00Z')
    parser.add_argument('--horizon-days', type=int, default=90)
    parser.add_argument('--max-issues', type=int, default=150)
    parser.add_argument('--max-search-pages', type=int, default=5)
    parser.add_argument('--output', required=True)
    parser.add_argument('--bodies-out', help='Optional local file for current issue bodies; never inside this checkout')
    args = parser.parse_args()
    if args.bodies_out and pathlib.Path(args.bodies_out).resolve().is_relative_to(ROOT):
        parser.error('--bodies-out must be outside the checkout: bodies are not committed')
    client = Counting(core.GitHub())
    snapshot, bodies = collect(core.parse_repository(args.repository), args.cutoff, args.horizon_days, client,
                               max_issues=args.max_issues, max_search_pages=args.max_search_pages)
    snapshot['reads'] = client.reads
    pathlib.Path(args.output).write_text(json.dumps(snapshot, indent=1, sort_keys=True) + '\n', 'utf-8')
    if args.bodies_out:
        pathlib.Path(args.bodies_out).write_text(json.dumps(bodies, sort_keys=True) + '\n', 'utf-8')
    labels = benchlib.labels(snapshot)
    counts = {name: sum(value == name for value in labels.values()) for name in ('positive', 'negative', 'excluded')}
    print(json.dumps({'repository': args.repository, 'issues': len(snapshot['issues']), **counts,
                      'reads': client.reads, 'notes': snapshot['notes']}))


if __name__ == '__main__':
    main()
