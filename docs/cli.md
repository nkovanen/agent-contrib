# Command reference

Commands emit JSON by default except help/version. Exit codes: **0** for a complete read,
successful export/draft write or completion-ready verification; **1** for an
expected error, incomplete read or unresolved verification; **2** for usage
errors. An exit code is not authorization.

JSON results are flushed before returning. If the stdout pipe's consumer has
closed, the command closes the failed stream and exits **1** without a traceback
or a second error during interpreter shutdown. This also overrides an otherwise
successful result or usage-error status when its JSON cannot be delivered.
A missing stdout stream (for example, fd 1 closed before Python starts) also
returns **1** quietly. Caller-provided replacement streams need only support
`write()`; their `flush()` and cleanup `close()` methods are used when available.
Writable stdout, including a redirected output file, retains the normal JSON
format and command exit status. Help/version output is unchanged.

| Command | Result |
| --- | --- |
| `agent-contrib discover owner/repo` | Repository resolution, policy/instruction context, ranked issues and overlap/completeness metadata |
| `agent-contrib discover owner/a owner/b ... [--repositories-file FILE]` | Two to 20 repositories in one run, each with its own result, plus a merged candidate order |
| `agent-contrib discover owner/repo --signals` | Same reads and fields, plus per-issue `signals` and a signal-aware `ordering` |
| `agent-contrib discover owner/repo --responsiveness` | One extra read of recently closed PRs, reported as `repository_signals.responsiveness`; issues and ordering unchanged |
| `agent-contrib audit owner/repo [--print-policy]` | Read-only maintainer report: policy validity, labels, instruction coverage, issue-quality and overlap counts, non-binding suggestions |
| `agent-contrib inspect 'owner/repo#123'` | Detailed issue snapshot, source policy, instructions, exclusions and PR matches |
| `agent-contrib prepare 'owner/repo#123' --output task.json` | A new schema `0.1` draft; an existing output file is never overwritten |
| `agent-contrib verify task.json` | Schema, current source/approval/overlap and execution-readiness checks; no commands executed |
| `agent-contrib verify task.json --evidence evidence.json --repo-dir checkout` | Also validates supplied evidence against the local checkout and live source |
| `agent-contrib authorization-request task.json` | Schema 0.2 only: an unsigned request with every mandate binding pre-filled from the contract and live reads and every human-only field `null`. Grants nothing; exit 1 when not ready |
| `agent-contrib scope-check task.json --repo-dir checkout [--base REV]` | Offline check of committed, staged, unstaged and untracked paths against the contract scope; exit 1 lists each violation. Never evidence |
| `agent-contrib evidence init task.json --repo-dir checkout --base REV --output evidence.json` | A new evidence skeleton with observed Git facts and contract IDs; results stay unfilled and the file fails validation until completed |
| `agent-contrib pr-body task.json [--evidence e.json --repo-dir checkout] [--closes] [--assistant TEXT] --output body.md` | A new Markdown PR description built from the contract, evidence and a fresh read-only `verify` run |
| `agent-contrib feedback 'owner/repo#PR' [--expected-head SHA]` | Read-only review state, review/issue comments and failing or pending check runs for a published PR |
| `agent-contrib inspect 'owner/repo#123' --ownership` or `agent-contrib ownership 'owner/repo#123'` | Opt-in, report-only timeline and comment signals: cross-referenced PRs, assignments, claims and possible prior fixes |
| `agent-contrib inspect 'owner/repo#123' --ai-policy` | Adds located excerpts of AI-contribution statements from the loaded instruction files |
| `agent-contrib drift task.json` | Read-only report of what changed since preparation: issue, instruction files, branch, policy and open-PR overlap |
| `agent-contrib verify task.json --evidence e.json --observe-ci` | Also reports GitHub check runs and combined status for the evidence head; never changes gates or exit code |
| `agent-contrib --report-budget [--min-remaining N] COMMAND ...` | Adds the core REST rate-limit budget before and after a GitHub-reading command; optionally refuses to start below N |
| `agent-contrib instructions` | Installed workflow Markdown, CLI version, schema support and update behavior |
| `agent-contrib skill --output SKILL.md` | Canonical adapter export, CLI version and SHA-256 |
| `agent-contrib --version` | CLI/library semantic version |

