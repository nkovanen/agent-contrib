# Find public Tipjar invitations

Status: proposed for controller-arranged review; documentation only, not implemented. Build after the reviewed jar inspection slice;
baseline design `c312c57`. Reader interface checked against inspection candidate `8002533`: `tipjar.read_jar(repository, client=None,
*, commit=None, metadata=None)`.

## Purpose and scope

`tipjar find [--owner OWNER]` finds a small batch of public repositories declaring welcome in their own root `.tipjar.json`, without
requiring known repository names. A tip is agent work. This is an invitation finder, not issue discovery or approval. Use existing
discover/inspect/policy review next; execution and publication still require their separate authority. A welcome cannot override
contribution refusals. No task/evidence/host-context changes, registry, topic writes, payments, crawling, issue/PR reads, automatic
contact, or changes to supplied-list `--welcomed-only`.

Decision: fixed 10 search hits, one page, no scan/display controls in the first slice. A registry would add operations/adoption costs;
owner repository enumeration would scale with account size. REST code search offers a bounded candidate source, with incomplete
coverage. Repeating the command can return the same batch; no cursor or promise of fair rotation. A later pagination design needs its
own reviewed bounds.

## Search and candidate validation

Use authenticated existing `gh` GET transport, fixed `search/code` endpoint with URL-encoded `q=filename:.tipjar.json path:/`,
`per_page=10`, `page=1`. Optional owner appends exactly `user:OWNER`; legacy code search supports user/org scope. Validate OWNER with
existing owner grammar `[A-Za-z0-9][A-Za-z0-9-]{0,38}` before any GET; do not accept arbitrary query text, URLs, spaces or extra
qualifiers. No repository-search qualifiers (including visibility/archive filters), content `welcome` term, sort guarantee, new
web-code-search syntax or fallback query. Apply public/active eligibility through fresh repository metadata instead.

Require object response, integer (not bool) `total_count >= 0`, boolean `incomplete_results`, list `items` of at most 10, and
`total_count >= len(items)`. Malformed envelope fails the search; inspect nothing. If fewer than `min(total_count,10)` hits arrive,
retain them but mark anomalous short page/unknown. `incomplete_results=true` retains verified findings but makes the command
incomplete. For each hit require object, exact `name` and `path` `.tipjar.json`, valid 40-hex blob SHA, repository positive integer id,
validated full_name, and owner positive integer id/login matching its full_name. Require search `private` boolean; true is excluded
before further reads. An exact-path mismatch is a known nonroot/case exclusion, not an invitation. Other malformed hits are unknown;
never follow returned URLs, fragments, text matches, branch references or content bytes in application logic. Recheck owner case-insensitively against the
validated filter locally.

Validate the entire bounded page before reading jars. Collapse identical hits by numeric repository id plus case-folded full_name;
changed indexed SHA, name/id or owner-id conflicts invalidate every hit in the conflicting group as unknown. Never spend another
inspection slot on duplicates or backfill filtered hits.

## Fresh verification and limits

For each remaining distinct candidate, one `request_once('repos/'+full_name)` reads metadata. Require matching repository/owner numeric
ids and case-folded names, `private=false`, `visibility='public'`, `archived=false`, `disabled=false`, exact boolean flags and a valid
default branch. Known private/archived/disabled is an exclusion; missing/malformed/changed identity is unknown. Application logic does not
follow renames, transfers, parents or tracker resolution; canonical-name and numeric-id checks reject renamed/transferred responses even
after an internal gh redirect. A fork declares only itself. Pass this validated metadata to `tipjar.read_jar` with no
explicit commit: reuse its default-branch pin, complete tree, strict parser, byte/hash checks and provenance. Never compare indexed SHA
with current SHA as a freshness gate: stale index may legitimately lead to closed/undeclared/changed welcome. Unknown is never welcome.
After a complete welcome read only, GET metadata once more and require unchanged identity, owner, default branch and public/active
eligibility. Changed branch or identity/read failure is unknown; known ineligibility excludes and discards jar payload from public
output. Never display manifests from known private targets. Observations are snapshots, not atomic guarantees: branch/content or
visibility can change after a read. Report verification times and pinned commit, not “live now”.

