"""Collect a benchmark snapshot: a repository's issues open at a cutoff T, labelled by their outcome.

    python tools/benchmark/collect.py owner/repo --cutoff 2026-03-01T00:00:00Z --horizon-days 90 \\
        --output tools/benchmark/data/owner__repo__2026-03-01.json [--bodies-out /outside/checkout/bodies.json]

Read-only: every request is a fixed `gh api --method GET` through agent_contribute.core.GitHub.
Reads are bounded: repository metadata, one commit and one tree read, at most --max-search-pages
pages per search query (four queries), and one timeline (at most 5 pages) per kept issue."""
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


def collect(repository, cutoff, horizon_days, client, *, max_issues, max_search_pages):
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
    prs = [{'number': item['number'], 'title': item['title'], 'created_at': item['created_at']}
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
        label = benchlib.classify(events, cutoff, horizon_days, repository)
        if not label['open_at_cutoff']:
            dropped += 1
            continue
        issue = benchlib.reconstruct(item, events, cutoff)
        issue.update(outcome=label['outcome'], outcome_reason=label['reason'], evidence=label['evidence'])
        issues.append(issue)
        bodies[str(item['number'])] = item.get('body') or ''
    if dropped:
        notes.append(f'{dropped} issues were closed at the cutoff (reopened only after it) and were dropped')
    snapshot = {'format': benchlib.FORMAT, 'repository': repository, 'default_branch': branch,
                'cutoff': cutoff, 'horizon_days': horizon_days,
                'collected_at': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),
                'commit_at_cutoff': commit, 'tree_paths': paths, 'tree_truncated': tree.get('truncated') is not False,
                'open_prs_at_cutoff': [dict(pr, html_url=f'https://github.com/{repository}/pull/{pr["number"]}')
                                       for pr in prs],
                'issues': issues, 'notes': notes,
                'source': {'api': 'https://api.github.com', 'repository_url': f'https://github.com/{repository}'},
                'licence': ('Public GitHub metadata (issue and PR titles, label names, timestamps, file paths) '
                            'with source URLs for attribution; no issue or PR bodies are stored.')}
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
    counts = {name: sum(issue['outcome'] == name for issue in snapshot['issues'])
              for name in ('positive', 'negative', 'excluded')}
    print(json.dumps({'repository': args.repository, 'issues': len(snapshot['issues']), **counts,
                      'reads': client.reads, 'notes': snapshot['notes']}))


if __name__ == '__main__':
    main()