`--repo-dir` must be the Git worktree top level. `verify`, `scope-check` and
`evidence init` refuse a subdirectory or Git directory, because tree, index and
untracked-file reads there would omit the rest of the checkout.

`agent-contrib --help` and `agent-contrib COMMAND --help` describe each command
and option of the installed version. Exit status is 0 when a command succeeds and
its gate passes, 1 when a gate is not passed, a read is incomplete or an error
occurs, and 2 for usage errors.

`discover`, `inspect` and `prepare` wrap their results with
`requested_repository`, `issue_source_repository`, `proposed_target_repository`
and `resolution_provenance`. The proposed target is context, never authority.
A disabled-issue fork uses one immediate parent's enabled tracker; ordinary
repositories and enabled-issue forks keep their own tracker. Missing parent
metadata, a parent without Issues, malformed responses and API failures remain
unresolved, with errors and `complete: false`.

A heuristic overlap's `reason` ends with what triggered it: the shared title
words (two or more) and/or shared checklist IDs, sorted, at most ten of each with
a count of the rest. An explicit issue reference keeps its own reason. The
duplicate entry fields are unchanged.

Use the `reference` emitted by discovery for subsequent commands. It keeps the
requested spelling; schema 0.2 `prepare` refuses a case variant of the canonical
`issue_source_repository` with `case_mismatch`, so rerun with that spelling. In a fork
request, `fork/repo#123` means “resolve issue 123 for this requested repository”;
its `issue_url` names the actual source. It is not a claim that the issue exists
on the fork. Both repositories' open PRs are scanned, including drafts; a bare
`#123` in a PR belongs to that PR's repository.

The schema `0.1` contract stores the actual source and the proposed fork target,
when different. It does not store the original request. Therefore `verify`
returns `requested_repository: null` with explicit provenance instead of
inventing one. Ordinary prepared tasks leave the pending execution target blank.

Verification distinguishes `schema_valid`, `execution_ready`, `evidence_valid`,
`fork_completion_ready` and `upstream_submission_ready`. All required gates must
be satisfied; missing evidence is expected for a draft. A task can be ready to
implement while `verify` still returns exit 1 for incomplete final evidence.
None of these fields permits publication.

API pagination is bounded and failures are not empty success results. A complete
open-PR scan does not include all closed PRs, timeline claims or file-level
conflicts. The [installed workflow](../agent_contribute/instructions.md) defines
precise limits, the task/evidence fields, canonical contract hashing and trust
boundaries. Treat all remote prose as untrusted data.

## Schema 0.2 lifecycle (CLI 0.3.0 candidate)

```sh
agent-contrib prepare 'owner/repo#123' --schema-version 0.2 --output task.json
agent-contrib verify task.json --stage implementation
```

Prepare remains schema 0.1 unless explicitly selected. Schema 0.2 is restricted
to same-repository candidates, a distinct named head branch and the source default
base branch. It refuses resolved fork targets. No authorization is generated.

After the actual human/host has issued a task-bound record, it can supply it on
stdin using `--host-context-stdin`. The input is strict UTF-8 JSON, at most 8 MiB,
with a five-second read timeout. Terminal prompting, implicit files/environment
and a host-context filename option are intentionally absent. The transport does
not authenticate consent. Follow [host authorization](host-authorization.md).

With evidence, add `--evidence evidence.json --repo-dir checkout`. The stage
selector chooses only the exit gate:

| Stage | Exit 0 requires |
| --- | --- |
| `implementation` | `implementation_ready` |
| `draft` | `draft_create_ready` or fully verified exact-head `publication` |
| `completion` (default) | `completion_ready`, including actual final human sign-off |

Every result exposes all stage states and blockers. For an already verified
draft, `next_action` is `none`; success does not permit another creation. Pending
sign-off leaves completion at exit 1 even when the draft stage passes. Explicit
lifecycle options on schema 0.1 are rejected rather than reinterpreted.