At most 10 candidate inspections; each uses one metadata call + at most three reader calls with supplied metadata + at most one final
metadata call = five. Command work is <=51 logical GET calls and <=51 gh invocations (1 search, <=50 core), sequential, with no
application retry/sleep/pagination/fallback/backfill. Use existing `request_once` throughout; failures never fall back to retrying
request. These are invocation bounds, not raw HTTP GET bounds: gh may internally follow redirects; raw HTTP count is not instrumented
and may exceed the invocation count. No new authentication/HTTP transport is introduced. Retain the existing 8 MiB response cap and
30-second parent timeout covering each whole gh invocation; no disk cache for find reads, even under global `--cache`. Maximum summed
command invocation timeout is 25.5 minutes, excluding other processing. `--report-budget` adds two logical snapshot reads with up to
three gh invocations each: <=6 extra, <=57 total; all-success is 53 at maximum work. Existing `--min-remaining` checks core only;
neither it nor the core delta promises search quota. Search has its own tighter rate limit. Report `requests` search/core counters
count gh invocations, excluding instrumentation, never raw HTTP requests. No rate-limit probe is required by default; auth/rate errors
end the relevant command read without application retries. Application code never follows returned URLs or adopts renamed/transferred
identities; response-boundary checks enforce this even if gh has already followed an HTTP redirect.

## Output, exits and adoption

New closed command schema `find.schema.json` under the active output version at implementation time; additive command registration
alone does not bump it. Do not widen historical schemas. Reuse the shipped jar-report schema, without new fields. Report discriminator
`find-jars-report/1` is independent of that output version. Required fields: `format`, `fetched_at`, `owner` (nullable), `search`
(fixed query, page, per_page, nullable total_count/incomplete_results, returned_count, truncated, short_page), `coverage`
(`exhaustive:false`, limitations), `observations`, `complete`, `errors`, `requests` (search/core gh invocations, instrumentation excluded),
`notice`. Unknown search values are null, never zero/false guesses. Each observation has nullable `repository` (validated full_name),
`repository_id`, `disposition` (`welcome|closed|undeclared|excluded|unknown`), `reason` (fixed code, <=300 characters),
`verified_at` (nullable metadata check time), and `jar` (unchanged jar report or null). Only disposition welcome is selectable. Keep invalid identities null and reasons as fixed codes; do
not emit raw malformed hits, private names/manifests, snippets or remote error text; private exclusions have null repository/jar
fields. Canonical JSON preserves validated manifest text as data; terminal summaries use existing neutralization/abridgement. Construct
repository links from validated names. `truncated` is null on envelope failure; otherwise `total_count > returned_count`. `complete`
means this bounded batch has no unknown/error or server incompleteness, not exhaustive coverage. Intentional truncation, known
exclusions and no welcome are exit 0; unknown/search failure/incomplete server/short page is exit 1; usage 2. Text says “No verified
welcoming repositories in this batch” for empty selection, with coverage/unknown/truncation warnings; never “no welcoming repositories
exist”.

No adoption is established by this design and there is no curated fallback list. Until indexed jars exist, explicitly name projects to
assess through existing commands; absence grants no approval and the documented upstream-route gap remains. Maintainers add the
supported welcome manifest from the jar design at repository root on the default branch, with ordinary contribution policies. Search
indexing may lag; direct `tipjar jar owner/repo` verifies without waiting for search coverage. Older clients do not enforce jars;
refusals should also be stated in ordinary docs.

## Official API basis and acceptance

[Legacy search syntax](https://docs.github.com/en/search-github/searching-on-github/searching-code) documents the filename-only
exception, root path and owner scope. Its index omits many repositories, especially forks. [REST
search](https://docs.github.com/en/rest/search/search#search-code) defines envelope, bounded pages, incomplete results and separate
code-search quota. Read 2026-11-03; no live GitHub search/adoption claim. A rejected filename-only query is a visible search failure,
never grounds for a broad query or invented results. Acceptance: offline regressions in the plan prove bounded GET-only candidate
search, strict independent welcome verification and truthful partial provenance.