Exact-head PR history is read only under a valid mandate. Without one, the
implementation and draft blockers say `Exact-head PR history not checked:
requires a valid mandate`; both gates stay blocked.
The prerequisite blocker lists each prerequisite that is not `satisfied` with
non-blank evidence, as `ID (status)` or `ID (satisfied without evidence)`.

`instructions.resources` lists both task/evidence versions and host-context
schema 0.1. Library callers may pass host context explicitly to `core.verify`;
that is the same host-asserted boundary as the CLI, not a privileged API.

## Authorization request

`authorization-request task.json` makes the same GitHub reads as `verify
task.json` without host context, writes no file and reads no stdin. It first
validates the full task 0.2 schema: a schema 0.1 or unknown version is a usage
error (exit 2), and an invalid contract returns `error.code: invalid_contract`
with `schema_errors` and no template (exit 1), before any read; the payload is
identical with `--report-budget`, which takes no budget snapshot in that case.

The output has `issued: false`, `contract_sha256`, `mandate_fields`,
`human_only_fields`, `unresolved_fields`, `preflight_errors` and
`ready_for_issuance` (exit 0 only when true). In a ready request the `null`
leaves of `mandate_fields` are exactly `human_only_fields`. When identity or
permission reads fail, `credential_actor_id` and `authority` are also `null` and
listed in `unresolved_fields`; only fresh trusted reads resolve them.
`preflight_errors` omit the blockers that exist only because no mandate exists
yet. They are untrusted diagnostics and may contain repository-authored paths.

The request deliberately contains no scope, path, objective, criteria or
validation summary. The host renders the complete contract from the file it
hashes, issues the record, and the worker relays it unchanged. The request is not
host context: piping it to `verify --host-context-stdin` fails schema validation.

## Offline scope check

`scope-check` evaluates the working diff against the contract's
`scope.allowed_paths` and `scope.prohibited_paths` with the same function that
`verify` uses for evidence. It reads only the local checkout: committed changes
from `--base` (default: `source.commit`) to HEAD, staged and unstaged changes,
and untracked files that are not ignored. Renames report both paths. The base
must be an ancestor of HEAD; gitlinks fail closed. `--base` accepts exactly a
full 40-character SHA, `HEAD`, or a full ref name such as `refs/heads/NAME` or
`refs/tags/NAME`, each optionally followed by `~N` or `^N` (for example
`HEAD~3` or `refs/heads/base~1`). Short branch or tag names, abbreviated SHAs
(convert with `git rev-parse ABBREV`), pseudo-refs other than `HEAD` and other
revision syntax (`:/text`, `@{...}`, `REV^{type}`, paths, ranges) are refused.
`HEAD` and `refs/...` names are looked up exactly with `git show-ref --verify`,
never through Git's short-name lookup, so a same-named ref such as
`refs/tags/HEAD` cannot stand in for them; an unborn `HEAD` is refused. The
object ID is captured first, then the suffix and `^{commit}` are applied to it
with `git rev-parse`.
Every read uses the same hook, fsmonitor and replacement-object protections as
other Git reads, and nothing under `.git` is opened directly. `base_commit`
reports the full SHA. A value that is blank, starts with `-` or contains
whitespace or control characters is refused. When the default base is not an ancestor of HEAD,
`warnings` suggests passing `--base` for stacked or rebased work; the result
still fails. It makes no GitHub calls, so it can run as a pre-commit hook. Exit 0
means "no scope violation found", not evidence, readiness or authorization.
Each violation names the path and either the first matching prohibited pattern
or `not in allowed_paths`.

## Evidence skeleton

`evidence init` writes a draft evidence file for the contract's schema version.
It fills only what the CLI observes locally: the canonical `contract_sha256`,
`git_head`, `git_tree`, the given `base_commit` and the observed
`worktree_clean`. Validation entries copy each contract `id` and `argv`;
criteria copy their IDs. Every result field is left unfilled (`null` or empty),
criteria and attestations are `pending`, and `implementer` is blank, so the
skeleton deliberately fails evidence validation. It never runs argv and never
writes `passed`.

The base is resolved like `scope-check --base` and recorded as a full SHA. It
must descend from `source.commit` and be an ancestor of HEAD. Gitlinks are
refused. The output is created exclusively and
must be outside the checkout's Git top level, because an untracked file there
would invalidate the evidence. A dirty worktree is recorded as observed
(`worktree_clean: false`), which `verify` rejects.

## PR description

`pr-body` runs the same read-only `verify` and renders Markdown: the issue
reference (`Refs` by default, `Closes` only with `--closes`), objective, scope,
criteria with their evidence status, each validation `argv` as an exact JSON
code span with the recorded status, exit code, test and skip counts, review and
sign-off status, the count and full neutralized text of every verify blocker,
the open-PR scan provenance (completeness, pages, error count per scanned
repository) with every overlapping PR, and an AI-assistance disclosure with the
CLI version and contract hash. `--assistant` adds host-reported model text.

When supplied evidence does not pass `verify`, its statuses are labelled
`unverified claim`. Evidence that fails its schema is not quoted at all; its
errors appear among the gates. For schema 0.2, review and sign-off states come
from `verify`. `pr-body` takes no host context, so for 0.2 it shows only
`technical_evidence_valid` with source (including repository, owner and issue
identity), evidence and review blockers. It omits
the implementation, draft and completion gates, `next_action`, final sign-off and
authorization blockers, and says so, rather than misreporting authorized work as
unauthorized. The host's `verify --host-context-stdin` run decides those.

One extra bounded read of the tree at the contract's pinned `source.commit`
finds pull request templates (`pull_request_template.md` or a
`pull_request_template/` directory at the root, `.github/` or `docs/`,
case-insensitive). The body names each path and blob SHA, or says that none
exists, or that presence is unknown when the read fails or is truncated.
Template contents are not read and the CLI does not fill the template.

All quoted prose is neutralized: whitespace collapses to one line, HTML is
escaped, Markdown link/image/emphasis/code characters are backslash-escaped,
and zero-width space entities break `@` mentions, `#` references, `://` URLs
and closing keywords (close, fix, resolve and their forms). Data shown in code
spans (argv, template paths) is exact JSON. The output file is created
exclusively. Rendering never writes to GitHub and is not publication authority.

## Opt-in ranking signals

`discover --signals` adds deterministic, explained heuristics to each issue
without extra API calls. Without the flag, output and ordering are unchanged.

- `code_location`: paths in the issue title/body (first 64 KiB) that exist in
  the snapshot tree, including repository-relative suffixes of stack-frame
  paths and file names that match exactly one tree path (at most 20). It is
  `unknown` when the tree read was incomplete. Module names of two or more
  segments joined by `.` or `::` (`pkg.mod`, `pkg.mod.func`, `crate::a::b`)
  also count when they name exactly one file: the file's path without its
  extension, or a package directory holding `__init__.py`, `mod.rs` or
  `index.*`, must end with the segments. A leading Rust `crate`, `self` or
  `super` is ignored. Trailing segments are treated as members, so the longest
  prefix that names any module decides; an ambiguous match gives no hint and
  never falls back to a shorter prefix. Single names (`signals`) and names
  inside paths are not resolved. Path and file-name matches come first and the
  same limit of 20 applies.
- `acceptance_clarity`: `high`, `medium` or `low` from checklists,
  expected/actual sections, reproduction steps and code blocks.
- `activity`: age and last-update days, comment and reaction counts from the
  issue list payload; malformed fields are `null`.
- `maintainer`: whether the issue author's association is OWNER, MEMBER or
  COLLABORATOR.
- `score`: one point for found locations, up to two for clarity, one for a
  maintainer author.

Ordering stays exclusions first, then overlaps, then low success likelihood;
only then does a higher `score` come first, with the issue number as the final
tie-breaker. Signals are heuristics. They never approve, authorize or replace
reading the issue.

## Repository responsiveness

`discover --responsiveness` makes exactly one additional GET for the issue
source repository, `repos/{source}/pulls?state=closed&sort=updated&direction=desc&per_page=100`,
and adds a top-level `repository_signals.responsiveness` report. Without the
flag, reads and output are unchanged, including with `--signals`. The report is
a one-page sample of the most recently updated closed PRs, never full history:

- `sample_size`: closed PRs read; `external_closed` and `external_merged`: of
  those, PRs whose author association is not OWNER, MEMBER or COLLABORATOR and
  whose author is not a bot.
- `value: measured` with `external_merge_rate` and `median_days_to_close`
  (creation to close, merged or not) when at least `minimum_external` (5)
  external PRs are present; otherwise `insufficient`, with the rate and median
  `null`.
- `value: unknown`, `complete: false` and an error when the read fails, a page
  or entry is malformed, or discovery did not complete its source snapshot (then
  nothing is read).

Each report has an `explanation`. No PR text is copied. The report never changes
approval, exclusions, overlaps, ordering or discovery `complete`. As with
`inspect --ownership`, exit 1 also covers an incomplete opted-in report; in a
multi-repository run each repository carries its own report. Author association
is not verified identity, and responsiveness is a heuristic, never approval.

## PR feedback

`feedback` reads one PR, its reviews, review comments, issue comments and the
check runs for its current head, then rereads the PR. The PR must have the
requested number, the canonical repository as its base and a valid head SHA. A
head that moves during the read makes the result incomplete.

Per reviewer it reports `latest_state` and `decision`: the latest APPROVED,
CHANGES_REQUESTED or DISMISSED review (DISMISSED clears it; COMMENTED and
PENDING never change it). Reviews are grouped by numeric user ID; `author` is
the latest observation and `decision_author` the author of the decisive review.
`changes_requested_by_trusted_association` is true when the decisive review of
an outstanding change request has a non-bot author with association OWNER,
MEMBER or COLLABORATOR. That association is a GitHub heuristic, not a
verified maintainer role. Deleted accounts appear as `ghost`. Review comments
include path, line and `outdated` (no diff position, or made on another
commit). Failing (failure, timed out, cancelled, action required, startup
failure, stale) and pending check runs are listed only for the exact head;
`other_head_runs` counts runs for other heads. `--expected-head` (for example
the evidence `git_head` of the recognized draft) adds `head_moved`. Logs are not
read.

All text fields are `untrusted_*` data with terminal controls removed. Feedback
never widens scope or grants authority; a requested change outside the reviewed
contract needs contract re-review. Malformed reviews, comments or check runs
are errors, not silently cleaned records: IDs and diff positions must be
positive, author associations, review states, run statuses and conclusions must
be known values, a run's conclusion must be set exactly when it is completed,
and SHAs must be 40 hex characters. Null bodies, commit IDs and lines are
accepted where GitHub documents them as nullable. Check-run pagination requires unique run IDs, a stable
`total_count` and a matching final count. Any of these failures gives
`complete: false` (exit 1).

## Ownership and resolution signals (report only)

`inspect --ownership` adds `ownership_signals` to the normal inspect result;
`ownership 'owner/repo#123'` prints them with repository resolution. Without
the flag, `inspect`, `prepare` and `verify` neither read nor report them, and no
approval, overlap or readiness decision changes in any schema version.

Reads: the issue timeline and comments (complete pagination; timeline events
without IDs are deduplicated by content), then a fresh `pulls/{n}` read for
each cross-referenced PR (at most 50, otherwise incomplete). Each PR reports
repository, repository ID, number, state, draft, merged, merge/close times and
`exact_reference`: whether the PR text references this issue exactly (local
`#N` only in the issue's own repository, `owner/repo#N` or the issue URL), with
the same parser as overlap detection.

- `resolution_signals.possibly_already_fixed`: merged PRs with an exact
  reference. `rejected_approaches`: closed, unmerged PRs with an exact reference.
- `assignment_history`, `connected_events` and `referencing_commits` from the
  timeline.
- `claims`: comments matching a fixed set of claim patterns ("I'm working on",
  "I'll take", "can I work on", `/assign`, "assign me"), with author
  association, age, `stale` (older than 30 days or unknown) and a sanitized
  `untrusted_excerpt`. Comment text never proves, grants or removes ownership.
- `blocking_if_adopted` previews what a future versioned gate might block; it
  blocks nothing now.

Every consumed field is shape-checked: positive IDs and numbers, known
enumerations, 40-character SHAs, and PR details whose number, canonical URL,
base repository name and repository ID match the timeline reference. A deleted
account (`null` user) appears as `ghost`, and timeline event kinds the reader
does not use are ignored. Any wrong type, identity mismatch, failed or partial
read makes the signals `complete: false` and `resolution_signals.status:
unknown`; an unknown is never "not fixed". With
`--ownership`, exit 1 also covers incomplete signals.

## AI-contribution statements (opt-in)

`inspect --ai-policy` adds `ai_policy` without changing any other field. It
scans the instruction files `inspect` already loaded, line by line, for a fixed
set of patterns (AI-generated, AI-assisted, LLM, large language model,
generative AI, artificial intelligence, Copilot, ChatGPT, machine-generated, "no
AI", AI tools/agents/contributions/code). Each hit gives the path, line number,
the file's SHA-256, the matched patterns and a one-line `untrusted_excerpt` of
at most 300 characters (`excerpt_truncated` marks a shortened excerpt). At most
200 excerpts are returned (`excerpts_capped: true` beyond that). Only the first
2000 characters of each line are scanned; `lines_partially_scanned` counts
longer lines.

`ai_policy_review` is always `required`. `coverage` is `incomplete` when any
instruction read failed, the 60-file cap was hit, excerpts were capped or any
line was only partially scanned. The CLI does not interpret the prose: a hit is a signal to read the
file in context, and zero hits do not mean AI contributions are welcome. A
machine-readable maintainer opt-out (a new policy version) is a separate,
not-yet-implemented design.

## Drift since preparation

`drift task.json` compares a schema-valid contract with the live source and
never writes anything. It reports:

- `source`: stored and current source repository and issue URL, and for 0.2
  stored and current repository, owner and issue numeric IDs. Any difference,
  such as a fork tracker switch or a recreated repository, is drift; an
  unresolved 0.2 identity makes the report incomplete.
- `issue`: whether the combined issue hash changed, stored and current
  `updated_at`, and the current title/body hashes, state, labels and assignees.
  Per-component baselines are unavailable because schemas 0.1 and 0.2 store one
  combined hash.
- `instructions`: the files `added`, `removed` and `modified` (path and both
  SHA-256s). The baseline is reconstructed by re-reading the instruction files
  at the contract's immutable `source.commit`; it is used only when its
  aggregate equals the stored `instructions_sha256` (`baseline_verified`).
- `default_branch`: stored and current branch and commit. An advanced commit
  alone is informational and not drift.
- `policy`: stored and current approval status, plus policy hashes for 0.2.
- `overlap`: open source-repository PRs added to or gone from the prepared list.

The issue component read must hash to the same value as the inspection it
accompanies; if the issue changed in between, the report is incomplete. Exit 0
only when every read completed and nothing drifted. Any failed read,
including an unverifiable baseline, gives `complete: false`. The pinned re-read
costs another snapshot's worth of reads. After drift, review and prepare the
contract again.

## CI observation (opt-in, report only)

`verify ... --evidence evidence.json --observe-ci` adds `ci_observation` after
the verify decision and exit code are fixed; it never changes any gate. For the
evidence `git_head` in the contract's target repository (the source when the
target is blank), it reads every check-run page and the paginated combined
commit status. It reports check runs for that exact head (name, app slug and
numeric app ID, status, conclusion, URL), the count of runs for other heads,
and the combined state with each status context.

Shapes are strict: positive IDs, documented statuses and conclusions (set
exactly when a run is completed), and a combined status for the requested SHA.
For both check runs and statuses, `total_count` must be a non-negative integer
that stays stable across pages and equals the number of unique items read. Any failure, or a missing or
invalid evidence head, gives `complete: false` with errors. Queued, pending,
approval-required or missing runs are never success. This is an observation of
what GitHub reports, not proof that the evidence checks equal the CI checks.
Required-check gating is a deferred future-schema design.

## API budget (opt-in)

`--report-budget` before a GitHub-reading command reads `GET rate_limit` (which
does not consume the budget) before and after the command and adds
`api_budget`: both snapshots (limit, remaining, used, reset) and
`used_during_command`. Because other processes may share the token, that
number is an upper bound. It is `null`, with `delta_unknown_reason`, when a
snapshot failed, the reset window or limit changed, or the used counter
decreased; a negative difference is never reported. A snapshot is rejected
(`null` values with an error, never zero) unless its counters are non-negative
integers with `used + remaining == limit`. Command arguments are validated
before the first snapshot: malformed repository references, unreadable input
files and schema-invalid `drift`/`pr-body` contracts cause no GitHub read.
`verify` still reports schema and evidence failures in its normal result envelope;
optional budget reads do not turn those failures into success. `--min-remaining N` refuses to start (error `rate_limit_budget`, exit 1)
when the budget is unknown or below N, before any command read. The CLI does not
estimate a command's cost; choose N yourself. Offline commands reject the flag.
Without the flag, no rate-limit read happens and output is unchanged. Response
caching is a deferred design.

## Several repositories

`discover` accepts several repositories as arguments and/or
`--repositories-file FILE` (UTF-8, at most 64 KiB, one `owner/repo` per line,
blank lines and `#` comments ignored). With exactly one repository the output is
the unchanged single-repository result. With 2 to 20 distinct repositories it
returns `repositories` (each repository's complete single-repository result, in
input order), `candidates` (every issue with its repository, reference and the
ordering facts), `errors` prefixed with the repository name, and top-level
`complete`, true only if every repository is complete. A failing repository
never aborts the others or marks them complete. All identifiers are validated
before any read. The merged order is exclusions, overlaps, low likelihood,
higher signal score with `--signals`, then repository and issue number.

Reads cost the sum of the single-repository runs; combine with
`--report-budget --min-remaining N` on large lists. A display cap such as the
proposed `discover --limit` (#1) would apply per repository. Deriving
repositories from a dependency graph is out of scope.

## Text output (unreleased)

Put the global option before the subcommand:

```sh
agent-contrib --format text discover owner/repo
agent-contrib --format text verify task.json
agent-contrib --format json inspect 'owner/repo#123'
```

Text changes presentation only, never scan depth, authorization or exit status.
It is a summary: discovery shows at most 20 issues per repository, lists show at
most 50 entries and long remote lines are shortened. Omitted list entries are
counted. Multi-repository discovery includes every repository's completeness and
errors. Verification shows the gates and blockers. With an explicit
`verify --stage X`, text starts with stage X, its exit gate and its blockers;
the other stages appear only as blocker counts, because they do not decide that
exit. When schema validation fails before any stage is evaluated, the stage
line reads `not evaluated; see Errors` and the schema errors follow. JSON still
contains every stage. `scope-check` lists each violating path
and rule, warnings and errors. `drift` lists the reasons that set `drifted`, then
informational changes (an advanced default branch, PRs no longer open) apart.
Other commands show top-level
scalar fields; use JSON for full nested results, instructions and provenance.
Remote text is sanitized to a single line so it cannot add fake gate headings.
Default JSON bytes are unchanged. Parse-time usage errors still use structured
JSON when argument parsing has not produced a valid format selection.
A global option (`--format`, `--report-budget`, `--min-remaining`) placed after
the subcommand is still a usage error (exit 2); its message says to move the
option before the subcommand.

The text option uses the same stdout handling as JSON. Closed output returns 1
quietly; writable output retains the command's normal exit status. Output JSON
Schemas and an output-schema version are not implemented yet.
