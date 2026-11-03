# Command reference

Commands emit JSON by default except help/version. Exit codes: **0** for a complete read,
successful export/draft write or a passed verification gate (completion
readiness for schema 0.1, the selected `--stage` for 0.2); **1** for an
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
| `agent-contrib prepare 'owner/repo#123' --output task.json` | A new schema `0.1` draft with a `pending` `ai-policy-review` prerequisite; an existing output file is never overwritten |
| `agent-contrib verify task.json` | Schema, current source/approval/overlap and execution-readiness checks; no commands executed |
| `agent-contrib verify task.json --evidence evidence.json --repo-dir checkout` | Also validates supplied evidence against the local checkout and live source |
| `agent-contrib authorization-request task.json` | Schema 0.2 only: an unsigned request with every mandate binding pre-filled from the contract and live reads and every human-only field `null`. Grants nothing; exit 1 when not ready |
| `agent-contrib lint task.json` | Offline contract check: bundled task schema, then the reviewed-contract rules `verify` applies first; exit 0 only for a schema-valid reviewed contract. No GitHub or Git reads |
| `agent-contrib scope-check task.json --repo-dir checkout [--base REV]` | Offline check of committed, staged, unstaged and untracked paths against the contract scope; exit 1 lists each violation. Never evidence |
| `agent-contrib evidence init task.json --repo-dir checkout --base REV --output evidence.json` | A new evidence skeleton with observed Git facts and contract IDs; results stay unfilled and the file fails validation until completed |
| `agent-contrib pr-body task.json [--evidence e.json --repo-dir checkout] [--closes] [--assistant TEXT] --output body.md` | A new Markdown PR description built from the contract, evidence and a fresh read-only `verify` run |
| `agent-contrib feedback 'owner/repo#PR' [--expected-head SHA]` | Read-only review state, review/issue comments and failing or pending check runs for a published PR |
| `agent-contrib inspect 'owner/repo#123' --ownership` or `agent-contrib ownership 'owner/repo#123'` | Opt-in, report-only timeline and comment signals: cross-referenced PRs, assignments, claims and possible prior fixes |
| `repository_policy` (always added by `discover`, `inspect` and `prepare`) | Report-only policy inventory and hints; never a verdict. `--ai-policy` is deprecated and ignored (one stderr notice) |
| `agent-contrib drift task.json` | Read-only report of what changed since preparation: issue, instruction files, branch, policy and open-PR overlap |
| `agent-contrib verify task.json --evidence e.json --observe-ci` | Also reports GitHub check runs and combined status for the evidence head; never changes gates or exit code |
| `agent-contrib verify task.json --evidence e.json [--repo-dir checkout] --observe-signatures` | Also reports GitHub's signature verification for the evidence head, required-signature rulesets on the base branch and local signature-header presence; never verifies locally or changes gates or exit code |
| `agent-contrib --report-budget [--min-remaining N] COMMAND ...` | Adds the core REST rate-limit budget before and after a GitHub-reading command; optionally refuses to start below N |
| `agent-contrib --cache COMMAND ...` | Reuses verified file contents at pinned commits of public repositories from the user cache; every other read stays live and output is unchanged |
| `agent-contrib instructions` | Installed workflow Markdown, CLI version, schema support and update behavior |
| `agent-contrib skill --output SKILL.md` | Canonical adapter export, CLI version and SHA-256 |
| `agent-contrib schema COMMAND` | The JSON Schema of COMMAND's JSON output; see [Output schemas](#output-schemas) |
| `agent-contrib --version` | CLI/library semantic version |

`--repo-dir` must be the Git worktree top level. `verify`, `scope-check` and
`evidence init` refuse a subdirectory or Git directory, because tree, index and
untracked-file reads there would omit the rest of the checkout. They also refuse an
index with assume-unchanged or skip-worktree entries, including any sparse
checkout, because Git status and diff would hide changes to those files. The
index is only read, never changed; clear the flags or use a full checkout.
A checkout whose effective Git config (including `include`/`includeIf` files)
sets a key a read could run as a program or use to fetch is refused with
`unsafe_git_config`: `filter.*`, `gpg.program` and `gpg.*.program`,
`diff.external`, `diff.*.command`, `diff.*.textconv`,
`extensions.partialClone`, `remote.*.promisor`, `remote.*.partialCloneFilter`
and `protocol.*`. Git reads also force `log.showSignature=false` and
`protocol.allow=never` and disable lazy fetching, so a missing object is a read
error, never a fetch. Credential, SSH, askpass, pager, editor and merge-driver
settings are not refused because none of the fixed read commands reaches them.
Reads also force full stat and mode checks (`core.checkStat=default`,
`core.trustctime=true`, `core.ignoreStat=false`, `core.fileMode=true`, and
`core.symlinks=true` on POSIX), so
relaxed checkout settings cannot hide an edit or an executable bit; on a
filesystem without executable bits every file then looks changed, which fails
closed. `core.ignoreCase=true` is refused on a case-sensitive filesystem, where
it would hide case twins, and accepted where the filesystem really ignores case.
Worktree content is compared with a commit through a fresh temporary index
outside the checkout, so the checkout's stat cache is never trusted; every
tracked file is hashed on each run. Each file's bytes must equal either the
committed blob or exactly what checkout writes for it (`cat-file --filters`,
with `core.autocrlf=false` and `core.eol=lf`). Git takes those attributes from
the checkout's `.gitattributes` files; a changed tracked one is reported as a
change, and an untracked one is always reported (even when a committed
`.gitignore` would ignore it) and is never within `scope-check` scope. So `ident`, `eol`/`text` and `working-tree-encoding` cannot hide
an edit, and an untouched checkout with those conversions stays clean. A CRLF
copy produced only by a local `core.autocrlf` reports as changed. A non-empty
`.git/info/attributes` is refused with `unsafe_git_attributes`;
`core.attributesFile` and system attributes are always ignored.

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
duplicate entry fields are unchanged. When a shared ID is a well-known standard
name such as `SHA-256` or `UTF-8`, the reason adds that it may name a standard,
not a work item. The match still blocks: spelling alone cannot tell a standard
from a project ticket such as `SHA-1234`.

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
schemas 0.1 and 0.2.

When a host-context 0.2 document carries a `draft_update` record (#21), `verify`
adds a `draft_update` report and recognizes the draft only after its one
fast-forward update (slice 2). The record's contract, mandate, credential,
repository, PR, event, interval and identity bindings must check out, else the
status is `invalid` and no publication is read. With a record present, the
draft at its creation head is never recognized. The status is then:

- `recognized`: the live PR head `P` equals the validated evidence HEAD `E`,
  `P != from_head`, and `compare from_head...P` is `ahead`. The creation head
  precedes both `from_head` and `P`, and the PR is still the one claimed open,
  unmerged draft by the bound actor, created inside the mandate interval and
  not in the future. Its complete timeline has no force-push, head-ref
  deletion or restore, close, reopen, merge, ready-for-review or
  convert-to-draft event. A final re-read equals the first and keeps the
  route. The evidence is based on the reviewed source commit exactly, has no
  merge commit in `from_head..E` and only validations started after the
  round's `issued_at`. `publication.verified` is true at `E`; completion also
  needs a final sign-off for `E` issued after the round.
- `not_evaluated`: the PR is still at `from_head`, so no update was pushed.
- `blocked`: anything else, with the reasons in `errors`.

Every comparison must be internally consistent (status, commits and counters),
or it blocks. `candidate_head` is `E` exactly when the status is `recognized`,
else `null`; `live_head` is the PR head of the first complete read, or `null`.
The record may have expired after the push; `current` reports whether its
interval contains the verification time, judged after every read. Pre-push
readiness is not evaluated: no `next_action` asks for an update or a push, and
nothing here authorizes a push. Without the section the output is unchanged.
See [host authorization](host-authorization.md#draft-update-rounds-host-context-02).

With a host-context 0.2 document, `verify` adds `overlap_dispositions` and
`waived_duplicates`. The status is:
- `absent`: no record;
- `invalid`: a schema, binding or expiry error. Nothing is waived. A record
  rejected on its own checks makes no extra read, but one that expires during
  the reads becomes `invalid` only after them;
- `evaluated`: the record's contract, mandate, credential, event, interval and
  entry bindings check out.

For an `evaluated` record, `verify` reads each disposed PR (`pulls/{n}`) and each
distinct base-branch tip (`git/ref/heads/{ref}`): at most 20 PRs and 20 refs. It
recomputes the match and reconciles it with the open-PR scan. It removes a PR
from the blocking lists only when all of these hold:
- the scan was complete;
- the match is the same topical one (never a direct reference);
- the author is not the credential actor;
- every bound observation is equal (ID, URL, repository, author, state, draft,
  head repository and SHA, `updated_at`, title/body/ref hash and base tip);
- the record is still unexpired after all reads.

A direct reference, contradiction or failed read seen in that read blocks. A
direct reference first seen there is also added to `duplicates` with
`observed_in: "disposition_read"`; a failed read is a blocker only, never a
claimed overlap. A waived PR stays in `duplicates`. Waivers never remove any other blocker; text
output names them. A record that expires during the reads fails every stage
closed. Library callers may pass host context explicitly to `core.verify`;
that is the same host-asserted boundary as the CLI, not a privileged API.

## Authorization request

`authorization-request task.json` makes the same GitHub reads as `verify
task.json` without host context, writes no file and reads no stdin. It first
validates the full task 0.2 schema: a schema 0.1 or unknown version is a usage
error (exit 2), and an invalid contract returns `error.code: invalid_contract`
with `schema_errors` and no template (exit 1), before any read; the payload is
identical with `--report-budget`, which takes no budget snapshot in that case.

The output has `issued: false`, `contract_sha256`, `mandate_fields`,
`human_only_fields`, `requested_actions`, `unresolved_fields`, `preflight_errors` and
`ready_for_issuance` (exit 0 only when true). In a ready request the `null`
leaves of `mandate_fields` are exactly `human_only_fields`: a ready request
still awaits the host for every one of them. `requested_actions` repeats the
contract's actions; the host chooses `mandate_fields.actions`. When identity or
permission reads fail, `credential_actor_id` and `authority` are also `null` and
listed in `unresolved_fields`, which names only these derived fields; only fresh
trusted reads resolve them. Text output shows the requested actions, any
unresolved derived fields and the human-only fields.
`preflight_errors` omit the blockers that exist only because no mandate exists
yet. They are untrusted diagnostics and may contain repository-authored paths.

The request deliberately contains no scope, path, objective, criteria or
validation summary. The host renders the complete contract from the file it
hashes, issues the record, and the worker relays it unchanged. The request is not
host context: piping it to `verify --host-context-stdin` fails schema validation.

## Offline contract lint

`lint task.json` reads one contract and nothing else. It validates it against
the bundled task schema for its `schema_version` (unknown versions fail), and
for a schema-valid contract it applies the same reviewed-contract rules that
`verify` checks: reviewed status with no open questions, required fields,
concrete repository-relative scope, unique IDs, a definition of done covering
every criterion and validation, complete prepared discovery and satisfied
prerequisites. `reviewed` (and exit 0) means only that the contract is ready
for `verify`. It says nothing about the live issue, approval, overlap,
authorization or evidence, and it never runs validation argv.

## Offline scope check

`scope-check` evaluates the working diff against the contract's
`scope.allowed_paths` and `scope.prohibited_paths` with the same function that
`verify` uses for evidence. It reads only the local checkout: committed changes
from `--base` (default: `source.commit`) to HEAD, staged and unstaged changes,
and untracked files that are not ignored. Only per-directory `.gitignore` files
count as ignore rules; `.git/info/exclude` and `core.excludesFile` never hide a
file, and an untracked `.gitignore` is always reported. Files ignored by a
committed `.gitignore` are not reported (`verify` and `evidence init` apply the
same rule). Renames report both paths. The base
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
still fails. When the default base is an ancestor but more than one commit
behind HEAD and out-of-scope paths changed, `warnings` names the base, the
commit count and suggests `--base`; the violations and exit status are
unchanged. It makes no GitHub calls, so it can run as a pre-commit hook. Exit 0
means "no scope violation found", not evidence, readiness or authorization.
Each violation names the path and either the first matching prohibited pattern
or `not in allowed_paths`.

A changed path that is a symlink is also judged by its target, the same way in
`verify` and `scope-check`. The target comes from the commit, the index or the
worktree that holds the link, read without following it. It is resolved
lexically from the link's directory, expanding every link hop, including links
to directories, up to 40 hops. The link is a violation, with the reason as its
rule, when the target is absolute (`/x` or `C:/x`), contains a backslash,
escapes the repository, points at the repository root, is longer than 4096
bytes, contains a NUL byte, is not valid UTF-8, cannot be read (for example a
permission error on a hop), loops, or resolves to a path outside `allowed_paths` or matching
`prohibited_paths` (for example `symlink to AGENTS.md: not in allowed_paths`).
A link to an allowed file passes; a scope pass does not prove the target exists.
Git records no path beyond a symlink, so a
file written through a linked directory appears at its real path and is judged
there.

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
  never falls back to a shorter prefix. Single names (`signals`), names inside
  paths, names of more than 16 segments or longer than 300 characters (as a
  slash path), and a name cut off by the 64 KiB scan limit are refused whole;
  a name is never shortened to fit. Names are matched on regular-expression
  word characters (letters, digits and `_` in any script), so `äpkg.mod`
  resolves as a whole and `pkg.mod` inside it is never resolved on its own. A
  name containing other identifier characters, such as combining marks, `℘` or
  `·`, is refused; its fragments are never resolved either.
  Path and file-name matches come first and the same limit of 20 applies.
  `named_paths_missing` lists repository-relative file paths the issue names
  (`docs/x.md`, `./src/a.rs`, `.github/ci.yml`; a last segment with an
  extension) that the snapshot tree does not contain, at most 20 in order of
  appearance. The named path is compared exactly: unlike hints, an existing
  suffix (`src/a.rs` for `old/src/a.rs`) does not count. It is a heuristic, not
  a URL parser; it skips absolute paths, ordinary URLs, domains, `..` traversal and
  tokens cut at 300 characters, and it is empty when the tree is unknown. It is a
  staleness cue only: it does not change `value`, `score` or ordering.
- `acceptance_clarity`: `high`, `medium` or `low` from checklists,
  expected/actual sections, reproduction steps and code blocks.
- `activity`: age and last-update days, comment and reaction counts from the
  issue list payload; malformed fields are `null`.
- `maintainer`: whether the issue author's association is OWNER, MEMBER or
  COLLABORATOR.
- `labels`: the issue's label names (sanitized, at most 100).
- `demotion`: documented, report-only demotions with one reason each. A label
  matches a phrase when the phrase's words appear as whole words in the
  lower-cased label name, with punctuation and separators read as spaces
  (`Status: On-Hold` matches `on hold`; `blockedness` matches nothing). Each
  group counts once:
  - on hold or deferred: `icebox`, `on hold`, `blocked`, `deferred`,
    `postponed`, `frozen`;
  - needs a decision or design discussion: `needs decision`, `needs design`,
    `needs discussion`, `discussion`, `question`, `rfc`, `proposal`;
  - not planned or not this project: `not planned`, `out of scope`,
    `upstream`, `third party`, `wont do`;
  - major-version or breaking-change bucket: only an explicit bucket, where the
    label or its last `:` or `/` part is exactly `breaking`, `breaking change`,
    `breaking changes`, `vN` or `vN.x` (`v5`, `kind/breaking`, `target: v6`).
    `non-breaking`, `v5-compat` and `bug: v5 regression` are not buckets.
  A phrase right after `non`, `not`, `no` or `un` does not match, so
  `not blocked` and `no discussion needed` are not demotions.
  A title counts as meta-like when it starts with `meta`, `wip`, `tracking`,
  `tracker`, `roadmap`, `rfc`, `umbrella` or `epic` followed by `:`, `]`, `)` or
  `-`, or contains `meta issue`, `tracking issue`, `umbrella issue`, `roadmap`
  or `features list`. These rules come from dogfood evidence where icebox'd,
  maintainer-reserved `v5`, question-labelled and tracking issues ranked first.
  They are heuristics: a label can be stale, and titles can mislead.
- `score`: one point for found locations, up to two for clarity, one for a
  maintainer author unless the title is meta-like, minus two per demotion,
  never below zero.

`--check-top N` (1-5, with `--signals` and one repository) then reads the
existing ownership signals (as `inspect --ownership`) for only the top N
candidates. Each check reads the first timeline and comment page and at most 4
cross-referenced PR details, and all checks together make at most 30 reads.
Each read is one GitHub GET with no retry, so a transient failure marks the
check incomplete instead of making extra requests.
Reaching a cap, or a failed read, marks that check `complete: false`, and an
incomplete `top_check` exits 1. A checked issue is demoted when it has a
merged same-repository PR that references it exactly ("possibly already
fixed") or a current assignee. Claim comments never demote: comment prose is
untrusted and easy to misread (quoted instructions, code examples, other
issues), so claims stay visible only in the report-only `inspect --ownership`
output. A demoted issue then moves below every other candidate that is not
excluded or overlapping (known bad below unknown); relative order is otherwise
kept and issues below the top N are never read. Each
demotion is listed in the issue's `top_check.demotions`. No maintainer
"reserved" or "rejected" detector exists, so none is used. A clean or
incomplete check proves nothing, gates and overlap are unchanged, and the
reads appear in `--report-budget`. In live runs with N=5 it made 13-18 reads
and demoted ripgrep #2528 and hono #1018, both judged bad by that evaluator, to ranks 59 and 183.
Precision@5 stayed 1/5, 1/5 and 0/5 for click, ripgrep and hono: the issues
that moved up (ripgrep #1221, hono #2649) were judged bad too.

`tests/test_ranking_eval.py` replays a frozen dogfood-2 snapshot (public titles,
labels and signal inputs for click, ripgrep and hono, with the dogfood
evaluator's judgements; the evaluator was a model, Claude Opus 5.5, and no
separate human review was done) and checks precision@5 and the ranks of known bad labelled or meta issues offline.
The demotions move those issues out of the top ranks but do not raise
precision@5 on that snapshot (click 1/5, ripgrep 1/5, hono 0/5 before and
after): most remaining false candidates are design debates, already fixed or
not this project's bug, with no label or title cue.

Ordering stays exclusions first, then overlaps; with `--repo-dir` or
`--check-top` the next key is known-bad issues (locally referenced or demoted by
the check), which rank below every other candidate. Then low success likelihood;
only then does a higher `score` come first, with the issue number as the final
tie-breaker. Signals are heuristics. They never approve, authorize or replace
reading the issue.

`discover owner/repo --repo-dir CHECKOUT` (one repository) adds a report-only
`local_work` object for unpublished local work. It lists the issue numbers
referenced as `#N` or `owner/repo#N` (the source repository only)
in the messages of commits reachable from the checkout's HEAD but not from the
snapshot's source default-branch commit. It lists the newest 500 commits at most,
checks each commit object's size before reading any message, and reads only
whole messages: a commit larger than 64 KiB is skipped, and reading stops once
messages would exceed 4 MiB in total. Reads use the hardened Git reader after the
worktree-root and checkout-config checks. A missing base commit (the CLI never
fetches), a shallow checkout (a shallow boundary can hide commits), an unsafe
config, a subdirectory, more than 500 commits, a skipped message or a message
containing a NUL byte make it incomplete, which exits 1. Messages are read from
the raw commit objects (`git cat-file --batch`), never reformatted, and commit
headers such as the author are not parsed. With `--signals`, each issue gets `signals.local_work`
(`referenced`, `none` or `unknown`), and a referenced issue ranks below every
other candidate that is not excluded or overlapping. Its score, gates and
exclusions are unchanged. Without `--signals` the issue order is unchanged. A
reference is not proof that the work is done.

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
  or entry is malformed (including a missing `merged_at` field, a merge time
  outside the PR's creation-to-close interval, or a missing or repeated PR
  number), or discovery did not complete
  its source snapshot (then nothing is read).

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
repository, repository ID, number, sanitized `title`, `base_ref`, state, draft, merged,
merge/close times and `exact_reference`: whether the PR text references this issue exactly (local
`#N` only in the issue's own repository, `owner/repo#N` or the issue URL), with
the same parser as overlap detection.

- `resolution_signals.possibly_already_fixed`: merged PRs with an exact
  reference whose base repository is the issue's own repository (any base
  branch; check `base_ref`). `downstream_references`: merged PRs with an exact
  reference in other repositories, such as downstream workarounds; they never
  indicate a fix. `rejected_approaches`: closed, unmerged PRs with an exact reference.
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

## Repository policy report (default-on, report only)

`discover` (once per repository), `inspect` and `prepare` add `repository_policy`
in the CLI output. The report changes no core result, contract field,
`instructions_sha256` or exit code. Separately, `prepare` now writes a pending
`ai-policy-review` prerequisite into new contracts; existing contracts are unchanged. `--ai-policy` is deprecated: it is
accepted, changes no output or exit status, and writes one notice line to stderr (best effort: a missing,
closed or readerless stderr changes nothing). The earlier unreleased `ai_policy` excerpts and
the `agent_contribute.aipolicy` module no longer exist.

- **Inventory.** The issue source repository (never a requested fork) at the
  observed commit. It covers the loaded instruction files plus policy-named
  files at any depth. A name matches when it equals a prefix or continues it
  after `.`, `-`, `_` or a space, case-insensitively: `contributing`,
  `contribute`, `ai`, `llm`, `agents`, `claude`, `gemini`,
  `copilot-instructions`, `pull_request_template`, `code_of_conduct`,
  `code-of-conduct`, `security`, `support`, `governance`, and a root `readme`.
  So `CONTRIBUTING.en.md`, `AI_USAGE_RULES.md`, `SECURITY-POLICY.md` and
  `README.development.md` all match. Also matched: `.cursorrules`,
  `.cursor/rules/*`, `llms.txt`, `.github/PULL_REQUEST_TEMPLATE/*`, and files
  under `contributing/`, `contributors/`, `contribute/`, `policy/` or
  `policies/` directories.
  - Paths are classified in full and displayed shortened to 500 characters,
    with `path_truncated`.
  - Core instruction paths of 500 or more characters may already have been
    shortened, so they are listed as an unresolved identity.
  - The owner's `.github` repository (root, `.github/`, `docs/`) is read at its
    default-branch commit. Contents are read by commit SHA, and the decoded
    bytes must hash to the tree's Git blob SHA.
- **Formats.** `.md`, `.markdown`, `.rst`, `.txt` and extensionless files are
  scanned. Other document formats with a policy name (`.adoc`, `.pdf`, `.html`,
  `.docx`, `.odt`, `.org`, `.textile`, `.rtf`, `.mdx`) are listed in
  `unassessed` as `unsupported format`. Code, data and image files are not
  policy candidates.
- **`sources_scanned`.** Origin, repository, path, commit, SHA-256 of the file
  bytes, scan kind, and notes such as `paragraphs with non-Latin script not
  assessed: N`. The vocabulary is English only.
- **`unassessed`.** Policy-like links from any scanned file, including READMEs
  (`referenced, not assessed`; links to a scanned file at the same revision are
  omitted). Also unsupported formats, failed reads, an owner `.github`
  repository that is `not found or inaccessible` (never "absent"), and content
  that did not match the pinned tree entry.
- **`hints`.** Attention labels, not classifications:
  - `possible_agent_restriction`, `possible_ai_restriction` and
    `possible_pr_restriction`: an agent/automation, AI or pull-request term
    within 12 words of a restriction word.
  - `ai_mention`: any AI or agent term.

  Paragraphs are joined across wrapped lines, and headings are kept as context.
  HTML comments are scanned, and entities, tags, fullwidth forms and zero-width
  characters are normalized. Adding sentences or paragraphs before or after a
  passage never removes its hint kinds. Inserting words between the matched
  terms can move them out of the 12-word window, and so can added text that
  turns an existing line into a heading. Excerpts are sanitized and at most 300
  characters.
- **`limits_reached` and `reads`.** At most 25 logical GitHub requests per
  report (each with the client's usual three attempts), 12 source and 8 owner
  policy files, 200 kB per file and 1 MB scanned, all counted in UTF-8 bytes. The report keeps 100 hints,
  50 unassessed entries and 256 kB serialized, and identifiers are truncated
  with `what_truncated`. Anything dropped is counted in `limits_reached`. To
  fit the size bound, hints go first, then unassessed entries, then long source
  paths are shortened, and finally source records are left out. Each step is
  recorded as a `report size: ...` limit.
- **Identity.** Every source, omitted candidate and unassessed entry has
  `identity_sha256`, a hash of its original repository and path (or URL) as
  read from GitHub. Displayed paths can be shortened (`path_truncated`,
  `what_truncated`) or sanitized of control and format characters
  (`path_sanitized`, `what_sanitized`), so two entries can look alike. The
  identity, not the display text, is what deduplication and `inventory_sha256`
  use.
- **`omitted_sources` and `hides_sources`.** A policy candidate that a file,
  byte or request limit left unread is named in `omitted_sources` (at most 50,
  with its repository, path, kind and reason; overflow is counted). Each
  `limits_reached` entry says whether it `hides_sources`; hint limits do not.
  `limits_hide_sources` is true when any limit hides a source or reference. The
  workflow then treats repository policy as unresolved until every omitted
  candidate is read manually or shown inapplicable.
- **`never_inspected`.** A fixed list: wikis, external websites, images and PDFs,
  comments, other repositories, non-Latin text.
- **`inventory_sha256`.** A hash of the scanned sources' bytes, the retained
  unassessed identifiers and the limits. It excludes commit SHAs, so unrelated
  pushes do not change it. No verifier checks it; the workflow records it in
  prerequisite `ai-policy-review`.

There is deliberately no `coverage`, `complete` or `clear` field. Hints are
noisy on purpose. The installed workflow's mandatory policy review decides what
they mean, and that review is not verifier-enforced.

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

## Required CI checks (schema 0.2 completion, opt-in)

A reviewed schema 0.2 contract may declare `ci_requirements`: 0 to 20 unique
`{"check": NAME, "app_id": N}` pairs. `check` is 1 to 200 characters without
control or format characters, and `app_id` is a positive integer. A non-empty list
needs `create_draft` in `execution.requested_actions`. An absent or empty list
changes nothing: no reads, no output, no blocker.

With requirements, once an exact-head published draft is verified, `verify` reads
every check suite and then every check run (`filter=all`) for the evidence
`git_head`, within a 50-request budget. It adds `ci_gate`. A requirement is `met`
only when all of these hold:

- every check run whose raw name is exactly `check`, from app `app_id`, on that
  head, is completed with `success`;
- every check suite of that app on the head is completed;
- at least one such run exists;
- both reads are complete, consistent and cover fewer than 1,000 suites.

There is no latest-attempt selection: a retained failed attempt blocks even if a
retry succeeded. Other states, decided in this order:
`unknown` (incomplete or inconsistent reads, the suite window, an exhausted
budget), `failed`, `not_met` (neutral or skipped), `pending` (an unfinished run,
`action_required`, or an unfinished suite of that app, such as after a
rerequest), and `missing`. Same-name runs from other apps are counted, never
accepted, and commit statuses never count.

A contract with requirements also cannot complete when the implementation diff
touches `.github/` (additions, deletions and renames). Every gate blocker appears
only in `stage_blockers.completion`; the implementation and draft gates and the
`--observe-ci` report are unchanged. The gate observes the results GitHub
currently retains for that head. It does not prove which tree a job checked out,
and it never replaces review or final sign-off. Design:
[docs/design/2026-11-03-ci-gating.md](design/2026-11-03-ci-gating.md).

## Signature observation (opt-in, report only)

`verify ... --evidence evidence.json [--repo-dir checkout] --observe-signatures`
adds `signature_observation` after the verify decision and exit code are fixed.
It is added only for a schema-valid contract and never changes any gate,
`next_action` or the exit status. The repository is the contract's target, or
the source when the target is blank. It has three parts:

- `github_verification`: one `GET repos/{target}/git/commits/{git_head}`. It
  reports `verified`, `reason` and `verified_at` from GitHub's verification
  object. A reason outside GitHub's documented set is `unrecognized` and is not
  echoed; the signature, payload and message are never copied. `verified` must
  agree with a `valid` reason. `verified_means` states what it shows: GitHub
  matched the signature to a key registered to an account. That is not
  approval, authorship, review or proof that tests ran. A head not yet pushed to
  the target cannot be observed and is reported as a failed read.
- `required_signatures`: every page of `GET
  repos/{target}/rules/branches/{base}`, where `base` is the contract's
  `execution.base_ref` or else `source.default_branch`. `required` is true when
  an active ruleset rule of type `required_signatures` applies, and
  `ruleset_ids` lists those rulesets. `false` means only that no visible active
  ruleset requires signatures. Each rule type must be one of GitHub's documented
  lowercase rule types. A malformed type makes the part unknown. So does a
  well-formed but unrecognized type, unless an exact `required_signatures` rule
  is also present. `classic_branch_protection` is always
  `not_observed`, because reading it needs admin access, and ruleset bypass
  actors are not visible either.
- `local_commits` (only with `--repo-dir`; otherwise `not_requested`): the
  commits in evidence `base_commit..git_head`, oldest first, each with
  `signature_header: present` or `absent`, plus counts. This is header
  presence, not validity; anyone can write a forged header. First the checkout's
  effective Git configuration is checked, as for every checkout reader; config
  a read could run as a program or use to fetch (signature programs, filters,
  promisor remotes, protocol settings) makes the part incomplete before any other
  read. Then only `rev-parse --is-shallow-repository`, `merge-base`, `rev-list`
  and `cat-file` run, through the hardened Git reads, which never lazy-fetch. No signature
  program runs: no gpg, ssh-keygen, `verify-commit` or `--show-signature`, so
  repository-configured programs are never executed. The base must be a full SHA
  and an ancestor of the head. A shallow repository is reported as incomplete,
  because its boundary can silently cut the range even when the base is
  reachable through a merge. More than 1000 commits is also reported as
  incomplete; the list is never truncated.

Any failed, partial or malformed read makes that part, and the observation,
`complete: false` with fixed error strings. Contract-required verified heads and
signed evidence attestations (the rest of #18) are not implemented.

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
files and schema-invalid `drift`/`pr-body`/`authorization-request` contracts
cause no GitHub read.
`verify` still reports schema and evidence failures in its normal result envelope;
optional budget reads do not turn those failures into success. `--min-remaining N` refuses to start (error `rate_limit_budget`, exit 1)
when the budget is unknown or below N, before any command read. The CLI does not
estimate a command's cost; choose N yourself. Offline commands reject the flag
(see "Global options on offline commands").
Without the flag, no rate-limit read happens and output is unchanged.

## Content cache (opt-in)

`--cache` before a command reuses file contents that GitHub returned for a
pinned commit, so repeated `discover`, `inspect`, `prepare`, `verify` and
`drift` runs skip re-reading the same instruction and policy files. The cache is
content-addressed and self-verifying, and it never changes output, gates or exit
status.

- Only `repos/{owner}/{repo}/contents/{path}?ref={40-hex commit}` reads are
  served from it, and only for a repository whose live metadata earlier in the
  same command said both `"private": false` and `"visibility": "public"`. Private, internal or unobserved
  repositories always read live.
- The expected Git blob SHA for the path comes from the **live** recursive tree
  read at that commit. Trees, metadata, issues, PRs, labels, permissions, branch
  heads, comparisons, checks and every other read are never cached.
- Entries are the decoded file bytes, named by blob SHA. A stored response must
  carry that SHA and hash to it. Every hit recomputes the Git blob hash
  (SHA-1 of `blob <length>\0<bytes>`) and must match the live tree; a
  mismatching, oversized, symlinked, foreign-owned or non-regular entry (such
  as a FIFO, opened nonblocking) is deleted and read live. Identical files at different paths share one entry.
- The directory is `$XDG_CACHE_HOME/agent-contrib` (an absolute
  `XDG_CACHE_HOME`), otherwise `~/.cache/agent-contrib`.
  - It is opened once by walking every component of the absolute path from `/`
    without following symlinks: a symlink anywhere in the path disables the
    cache. Ancestors must already exist; only the cache directory itself is
    created (0700), after every ancestor passed.
  - The configured path is read lexically. `os.path.abspath` collapses `..`
    before the walk, so `a/link/../c` means `a/c`, even where a shell following
    `link` would land elsewhere.
  - Every ancestor must be owned by root or by you, and not group- or
    other-writable. The only exception is a root-owned sticky directory, such
    as `/tmp`. Ancestors you own must carry no POSIX ACL.
  - The cache directory itself must be yours, mode exactly 0700, with no POSIX
    ACL.
  - Any doubt disables the cache for that run; it is never an error and, by
    design, prints no diagnostic, so output stays identical. If warm runs never
    get faster, check these rules for your `XDG_CACHE_HOME`. Platforms
    without `os.listxattr`, where ACLs cannot be ruled out, disable it too.
  - **Default Ubuntu homes disable the cache:** umask 002 makes `~/.cache`
    0775. To enable it, point `XDG_CACHE_HOME` at a private 0700 directory, for
    example `mkdir -m 700 ~/.agent-contrib-cache` and then
    `XDG_CACHE_HOME=~/.agent-contrib-cache agent-contrib --cache …`. Every
    ancestor of that directory must meet the rules above.
  - Every read, write, rename, scan and delete then works relative to that
    open directory, so renaming or replacing its name afterwards cannot
    redirect them.
  - Writes are atomic and private (0600), and eviction touches only valid
    entry names and the CLI's own temporary files. A temporary file older than
    one hour, left by a crashed store, is removed. Younger ones count toward the
    total but are never deleted, since they may belong to a concurrent store.
  - Without POSIX ownership checks or `dir_fd` support, the cache is bypassed.
- Entries are at most 8 MiB. After each store the total is brought under
  256 MiB by deleting the oldest entries. Entries another invocation removes
  meanwhile are skipped, so concurrent commands may exceed the total briefly,
  but once they finish the last eviction pass has seen every stored entry. Delete the directory to clear it; any cache error falls back
  to the live read.
- `--report-budget` counts only the live reads that remain. The cache is active
  for one invocation; library callers never inherit it.
- Offline commands reject `--cache`, as they reject `--report-budget`.

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
It is a summary: discovery shows at most 20 issues per repository, each with its
overlapping-PR count, whether it is excluded and (with `--signals`) its score,
followed by overlapping and excluded counts over all issues; lists show at
most 50 entries and long remote lines are shortened. Omitted list entries are
counted. Discovery adds one line each for `--responsiveness` and `--repo-dir` local
work when requested. Multi-repository discovery includes every repository's completeness and
errors. Verification shows the gates and blockers. With an explicit
`verify --stage X`, text starts with stage X, its exit gate and its blockers;
the other stages appear only as blocker counts, because they do not decide that
exit. When schema validation fails before any stage is evaluated, the stage
line reads `not evaluated; see Errors` and the schema errors follow. JSON still
contains every stage. `scope-check` lists each violating path
and rule, warnings and errors. `drift` lists the reasons that set `drifted`, then
informational changes (an advanced default branch, PRs no longer open) apart.
`authorization-request` shows whether the request is ready for issuance, that it
is unsigned and grants nothing, the contract hash, and each preflight error and
unresolved field. `instructions` prints a version line and then the
workflow Markdown unchanged, so it can be read without unwrapping JSON. Other
commands show top-level scalar fields; use JSON for full nested results, instructions and provenance.
Remote text is sanitized to a single line so it cannot add fake gate headings.
Default JSON bytes are unchanged. Parse-time usage errors still use structured
JSON when argument parsing has not produced a valid format selection.
A global option (`--format`, `--report-budget`, `--min-remaining`, `--cache`) placed after
the subcommand is still a usage error (exit 2); its message says to move the
option before the subcommand.

### Global options on offline commands

`instructions`, `schema`, `skill`, `lint`, `scope-check` and `evidence init`
never read GitHub. On them `--report-budget` and `--cache` are both usage errors
(exit 2, "`--cache` applies only to commands that read GitHub", and likewise for
`--report-budget`), checked before any file is read; `--min-remaining` already
requires `--report-budget`. `--format` applies to every command.

The text option uses the same stdout handling as JSON. Closed output returns 1
quietly; writable output retains the command's normal exit status.

## Output schemas

Every command's JSON output has a packaged JSON Schema (draft 2020-12 subset).
`agent-contrib schema COMMAND` prints it; `error` is the error envelope that
replaces any command's result on a usage, input or protocol error, and
`evidence-init` is `evidence init`. `instructions` reports the
`output_schema_version` (currently `1`) and the package directory. Objects are
closed: a field is required unless marked optional, and fields not listed never
appear. Output values do not carry the schema version; a shape change bumps the
version together with the CLI's semantic version and changelog. Remote text in
fields named `untrusted_*` and in instruction files stays untrusted data.

The reference below is generated from the schemas; a test fails when it drifts.

<!-- output-reference:start (generated by tools/output_reference.py; do not edit) -->

### `audit`

`agent-contrib schema audit` · Read-only maintainer report of what an agent sees in a repository.

One of `audit_report`, `audit_unread`.

### `authorization-request`

`agent-contrib schema authorization-request` · Unsigned mandate request pre-filled from a schema 0.2 contract; it is not a mandate and grants nothing.

| Field | Type | Description |
| --- | --- | --- |
| `kind` | "agent-contrib/authorization-request" |  |
| `request_version` | "0.1" |  |
| `issued` | false |  |
| `notice` | string |  |
| `target_host_context_schema_version` | "0.1" |  |
| `ready_for_issuance` | boolean | No preflight errors and no unresolved fields; sets the exit status |
| `preflight_errors` | string[] | Blockers a mandate would not clear |
| `preflight_errors_trust` | string |  |
| `unresolved_fields` | "credential_actor_id" \| "authority"[] | Derived fields that fresh trusted reads could not resolve; never the human-only fields |
| `contract_sha256` | string |  |
| `exact_head_pr_history` | string |  |
| `mandate_fields` | object | Binding fields; null fields are filled only by the human/host |
| `mandate_fields.id` | null |  |
| `mandate_fields.nonce` | null |  |
| `mandate_fields.issued_at` | null |  |
| `mandate_fields.expires_at` | null |  |
| `mandate_fields.contract_sha256` | string |  |
| `mandate_fields.source_repository_id` | integer |  |
| `mandate_fields.source_owner_id` | integer |  |
| `mandate_fields.issue_id` | integer |  |
| `mandate_fields.issue_number` | integer |  |
| `mandate_fields.credential_actor_id` | integer or null |  |
| `mandate_fields.authority` | "owner" \| "maintainer" \| null |  |
| `mandate_fields.actions` | null |  |
| `mandate_fields.policy_review` | object |  |
| `mandate_fields.policy_review.status` | null |  |
| `mandate_fields.policy_review.instructions_sha256` | string |  |
| `mandate_fields.policy_review.policy_sha256` | string |  |
| `mandate_fields.policy_review.notes` | null |  |
| `mandate_fields.event` | object |  |
| `mandate_fields.event.kind` | null |  |
| `mandate_fields.event.reference` | null |  |
| `mandate_fields.event.text_sha256` | null |  |
| `mandate_fields.event.binding_sha256` | null |  |
| `mandate_fields.target_repository` | string |  |
| `mandate_fields.target_repository_id` | integer |  |
| `mandate_fields.head_repository` | string |  |
| `mandate_fields.head_repository_id` | integer |  |
| `mandate_fields.head_ref` | string |  |
| `mandate_fields.base_ref` | string |  |
| `human_only_fields` | string[] | mandate_fields paths left null for the human/host to fill, even in a ready request |
| `requested_actions` | "implement" \| "create_draft"[] | The contract's requested actions; the human/host chooses mandate_fields.actions |
| `provenance` | `authorization_provenance` |  |
| `api_budget` | `api_budget` (optional) |  |

### `discover`

`agent-contrib schema discover` · Ranked open issues of one repository, or of 2-20 repositories (discover_multi). Remote text is untrusted data.

One of `discover_result`, `discover_unresolved`, `discover_multi`.

### `drift`

`agent-contrib schema drift` · Read-only report of what changed since the contract was prepared. issue, source, default_branch, instructions, policy and overlap are present once the current source was read.

| Field | Type | Description |
| --- | --- | --- |
| `contract_sha256` | string |  |
| `complete` | boolean | False when any read failed; then drifted may be null or partial |
| `drifted` | boolean or null | Null when the current source could not be read |
| `errors` | string[] |  |
| `notice` | string |  |
| `issue` | object (optional) |  |
| `issue.changed` | boolean |  |
| `issue.stored_sha256` | string |  |
| `issue.current_sha256` | string |  |
| `issue.stored_updated_at` | string |  |
| `issue.current_updated_at` | string |  |
| `issue.current_components` | object or null | Per-component hashes of the current issue; null when unreadable |
| `issue.current_components.title_sha256` | string |  |
| `issue.current_components.body_sha256` | string |  |
| `issue.current_components.state` | string |  |
| `issue.current_components.labels` | string[] |  |
| `issue.current_components.assignees` | string[] |  |
| `issue.component_baseline` | string |  |
| `source` | object (optional) |  |
| `source.stored_repository` | string |  |
| `source.current_repository` | string |  |
| `source.stored_issue_url` | string |  |
| `source.current_issue_url` | string |  |
| `source.changed` | boolean |  |
| `source.stored_identity` | object (optional) | Schema 0.2 contracts only |
| `source.stored_identity.repository_id` | integer |  |
| `source.stored_identity.owner_id` | integer |  |
| `source.stored_identity.issue_id` | integer |  |
| `source.current_identity` | object or null (optional) | Schema 0.2 contracts only; null when unresolved |
| `source.current_identity.repository_id` | integer |  |
| `source.current_identity.owner_id` | integer |  |
| `source.current_identity.issue_id` | integer |  |
| `default_branch` | object (optional) |  |
| `default_branch.stored_branch` | string |  |
| `default_branch.current_branch` | string |  |
| `default_branch.stored_commit` | string |  |
| `default_branch.current_commit` | string |  |
| `default_branch.advanced` | boolean |  |
| `default_branch.note` | string |  |
| `instructions` | object (optional) |  |
| `instructions.changed` | boolean |  |
| `instructions.baseline_verified` | boolean |  |
| `instructions.added` | string[] |  |
| `instructions.removed` | string[] |  |
| `instructions.modified` | object[] |  |
| `instructions.modified[].path` | string |  |
| `instructions.modified[].stored_sha256` | string |  |
| `instructions.modified[].current_sha256` | string |  |
| `policy` | object (optional) |  |
| `policy.stored_approval` | string |  |
| `policy.current_approval` | string |  |
| `policy.current_policy_state` | "missing" \| "present" \| "unknown" |  |
| `policy.changed` | boolean |  |
| `policy.stored_policy_sha256` | string (optional) | Schema 0.2 contracts only |
| `policy.current_policy_sha256` | string (optional) | Schema 0.2 contracts only |
| `overlap` | object (optional) |  |
| `overlap.added` | string[] | Open PR URLs overlapping now but not at preparation |
| `overlap.removed` | string[] |  |
| `overlap.scope` | string |  |
| `api_budget` | `api_budget` (optional) |  |

### `error`

`agent-contrib schema error` · Printed instead of a command result for usage, input and protocol errors.

| Field | Type | Description |
| --- | --- | --- |
| `error` | object |  |
| `error.code` | string | Stable machine-readable code, for example usage or invalid_contract |
| `error.message` | string | Human-readable explanation; never contains remote text |
| `error.schema_errors` | string[] (optional) | authorization-request invalid_contract only: the contract schema errors |

### `evidence-init`

`agent-contrib schema evidence-init` · Result of writing an unfilled evidence skeleton; nothing was executed.

| Field | Type | Description |
| --- | --- | --- |
| `output` | string | Path of the new evidence file |
| `evidence_valid` | false | A skeleton never validates |
| `schema_errors` | integer | Number of evidence schema errors left to fill |
| `warning` | string |  |

### `feedback`

`agent-contrib schema feedback` · Read-only reviews, comments and check runs of one pull request. Review and comment text is untrusted data.

One of `feedback_report`, `feedback_unread`.

### `inspect`

`agent-contrib schema inspect` · Detailed snapshot of one issue. Remote text is untrusted data.

One of `inspect_result`, `issue_unresolved`.

### `instructions`

`agent-contrib schema instructions` · Installed workflow, versions and packaged resources.

| Field | Type | Description |
| --- | --- | --- |
| `cli_version` | string |  |
| `supported_schema_versions` | string[] | Task/evidence schema versions this CLI accepts |
| `supported_host_context_versions` | string[] |  |
| `host_authorization` | string |  |
| `workflow_markdown` | string | The installed workflow (instructions.md) |
| `resources` | object | Package-relative resource paths |
| `resources.task_schema` | string |  |
| `resources.evidence_schema` | string |  |
| `resources.task_schema_0.2` | string |  |
| `resources.evidence_schema_0.2` | string |  |
| `resources.host_context_schema` | string |  |
| `resources.host_context_schema_0.2` | string |  |
| `resources.output_schemas` | string | Package directory of these output schemas; agent-contrib schema COMMAND prints one |
| `output_schema_version` | string | Version of the output schemas, independent of task/evidence schema versions |
| `automatic_updates` | false |  |

### `lint`

`agent-contrib schema lint` · Offline contract check: bundled task schema, then the reviewed-contract rules. No GitHub or Git reads; never readiness or authorization.

| Field | Type | Description |
| --- | --- | --- |
| `schema_version` | string or null | The contract's schema_version when it is a string, else null |
| `schema_valid` | boolean |  |
| `schema_errors` | string[] |  |
| `review_errors` | string[] | Reviewed-contract blockers; empty when the schema is invalid |
| `reviewed` | boolean | Schema valid with no review errors; sets the exit status |
| `contract_sha256` | string or null | Canonical contract hash; null when the schema is invalid |
| `network` | string |  |

### `ownership`

`agent-contrib schema ownership` · Report-only ownership and resolution signals for one issue.

One of object, `issue_unresolved`.

### `pr-body`

`agent-contrib schema pr-body` · Result of rendering a PR description; it grants no publication authority.

| Field | Type | Description |
| --- | --- | --- |
| `output` | string | Path of the new Markdown file |
| `sha256` | string | SHA-256 of the rendered body |
| `contract_sha256` | string or null | Contract hash reported by the embedded verify run |
| `warning` | string |  |
| `api_budget` | `api_budget` (optional) |  |

### `prepare`

`agent-contrib schema prepare` · Draft contract written to --output, or the unresolved inspect result when no draft was written.

One of `prepared`, `issue_unresolved`.

### `scope-check`

`agent-contrib schema scope-check` · Offline comparison of local changes with the contract scope; never evidence.

| Field | Type | Description |
| --- | --- | --- |
| `within_scope` | boolean | True only with no errors and no violations; sets the exit status |
| `base_commit` | string or null | Resolved base commit; null when the contract or base is invalid |
| `changed_paths` | string[] | Committed, staged, unstaged and untracked paths since the base |
| `violations` | object[] |  |
| `violations[].path` | string |  |
| `violations[].rule` | string | "not in allowed_paths" or "prohibited_paths: PATTERN" |
| `errors` | string[] |  |
| `warnings` | string[] |  |
| `evidence` | string |  |

### `skill`

`agent-contrib schema skill` · Result of exporting the canonical agent Skill.

| Field | Type | Description |
| --- | --- | --- |
| `output` | string | Path of the new SKILL.md |
| `cli_version` | string |  |
| `sha256` | string | SHA-256 of the exported file |

### `verify`

`agent-contrib schema verify` · Contract, live GitHub state and optional evidence checks; never runs validation argv. The shape follows the contract schema_version (0.1 or 0.2) and whether the contract validated.

One of `verify_0_1`, `verify_0_1_rejected`, `verify_0_2`, `verify_0_2_rejected`.

### Definitions

Shared shapes referenced above; each name means the same shape in every schema.

#### `api_budget`

Added by --report-budget; report only

| Field | Type | Description |
| --- | --- | --- |
| `before` | `rate_limit_snapshot` |  |
| `after` | `rate_limit_snapshot` |  |
| `used_during_command` | integer or null | after.used - before.used; null when the snapshots cannot be compared |
| `delta_unknown_reason` | string or null | Why used_during_command is null |
| `note` | string |  |

#### `approval`

Source approval from the default-branch .agent-contrib.json policy; never execution authorization

| Field | Type | Description |
| --- | --- | --- |
| `status` | "approved" \| "candidate" \| "unknown" |  |
| `policy_path` | string |  |
| `policy_commit` | string |  |
| `matched_labels` | string[] |  |
| `reason` | string |  |

#### `audit_report`

| Field | Type | Description |
| --- | --- | --- |
| `requested_repository` | string | Repository named on the command line |
| `issue_source_repository` | string or null | Repository whose tracker was read; null when unresolved |
| `proposed_target_repository` | string | Proposed contribution target; context, never authority |
| `resolution_provenance` | `resolution_provenance` |  |
| `complete` | boolean | False when any read failed or a label name is malformed |
| `errors` | string[] |  |
| `warning` | string |  |
| `repository` | string | Repository whose snapshot was audited |
| `commit` | string | Default-branch commit read |
| `policy` | object | Approval policy validity at the default branch |
| `policy.state` | "missing" \| "present" \| "unknown" |  |
| `policy.path` | string |  |
| `policy.commit` | string |  |
| `policy.valid` | boolean or null | Null unless a policy file is present |
| `policy.reason` | string |  |
| `policy.approval_labels` | string[] (optional) | Labels the policy declares; with a list-valued declaration only |
| `policy.missing_labels` | string[] (optional) | Declared labels that do not exist in the repository |
| `policy.generic_approval_labels` | string[] (optional) | Declared labels that are generic triage labels |
| `instructions` | object |  |
| `instructions.found` | string[] | Instruction files agents load |
| `instructions.expected` | object |  |
| `instructions.expected.contributing` | "loaded" \| "present_unread" \| "missing" \| "unknown" |  |
| `instructions.expected.agent instructions` | "loaded" \| "present_unread" \| "missing" \| "unknown" |  |
| `instructions.expected.pull request template` | "loaded" \| "present_unread" \| "missing" \| "unknown" |  |
| `instructions.expected.architecture/spec index` | "loaded" \| "present_unread" \| "missing" \| "unknown" |  |
| `instructions.read_limit` | integer |  |
| `instructions.tree_complete` | boolean |  |
| `labels` | object |  |
| `labels.count` | integer |  |
| `labels.malformed` | integer |  |
| `labels.scan` | `list_scan` |  |
| `issues` | object |  |
| `issues.open` | integer |  |
| `issues.ambiguity` | object | Open issues per ranking.ambiguity value |
| `issues.ambiguity.high` | integer (optional) |  |
| `issues.ambiguity.medium` | integer (optional) |  |
| `issues.approval` | object | Open issues per approval status |
| `issues.approval.approved` | integer (optional) |  |
| `issues.approval.candidate` | integer (optional) |  |
| `issues.approval.unknown` | integer (optional) |  |
| `issues.excluded` | integer |  |
| `issues.overlapping` | integer |  |
| `issues.scan` | `list_scan` |  |
| `pull_requests` | object |  |
| `pull_requests.open` | integer |  |
| `pull_requests.scan` | `list_scan` |  |
| `pull_requests.overlap_density` | number or null | Share of open issues with an overlapping PR; null without issues |
| `fork` | object |  |
| `fork.tracker` | string | resolution_provenance.reason |
| `fork.proposed_target_pulls` | `target_pulls_scan` or null | Null unless the tracker is a fork parent |
| `suggestions` | string[] | Non-binding suggestions for maintainers |
| `policy_template` | object (optional) | Example policy file; only with --print-policy, never written |
| `policy_template.schema_version` | "0.1" |  |
| `policy_template.agent_approved_labels` | string[] |  |
| `policy_template.label_authority` | "repository-label-permission" |  |
| `api_budget` | `api_budget` (optional) |  |

#### `audit_unread`

The repository could not be resolved or its snapshot read

| Field | Type | Description |
| --- | --- | --- |
| `requested_repository` | string | Repository named on the command line |
| `issue_source_repository` | string or null | Repository whose tracker was read; null when unresolved |
| `proposed_target_repository` | string | Proposed contribution target; context, never authority |
| `resolution_provenance` | `resolution_provenance` |  |
| `complete` | false |  |
| `errors` | string[] |  |
| `warning` | string |  |
| `api_budget` | `api_budget` (optional) |  |

#### `authorization_provenance`

| Field | Type | Description |
| --- | --- | --- |
| `fetched_at` | string |  |
| `endpoints` | string[] | GitHub endpoints read |

#### `ci_gate`

Present only when the contract declares ci_requirements; its blockers appear only in stage_blockers.completion

| Field | Type | Description |
| --- | --- | --- |
| `head_sha` | string or null | Exact head observed; null until an exact-head published draft is verified |
| `complete` | boolean |  |
| `suites_read` | integer |  |
| `github_paths_changed` | boolean or null | Whether the implementation diff touches .github/; null when not read |
| `requirements` | object[] |  |
| `requirements[].check` | string | Reviewed check name (display copy) |
| `requirements[].app_id` | integer |  |
| `requirements[].state` | "met" \| "failed" \| "not_met" \| "pending" \| "missing" \| "unknown" | Only met passes |
| `requirements[].runs` | object[] | Every retained run with this exact raw name from this app on the head |
| `requirements[].runs[].id` | integer |  |
| `requirements[].runs[].status` | "queued" \| "in_progress" \| "completed" \| "waiting" \| "requested" \| "pending" |  |
| `requirements[].runs[].conclusion` | "success" \| "failure" \| "neutral" \| "cancelled" \| "skipped" \| "timed_out" \| "action_required" \| "stale" \| "startup_failure" \| null |  |
| `requirements[].runs[].url` | string |  |
| `requirements[].blocking_suites` | integer[] | Suites of this app on the head that are not completed |
| `requirements[].other_app_runs` | integer | Same-name runs from other apps; never accepted |
| `errors` | string[] |  |
| `notice` | string |  |

#### `ci_observation`

Added by --observe-ci on a schema-valid contract; report only, never changes gates or exit status. The run and status fields are absent when there was no valid head or target to read

| Field | Type | Description |
| --- | --- | --- |
| `repository` | string | Repository whose CI was read: the execution target, else the source |
| `head_sha` | string or null | Evidence git_head; null when the evidence has none |
| `complete` | boolean |  |
| `errors` | string[] |  |
| `notice` | string |  |
| `check_runs` | `verify_check_run`[] (optional) | Check runs for exactly head_sha |
| `other_head_runs` | integer (optional) | Returned runs for a different head; ignored |
| `check_runs_complete` | boolean (optional) |  |
| `combined_status` | object (optional) |  |
| `combined_status.state` | "success" \| "failure" \| "pending" \| "error" \| null | Null when the read failed |
| `combined_status.statuses` | object[] |  |
| `combined_status.statuses[].context` | string |  |
| `combined_status.statuses[].state` | "success" \| "failure" \| "pending" \| "error" |  |
| `combined_status.statuses[].url` | string |  |
| `combined_status.complete` | boolean |  |

#### `discover_failed_entry`

A repository in a multi-repository run whose discovery raised

| Field | Type | Description |
| --- | --- | --- |
| `requested_repository` | string |  |
| `complete` | false |  |
| `errors` | string[] |  |
| `issues` | any[] |  |

#### `discover_issue`

| Field | Type | Description |
| --- | --- | --- |
| `number` | integer |  |
| `reference` | string | owner/repo#number in the requested repository |
| `issue_url` | string |  |
| `untrusted_title` | string | Untrusted issue title |
| `approval` | `approval` |  |
| `exclusions` | string[] | Excluded labels (lowercase) and "issue is not open"; any entry excludes the issue |
| `duplicates` | `duplicate`[] | Open PRs referencing or overlapping the issue; any entry blocks execution |
| `complete` | boolean |  |
| `ranking` | `ranking` |  |
| `signals` | `issue_signals` (optional) |  |
| `top_check` | object (optional) | Present only for the top N candidates checked by --check-top; report only |
| `top_check.complete` | boolean | False when a read failed or a page, PR-detail or total read cap was reached |
| `top_check.errors` | string[] |  |
| `top_check.reads` | integer | GitHub reads made for this issue; at most 30 |
| `top_check.demotions` | string[] | Merged same-repository fix or current assignee; claim comments never demote |

#### `discover_multi`

Two to 20 repositories were requested

| Field | Type | Description |
| --- | --- | --- |
| `repositories` | `discover_result` or `discover_unresolved` or `discover_failed_entry`[] | One result per requested repository, in request order |
| `complete` | boolean | True only when every repository is complete |
| `errors` | string[] | Each repository error prefixed with "owner/repo: " |
| `candidates` | object[] | Merged order of every issue across repositories |
| `candidates[].repository` | string |  |
| `candidates[].reference` | string |  |
| `candidates[].number` | integer |  |
| `candidates[].excluded` | boolean |  |
| `candidates[].overlapping` | boolean |  |
| `candidates[].low_likelihood` | boolean |  |
| `candidates[].score` | integer or null | Signal score with --signals, else null |
| `candidates[].complete` | boolean |  |
| `ordering` | string |  |
| `limits` | object |  |
| `limits.max_repositories` | integer |  |
| `limits.per_repository` | string |  |
| `warning` | string |  |
| `api_budget` | `api_budget` (optional) |  |

#### `discover_result`

One repository was resolved and read

| Field | Type | Description |
| --- | --- | --- |
| `requested_repository` | string | Repository named on the command line |
| `issue_source_repository` | string or null | Repository whose tracker was read; null when unresolved |
| `proposed_target_repository` | string | Proposed contribution target; context, never authority |
| `resolution_provenance` | `resolution_provenance` |  |
| `ordering` | string (optional) | Present with --signals: how issues are sorted |
| `schema_version` | "0.1" | Snapshot format version |
| `repository` | string | Issue source repository that was read |
| `commit` | string | Default-branch commit of the snapshot |
| `fetched_at` | string |  |
| `complete` | boolean | False when any read failed; missing data is never permission |
| `errors` | string[] |  |
| `issues` | `discover_issue`[] | Open issues, best candidates first |
| `instructions` | `instruction_file`[] | Pinned repository instruction files |
| `spec_paths` | string[] | Markdown spec/doc paths in the tree |
| `provenance` | object |  |
| `provenance.pulls_scan` | `list_scan` |  |
| `provenance.labels_scan` | `list_scan` |  |
| `provenance.policy_state` | "missing" \| "present" \| "unknown" | State of .agent-contrib.json at the snapshot commit |
| `provenance.proposed_target_pulls` | `target_pulls_scan` or null | Null when the target is the issue source |
| `issue_scan` | `list_scan` |  |
| `limits` | object |  |
| `limits.pages_per_list` | integer |  |
| `limits.instruction_files` | integer |  |
| `warning` | string |  |
| `repository_signals` | object (optional) | Added by --responsiveness |
| `repository_signals.responsiveness` | `responsiveness` |  |
| `top_check` | object (optional) | Present with --check-top N: bounded ownership reads for the top N; a demoted one moves below every other candidate that is not excluded or overlapping |
| `top_check.requested` | integer | at most 5 |
| `top_check.checked` | integer | at most 5 |
| `top_check.reads` | integer | at most 30 |
| `top_check.read_cap` | integer | at most 30 |
| `top_check.complete` | boolean | Every checked issue was read completely; false sets exit 1 |
| `top_check.notice` | string |  |
| `local_work` | `local_work` (optional) |  |
| `api_budget` | `api_budget` (optional) |  |
| `repository_policy` | `repository_policy` (optional) | Default-on, report-only; never a verdict |

#### `discover_unresolved`

The repository could not be resolved or its snapshot read

| Field | Type | Description |
| --- | --- | --- |
| `requested_repository` | string | Repository named on the command line |
| `issue_source_repository` | string or null | Repository whose tracker was read; null when unresolved |
| `proposed_target_repository` | string | Proposed contribution target; context, never authority |
| `resolution_provenance` | `resolution_provenance` |  |
| `complete` | false |  |
| `errors` | string[] |  |
| `issues` | any[] |  |
| `repository_signals` | object (optional) | Added by --responsiveness |
| `repository_signals.responsiveness` | `responsiveness` |  |
| `api_budget` | `api_budget` (optional) |  |
| `local_work` | `local_work` (optional) |  |

#### `duplicate`

An open PR that references or overlaps the issue

| Field | Type | Description |
| --- | --- | --- |
| `number` | integer |  |
| `url` | string |  |
| `reason` | string | "Explicit reference to this issue" or a heuristic overlap naming the shared words/IDs |
| `repository` | string (optional) | Repository of the PR, when it is not the issue source |
| `observed_in` | "disposition_read" (optional) | Only in schema 0.2 verify: the match was first seen in a host-context 0.2 disposition read, not the open-PR list scan |

#### `feedback_author`

| Field | Type | Description |
| --- | --- | --- |
| `login` | string | "ghost" for a deleted account |
| `id` | integer or null | null for a deleted account |
| `bot` | boolean | Bot account type or a [bot] login |
| `association` | "COLLABORATOR" \| "CONTRIBUTOR" \| "FIRST_TIMER" \| "FIRST_TIME_CONTRIBUTOR" \| "MANNEQUIN" \| "MEMBER" \| "NONE" \| "OWNER" | GitHub's author_association; a heuristic, not a verified role |

#### `feedback_check_run`

| Field | Type | Description |
| --- | --- | --- |
| `id` | integer |  |
| `name` | string |  |
| `app_slug` | string |  |
| `app_id` | integer |  |
| `head_sha` | string |  |
| `status` | "queued" \| "in_progress" \| "completed" \| "waiting" \| "requested" \| "pending" |  |
| `conclusion` | "success" \| "failure" \| "neutral" \| "cancelled" \| "skipped" \| "timed_out" \| "action_required" \| "stale" \| "startup_failure" \| null | Null exactly when status is not completed |
| `url` | string | Empty when GitHub reports none |

#### `feedback_report`

| Field | Type | Description |
| --- | --- | --- |
| `reference` | string | owner/repo#number of the pull request |
| `complete` | boolean | True only when every read succeeded and the head did not move while reading |
| `errors` | string[] |  |
| `untrusted_data_notice` | string |  |
| `pull_request` | object |  |
| `pull_request.number` | integer |  |
| `pull_request.url` | string |  |
| `pull_request.state` | "open" \| "closed" |  |
| `pull_request.draft` | boolean |  |
| `pull_request.head_sha` | string |  |
| `pull_request.head_ref` | string |  |
| `pull_request.base_ref` | string |  |
| `head_moved` | boolean or null | Whether the head differs from --expected-head; null without it |
| `reviews` | object[] | One entry per reviewer, latest review last |
| `reviews[].author` | `feedback_author` | Author of the latest review |
| `reviews[].decision` | "APPROVED" \| "CHANGES_REQUESTED" \| null | Latest APPROVED or CHANGES_REQUESTED review; null when none or dismissed |
| `reviews[].decision_author` | `feedback_author` or null | Author as of the deciding review; null without a decision |
| `reviews[].latest_state` | "APPROVED" \| "CHANGES_REQUESTED" \| "COMMENTED" \| "DISMISSED" \| "PENDING" |  |
| `reviews[].commit_id` | string or null |  |
| `reviews[].submitted_at` | string or null |  |
| `reviews[].untrusted_body` | string | Untrusted review text, at most 4000 characters |
| `changes_requested_by_trusted_association` | boolean | A non-bot OWNER, MEMBER or COLLABORATOR currently requests changes |
| `review_provenance` | string |  |
| `review_comments` | object[] |  |
| `review_comments[].author` | `feedback_author` |  |
| `review_comments[].untrusted_body` | string |  |
| `review_comments[].path` | string |  |
| `review_comments[].line` | integer or null |  |
| `review_comments[].outdated` | boolean | No diff position, or made on another commit than the head |
| `issue_comments` | object[] |  |
| `issue_comments[].author` | `feedback_author` |  |
| `issue_comments[].untrusted_body` | string |  |
| `issue_comments[].created_at` | string |  |
| `checks` | object |  |
| `checks.total` | integer | Check runs read for the head commit |
| `checks.complete` | boolean |  |
| `checks.other_head_runs` | integer | Runs whose head_sha differs from the PR head |
| `checks.failing` | `feedback_check_run`[] |  |
| `checks.pending` | `feedback_check_run`[] |  |
| `api_budget` | `api_budget` (optional) |  |

#### `feedback_unread`

The pull request itself could not be read

| Field | Type | Description |
| --- | --- | --- |
| `reference` | string | owner/repo#number of the pull request |
| `complete` | false |  |
| `errors` | string[] |  |
| `untrusted_data_notice` | string |  |
| `api_budget` | `api_budget` (optional) |  |

#### `inspect_result`

The issue was read

| Field | Type | Description |
| --- | --- | --- |
| `schema_version` | "0.1" | Snapshot format version |
| `source` | object | Pinned snapshot; prepare copies it into the contract |
| `source.repository` | string |  |
| `source.default_branch` | string |  |
| `source.commit` | string |  |
| `source.fetched_at` | string |  |
| `source.instructions_sha256` | string |  |
| `source.issue` | integer |  |
| `source.issue_url` | string |  |
| `source.issue_updated_at` | string |  |
| `source.issue_sha256` | string |  |
| `untrusted_issue` | object | Untrusted issue text, sanitized |
| `untrusted_issue.title` | string |  |
| `untrusted_issue.body` | string |  |
| `untrusted_issue.labels` | string[] |  |
| `instructions` | `instruction_file`[] |  |
| `spec_paths` | string[] |  |
| `approval` | `approval` |  |
| `duplicates` | `duplicate`[] | Open PRs referencing or overlapping the issue; any entry blocks execution |
| `duplicate_scan` | "complete" \| "unknown" | Whether the open-PR scans behind duplicates were complete |
| `complete` | boolean | False when any read failed; missing data is never permission |
| `errors` | string[] |  |
| `warnings` | string[] |  |
| `exclusions` | string[] | Excluded labels (lowercase) and "issue is not open"; any entry excludes the issue |
| `ranking` | `ranking` |  |
| `provenance` | object |  |
| `provenance.pulls` | `list_scan` |  |
| `provenance.labels` | `list_scan` |  |
| `provenance.policy_state` | "missing" \| "present" \| "unknown" | State of .agent-contrib.json at the snapshot commit |
| `provenance.policy` | `policy_file` |  |
| `provenance.proposed_target_pulls` | `target_pulls_scan` (optional) |  |
| `requested_repository` | string | Repository named on the command line |
| `issue_source_repository` | string or null | Repository whose tracker was read; null when unresolved |
| `proposed_target_repository` | string | Proposed contribution target; context, never authority |
| `resolution_provenance` | `resolution_provenance` |  |
| `reference` | string | owner/repo#number as requested |
| `ownership_signals` | `ownership_signals` (optional) | Added by --ownership |
| `api_budget` | `api_budget` (optional) |  |
| `repository_policy` | `repository_policy` (optional) | Default-on, report-only; never a verdict |

#### `instruction_file`

| Field | Type | Description |
| --- | --- | --- |
| `path` | string |  |
| `sha256` | string |  |
| `untrusted_text` | string | Untrusted repository text |

#### `issue_signals`

Added by --signals; report-only heuristics, never approval

| Field | Type | Description |
| --- | --- | --- |
| `code_location` | object |  |
| `code_location.value` | "found" \| "none" \| "unknown" |  |
| `code_location.hints` | string[] | Repository paths matched from the issue text |
| `code_location.named_paths_missing` | string[] | Repository-relative file paths named in the issue text that are not in the snapshot tree (exact comparison; report only) |
| `code_location.explanation` | string |  |
| `acceptance_clarity` | object |  |
| `acceptance_clarity.value` | "high" \| "medium" \| "low" |  |
| `acceptance_clarity.markers` | "checklist" \| "expected/actual sections" \| "reproduction steps" \| "code block"[] |  |
| `acceptance_clarity.explanation` | string |  |
| `activity` | object |  |
| `activity.value` | object | Null when the issue payload lacks or malforms the field |
| `activity.value.age_days` | integer or null |  |
| `activity.value.updated_days` | integer or null |  |
| `activity.value.comments` | integer or null |  |
| `activity.value.reactions` | integer or null |  |
| `activity.explanation` | string |  |
| `maintainer` | object |  |
| `maintainer.value` | "maintainer" \| "other" \| "unknown" |  |
| `maintainer.explanation` | string |  |
| `labels` | string[] | Issue label names (sanitized), as used by the demotion rules |
| `assignees` | string[] (optional) | Present only with --check-top: current assignee logins from the issue list payload (sanitized, at most 10) |
| `demotion` | object | Documented label and title demotions; each subtracts 2 from the score |
| `demotion.value` | "demoted" \| "none" |  |
| `demotion.reasons` | string[] | One entry per matched label group or meta-like title |
| `local_work` | object (optional) | Present with --repo-dir; a referenced issue ranks below other candidates that are not excluded or overlapping |
| `local_work.value` | "referenced" \| "none" \| "unknown" |  |
| `local_work.commits` | string[] |  |
| `local_work.explanation` | string |  |
| `score` | integer | code_location found (1) + acceptance clarity (0-2) + maintainer author (1, not for a meta-like title) - 2 per demotion, floored at 0 |

#### `issue_unresolved`

The repository or issue could not be resolved or read; nothing else is reported

| Field | Type | Description |
| --- | --- | --- |
| `requested_repository` | string | Repository named on the command line |
| `issue_source_repository` | string or null | Repository whose tracker was read; null when unresolved |
| `proposed_target_repository` | string | Proposed contribution target; context, never authority |
| `resolution_provenance` | `resolution_provenance` |  |
| `reference` | string | owner/repo#number as requested |
| `complete` | false |  |
| `errors` | string[] |  |
| `api_budget` | `api_budget` (optional) |  |

#### `list_scan`

Completeness of one paginated GitHub list read

| Field | Type | Description |
| --- | --- | --- |
| `complete` | boolean |  |
| `pages` | integer |  |
| `errors` | string[] |  |

#### `local_work`

Present with --repo-dir: issues referenced by local commits not in the source default branch; report only

| Field | Type | Description |
| --- | --- | --- |
| `complete` | boolean | False when the checkout or base could not be read or the commit limit was reached; sets exit 1 |
| `head` | string or null |  |
| `base` | string or null | Source default-branch commit of the snapshot |
| `commits_scanned` | integer |  |
| `commit_limit` | integer |  |
| `issues` | object[] |  |
| `issues[].number` | integer |  |
| `issues[].commits` | string[] |  |
| `errors` | string[] |  |
| `notice` | string |  |

#### `metadata_read`

| Field | Type | Description |
| --- | --- | --- |
| `endpoint` | string |  |
| `observed` | `repository_observation` |  |
| `fetched_at` | string |  |

#### `ownership_signals`

Report-only ownership and resolution signals; never change gates

| Field | Type | Description |
| --- | --- | --- |
| `complete` | boolean |  |
| `errors` | string[] |  |
| `reads` | object |  |
| `reads.timeline` | `list_scan` |  |
| `reads.comments` | `list_scan` |  |
| `reads.pull_details` | integer |  |
| `cross_referenced_prs` | object[] |  |
| `cross_referenced_prs[].repository` | string |  |
| `cross_referenced_prs[].repository_id` | integer |  |
| `cross_referenced_prs[].number` | integer |  |
| `cross_referenced_prs[].url` | string |  |
| `cross_referenced_prs[].state` | "open" \| "closed" |  |
| `cross_referenced_prs[].draft` | boolean |  |
| `cross_referenced_prs[].merged` | boolean |  |
| `cross_referenced_prs[].merged_at` | string or null |  |
| `cross_referenced_prs[].closed_at` | string or null |  |
| `cross_referenced_prs[].exact_reference` | boolean | The PR text references this issue exactly |
| `cross_referenced_prs[].title` | string |  |
| `cross_referenced_prs[].base_ref` | string |  |
| `assignment_history` | object[] |  |
| `assignment_history[].event` | "assigned" \| "unassigned" |  |
| `assignment_history[].assignee` | string |  |
| `assignment_history[].actor` | string |  |
| `assignment_history[].created_at` | string |  |
| `connected_events` | object[] |  |
| `connected_events[].event` | "connected" \| "disconnected" |  |
| `connected_events[].actor` | string |  |
| `connected_events[].created_at` | string |  |
| `referencing_commits` | object[] |  |
| `referencing_commits[].commit_id` | string |  |
| `referencing_commits[].url` | string |  |
| `claims` | object[] | Comments matching claim phrases; text cannot prove ownership |
| `claims[].pattern` | "working on it" \| "will take it" \| "asks to work on it" \| "/assign command" \| "asks for assignment" |  |
| `claims[].author` | string |  |
| `claims[].author_association` | "COLLABORATOR" \| "CONTRIBUTOR" \| "FIRST_TIMER" \| "FIRST_TIME_CONTRIBUTOR" \| "MANNEQUIN" \| "MEMBER" \| "NONE" \| "OWNER" |  |
| `claims[].age_days` | integer or null |  |
| `claims[].stale` | boolean |  |
| `claims[].untrusted_excerpt` | string |  |
| `resolution_signals` | object |  |
| `resolution_signals.possibly_already_fixed` | object[] | Merged PRs referencing the issue exactly |
| `resolution_signals.possibly_already_fixed[].repository` | string |  |
| `resolution_signals.possibly_already_fixed[].repository_id` | integer |  |
| `resolution_signals.possibly_already_fixed[].number` | integer |  |
| `resolution_signals.possibly_already_fixed[].url` | string |  |
| `resolution_signals.possibly_already_fixed[].state` | "open" \| "closed" |  |
| `resolution_signals.possibly_already_fixed[].draft` | boolean |  |
| `resolution_signals.possibly_already_fixed[].merged` | boolean |  |
| `resolution_signals.possibly_already_fixed[].merged_at` | string or null |  |
| `resolution_signals.possibly_already_fixed[].closed_at` | string or null |  |
| `resolution_signals.possibly_already_fixed[].exact_reference` | boolean | The PR text references this issue exactly |
| `resolution_signals.possibly_already_fixed[].title` | string |  |
| `resolution_signals.possibly_already_fixed[].base_ref` | string |  |
| `resolution_signals.rejected_approaches` | object[] | Closed unmerged PRs referencing the issue exactly |
| `resolution_signals.rejected_approaches[].repository` | string |  |
| `resolution_signals.rejected_approaches[].repository_id` | integer |  |
| `resolution_signals.rejected_approaches[].number` | integer |  |
| `resolution_signals.rejected_approaches[].url` | string |  |
| `resolution_signals.rejected_approaches[].state` | "open" \| "closed" |  |
| `resolution_signals.rejected_approaches[].draft` | boolean |  |
| `resolution_signals.rejected_approaches[].merged` | boolean |  |
| `resolution_signals.rejected_approaches[].merged_at` | string or null |  |
| `resolution_signals.rejected_approaches[].closed_at` | string or null |  |
| `resolution_signals.rejected_approaches[].exact_reference` | boolean | The PR text references this issue exactly |
| `resolution_signals.rejected_approaches[].title` | string |  |
| `resolution_signals.rejected_approaches[].base_ref` | string |  |
| `resolution_signals.status` | "complete" \| "unknown" |  |
| `resolution_signals.downstream_references` | object[] | Merged PRs with an exact reference in other repositories; never a fix |
| `resolution_signals.downstream_references[].repository` | string |  |
| `resolution_signals.downstream_references[].repository_id` | integer |  |
| `resolution_signals.downstream_references[].number` | integer |  |
| `resolution_signals.downstream_references[].url` | string |  |
| `resolution_signals.downstream_references[].state` | "open" \| "closed" |  |
| `resolution_signals.downstream_references[].draft` | boolean |  |
| `resolution_signals.downstream_references[].merged` | boolean |  |
| `resolution_signals.downstream_references[].merged_at` | string or null |  |
| `resolution_signals.downstream_references[].closed_at` | string or null |  |
| `resolution_signals.downstream_references[].exact_reference` | boolean | The PR text references this issue exactly |
| `resolution_signals.downstream_references[].title` | string |  |
| `resolution_signals.downstream_references[].base_ref` | string |  |
| `blocking_if_adopted` | string[] | Preview of what would block if these signals became gates; nothing blocks now |
| `notice` | string |  |

#### `policy_file`

The parsed .agent-contrib.json exactly as read: any JSON value, untrusted and possibly invalid; null when absent

any

#### `prepared`

A draft was written; it grants no authorization

| Field | Type | Description |
| --- | --- | --- |
| `requested_repository` | string | Repository named on the command line |
| `issue_source_repository` | string or null | Repository whose tracker was read; null when unresolved |
| `proposed_target_repository` | string | Proposed contribution target; context, never authority |
| `resolution_provenance` | `resolution_provenance` |  |
| `reference` | string |  |
| `output` | string | Path of the new draft contract |
| `complete` | boolean | Whether the inspect read behind the draft was complete |
| `contract` | object | The draft task contract as written; validate it with the task schema of its schema_version |
| `contract.schema_version` | "0.1" \| "0.2" |  |
| `warning` | string |  |
| `api_budget` | `api_budget` (optional) |  |
| `repository_policy` | `repository_policy` (optional) | Default-on, report-only; never a verdict |

#### `ranking`

Deterministic heuristics, not predictions

| Field | Type | Description |
| --- | --- | --- |
| `difficulty` | object |  |
| `difficulty.value` | "high" \| "unknown" |  |
| `difficulty.explanation` | string |  |
| `ambiguity` | object |  |
| `ambiguity.value` | "high" \| "medium" |  |
| `ambiguity.explanation` | string |  |
| `dependencies` | object |  |
| `dependencies.value` | "possible" \| "unknown" |  |
| `dependencies.explanation` | string |  |
| `success_likelihood` | object |  |
| `success_likelihood.value` | "low" \| "unknown" |  |
| `success_likelihood.explanation` | string |  |

#### `rate_limit_snapshot`

Core REST rate-limit snapshot; the counters are null when error is set

| Field | Type | Description |
| --- | --- | --- |
| `limit` | integer or null |  |
| `remaining` | integer or null |  |
| `used` | integer or null |  |
| `reset` | integer or null | Reset time, epoch seconds |
| `error` | string or null | Why the snapshot failed; null when it succeeded |

#### `repository_observation`

| Field | Type | Description |
| --- | --- | --- |
| `full_name` | string |  |
| `fork` | boolean |  |
| `has_issues` | boolean |  |
| `parent` | object (optional) | Immediate fork parent, when it was read |
| `parent.full_name` | string |  |

#### `repository_policy`

Default-on, report-only policy inventory and hints; never a verdict

| Field | Type | Description |
| --- | --- | --- |
| `report` | "policy-report/1" |  |
| `review_obligation` | string |  |
| `sources_scanned` | object[] |  |
| `sources_scanned[].origin` | "repository" \| "owner-github" |  |
| `sources_scanned[].repository` | string |  |
| `sources_scanned[].path` | string |  |
| `sources_scanned[].path_truncated` | boolean |  |
| `sources_scanned[].commit` | string |  |
| `sources_scanned[].sha256` | string |  |
| `sources_scanned[].kind` | "ai_policy" \| "agent_instructions" \| "contributing" \| "pr_template" \| "community" \| "readme" \| "instruction" |  |
| `sources_scanned[].notes` | string[] |  |
| `sources_scanned[].path_sanitized` | boolean |  |
| `sources_scanned[].identity_sha256` | string | SHA-256 of the original repository/path or URL; display text may be shortened or sanitized |
| `unassessed` | object[] |  |
| `unassessed[].what` | string |  |
| `unassessed[].reason` | string |  |
| `unassessed[].from` | string or null |  |
| `unassessed[].line` | integer or null |  |
| `unassessed[].link_text` | string or null |  |
| `unassessed[].what_truncated` | boolean |  |
| `unassessed[].what_sanitized` | boolean |  |
| `unassessed[].identity_sha256` | string | SHA-256 of the original repository/path or URL; display text may be shortened or sanitized |
| `omitted_sources` | object[] |  |
| `omitted_sources[].repository` | string |  |
| `omitted_sources[].path` | string |  |
| `omitted_sources[].path_truncated` | boolean |  |
| `omitted_sources[].kind` | "ai_policy" \| "agent_instructions" \| "contributing" \| "pr_template" \| "community" \| "readme" \| "instruction" |  |
| `omitted_sources[].reason` | "file limit" \| "scan byte limit" \| "request limit" |  |
| `omitted_sources[].path_sanitized` | boolean |  |
| `omitted_sources[].identity_sha256` | string | SHA-256 of the original repository/path or URL; display text may be shortened or sanitized |
| `limits_reached` | object[] |  |
| `limits_reached[].limit` | string |  |
| `limits_reached[].not_reported` | integer |  |
| `limits_reached[].hides_sources` | boolean |  |
| `limits_hide_sources` | boolean | A limit hid a policy candidate or reference, or omitted_sources is non-empty |
| `never_inspected` | string[] |  |
| `hints` | object[] |  |
| `hints[].kind` | "possible_agent_restriction" \| "possible_ai_restriction" \| "possible_pr_restriction" \| "ai_mention" |  |
| `hints[].line` | integer |  |
| `hints[].heading` | string |  |
| `hints[].untrusted_excerpt` | string |  |
| `hints[].source` | integer |  |
| `hints[].id` | string | H1, H2, ... in report order |
| `reads` | object |  |
| `reads.requests` | integer |  |
| `reads.limit` | integer |  |
| `inventory_sha256` | string |  |

#### `resolution_provenance`

| Field | Type | Description |
| --- | --- | --- |
| `metadata_reads` | `metadata_read`[] |  |
| `reason` | string | How the issue tracker was chosen, or "unresolved" |
| `execution_authority` | string | Always "none": resolution never grants authority |

#### `responsiveness`

Added by --responsiveness; one-page sample of recently closed PRs, report only

| Field | Type | Description |
| --- | --- | --- |
| `repository` | string or null | Null when discovery did not resolve the source |
| `endpoint` | string or null |  |
| `complete` | boolean |  |
| `value` | "measured" \| "insufficient" \| "unknown" |  |
| `sample_size` | integer or null | Closed PRs read (one page) |
| `external_closed` | integer or null |  |
| `external_merged` | integer or null |  |
| `external_merge_rate` | number or null | external_merged / external_closed, when value is measured |
| `median_days_to_close` | number or null |  |
| `minimum_external` | integer |  |
| `errors` | string[] |  |
| `explanation` | string |  |

#### `signature_github_verification`

GitHub verification object for the evidence head (git/commits)

| Field | Type | Description |
| --- | --- | --- |
| `complete` | boolean |  |
| `verified` | boolean or null | GitHub key-to-account match; not approval. Null when unread |
| `reason` | "bad_cert" \| "bad_email" \| "expired_key" \| "gpgverify_error" \| "gpgverify_unavailable" \| "invalid" \| "malformed_signature" \| "no_user" \| "not_signing_key" \| "ocsp_pending" \| "unknown_key" \| "unknown_signature_type" \| "unsigned" \| "unverified_email" \| "valid" \| "unrecognized" \| null | GitHub verification reason; unrecognized values are not echoed |
| `verified_at` | string or null | Timezone-bearing time GitHub verified, or null |
| `errors` | string[] |  |
| `verified_means` | string | What verified does and does not show |

#### `signature_local_commit`

| Field | Type | Description |
| --- | --- | --- |
| `sha` | string |  |
| `signature_header` | "present" \| "absent" | Header presence only, never validity |

#### `signature_local_commits`

Local signature-header presence; no signature program runs

| Field | Type | Description |
| --- | --- | --- |
| `complete` | boolean |  |
| `commits` | `signature_local_commit`[] or null | base_commit..git_head, oldest first; null when incomplete, never truncated |
| `with_header` | integer or null |  |
| `without_header` | integer or null |  |
| `limit` | integer | Commit cap; more is reported as incomplete |
| `errors` | string[] |  |
| `notice` | string |  |

#### `signature_observation`

Report-only commit-signature observation (verify --observe-signatures); never a gate

| Field | Type | Description |
| --- | --- | --- |
| `repository` | string | Repository read: the execution target, else the source |
| `head_sha` | string or null | Evidence git_head; null when the evidence has none |
| `complete` | boolean |  |
| `github_verification` | null or `signature_github_verification` |  |
| `required_signatures` | null or `signature_required` |  |
| `local_commits` | object or `signature_local_commits` |  |
| `errors` | string[] |  |
| `notice` | string |  |

#### `signature_required`

Active ruleset rules for the base branch (rules/branches)

| Field | Type | Description |
| --- | --- | --- |
| `complete` | boolean |  |
| `branch` | string | Base branch whose active rules were read |
| `required` | boolean or null | An active required_signatures ruleset rule applies; null when unread |
| `ruleset_ids` | integer[] or null | Rulesets requiring signatures, ascending; null when unread |
| `classic_branch_protection` | "not_observed" | Classic protection needs admin access and is never read |
| `errors` | string[] |  |

#### `target_pulls_scan`

Open-PR scan of the proposed target repository when it differs from the issue source

| Field | Type | Description |
| --- | --- | --- |
| `repository` | string |  |
| `endpoint` | string |  |
| `complete` | boolean |  |
| `pages` | integer |  |
| `errors` | string[] |  |

#### `verify_0_1`

Schema 0.1: a schema-valid contract was checked. live_provenance, source_resolution_provenance and duplicates are absent when the live refresh failed

| Field | Type | Description |
| --- | --- | --- |
| `schema_version` | "0.1" |  |
| `schema_valid` | boolean | The contract matches the bundled task schema |
| `execution_ready` | boolean | Contract, live source and local execution authorization all pass |
| `evidence_valid` | boolean | Supplied evidence validates against the contract and checkout |
| `upstream_submission_ready` | boolean | Exit gate for upstream-contribution mode |
| `fork_completion_ready` | boolean | Exit gate for fork-experiment mode |
| `approval` | `approval` or `verify_unrefreshed_approval` | Live source approval; "Not refreshed" until the live read succeeds |
| `errors` | string[] | Blockers for execution_ready |
| `evidence_errors` | string[] | Blockers for evidence_valid |
| `evidence_trust` | string | Evidence is self-attested; identity and truth are not authenticated |
| `publication` | string | Fixed notice: this CLI never publishes |
| `api_budget` | `api_budget` (optional) |  |
| `ci_observation` | `ci_observation` (optional) |  |
| `signature_observation` | `signature_observation` (optional) |  |
| `contract_sha256` | string | Canonical hash of the contract |
| `requested_repository` | null | Not stored in schema 0.1 |
| `issue_source_repository` | string |  |
| `proposed_target_repository` | string |  |
| `resolution_provenance` | object | Which contract fields the repositories come from |
| `resolution_provenance.requested_repository` | string |  |
| `resolution_provenance.issue_source_repository` | string |  |
| `resolution_provenance.proposed_target_repository` | string |  |
| `resolution_provenance.execution_authority` | string |  |
| `live_complete` | boolean | Whether the live refresh was complete |
| `live_provenance` | `verify_live_provenance` (optional) |  |
| `source_resolution_provenance` | `resolution_provenance` (optional) |  |
| `duplicates` | `duplicate`[] (optional) | Open PRs overlapping the issue now |
| `execution_authorization` | object | The contract's execution block, echoed; a reviewed assertion, never inferred |
| `execution_authorization.mode` | "pending" \| "fork-experiment" \| "upstream-contribution" |  |
| `execution_authorization.target_repository` | string |  |
| `execution_authorization.authorized_by` | string |  |
| `execution_authorization.authorization_evidence` | string |  |

#### `verify_0_1_rejected`

Schema 0.1: the contract failed validation; nothing was read

| Field | Type | Description |
| --- | --- | --- |
| `schema_version` | "0.1" |  |
| `schema_valid` | boolean | The contract matches the bundled task schema |
| `execution_ready` | boolean | Contract, live source and local execution authorization all pass |
| `evidence_valid` | boolean | Supplied evidence validates against the contract and checkout |
| `upstream_submission_ready` | boolean | Exit gate for upstream-contribution mode |
| `fork_completion_ready` | boolean | Exit gate for fork-experiment mode |
| `approval` | `approval` or `verify_unrefreshed_approval` | Live source approval; "Not refreshed" until the live read succeeds |
| `errors` | string[] | Blockers for execution_ready |
| `evidence_errors` | string[] | Blockers for evidence_valid |
| `evidence_trust` | string | Evidence is self-attested; identity and truth are not authenticated |
| `publication` | string | Fixed notice: this CLI never publishes |
| `api_budget` | `api_budget` (optional) |  |
| `ci_observation` | `ci_observation` (optional) |  |
| `signature_observation` | `signature_observation` (optional) |  |

#### `verify_0_2`

Schema 0.2: a schema-valid contract was checked. live_provenance is absent when the live refresh failed

| Field | Type | Description |
| --- | --- | --- |
| `schema_version` | "0.2" |  |
| `schema_valid` | true |  |
| `repository_approval` | `approval` or `verify_unrefreshed_approval` | Live source approval; "Not refreshed" when the live read failed |
| `user_authorization` | `verify_user_authorization` |  |
| `implementation_ready` | boolean | Gate for --stage implementation |
| `technical_evidence_valid` | boolean | Supplied evidence validates against the contract and checkout |
| `independent_review` | `verify_review` |  |
| `draft_create_ready` | boolean | Draft-creation gate; false once an own draft is verified |
| `publication` | `verify_publication` |  |
| `human_signoff` | `verify_signoff` |  |
| `completion_ready` | boolean | Gate for --stage completion (the default) |
| `next_action` | "resolve_blockers" \| "implement" \| "create_draft" \| "none" |  |
| `errors` | string[] | Contract, live-source and mandate blockers |
| `evidence_errors` | string[] |  |
| `stage_blockers` | object | Blockers per --stage gate |
| `stage_blockers.implementation` | string[] |  |
| `stage_blockers.draft` | string[] |  |
| `stage_blockers.completion` | string[] |  |
| `blocking_duplicates` | `duplicate`[] | Overlapping PRs other than the verified own draft |
| `evidence_trust` | string | Evidence is self-attested; identity and truth are not authenticated |
| `mandate_trust` | "host-asserted" |  |
| `mandate_sha256` | string or null |  |
| `final_signoff_sha256` | string or null |  |
| `contract_sha256` | string |  |
| `source_identity` | object | Reviewed numeric source identity |
| `source_identity.repository` | string |  |
| `source_identity.repository_id` | integer |  |
| `source_identity.owner_id` | integer |  |
| `source_identity.issue` | integer |  |
| `source_identity.issue_id` | integer |  |
| `live_complete` | boolean |  |
| `live_provenance` | `verify_live_provenance` (optional) |  |
| `duplicates` | `duplicate`[] | Open PRs overlapping the issue now |
| `api_budget` | `api_budget` (optional) |  |
| `ci_observation` | `ci_observation` (optional) |  |
| `signature_observation` | `signature_observation` (optional) |  |
| `overlap_dispositions` | `verify_overlap_dispositions` (optional) | Present only for a host-context 0.2 document |
| `waived_duplicates` | `verify_waived_overlap`[] (optional) | Overlaps removed from blocking by a host disposition (also in overlap_dispositions.waived); duplicates still lists them |
| `draft_update` | `verify_draft_update` (optional) | Present only when a host-context 0.2 document carries draft_update |
| `ci_gate` | `ci_gate` (optional) |  |

#### `verify_0_2_rejected`

Schema 0.2: the contract failed validation; nothing was read

| Field | Type | Description |
| --- | --- | --- |
| `schema_version` | "0.2" |  |
| `schema_valid` | false |  |
| `repository_approval` | `verify_unrefreshed_approval` |  |
| `user_authorization` | object |  |
| `implementation_ready` | false |  |
| `technical_evidence_valid` | false |  |
| `independent_review` | `verify_review_pending` |  |
| `draft_create_ready` | false |  |
| `publication` | `verify_publication_pending` |  |
| `human_signoff` | `verify_review_pending` |  |
| `completion_ready` | false |  |
| `next_action` | "resolve_blockers" |  |
| `errors` | string[] | Contract schema errors |
| `evidence_errors` | string[] |  |
| `stage_blockers` | object |  |
| `blocking_duplicates` | `duplicate`[] |  |
| `evidence_trust` | string | Evidence is self-attested; identity and truth are not authenticated |
| `mandate_trust` | "host-asserted" |  |
| `mandate_sha256` | null |  |
| `final_signoff_sha256` | null |  |
| `api_budget` | `api_budget` (optional) |  |

#### `verify_binding`

Normalized mandate binding; null unless the mandate is historically valid

| Field | Type | Description |
| --- | --- | --- |
| `target_repository` | string |  |
| `target_repository_id` | integer |  |
| `head_repository` | string |  |
| `head_repository_id` | integer |  |
| `head_ref` | string |  |
| `base_ref` | string |  |
| `credential_actor_id` | integer |  |
| `contract_sha256` | string |  |
| `issued_at` | string |  |
| `expires_at` | string |  |
| `mandate_sha256` | string |  |

#### `verify_check_run`

| Field | Type | Description |
| --- | --- | --- |
| `id` | integer |  |
| `name` | string |  |
| `app_slug` | string |  |
| `app_id` | integer |  |
| `head_sha` | string |  |
| `status` | "queued" \| "in_progress" \| "completed" \| "waiting" \| "requested" \| "pending" |  |
| `conclusion` | "success" \| "failure" \| "neutral" \| "cancelled" \| "skipped" \| "timed_out" \| "action_required" \| "stale" \| "startup_failure" \| null | Null unless status is completed |
| `url` | string | Empty when GitHub gave none |

#### `verify_draft_update`

Host-context 0.2 draft_update report (#21, slices 1-2): bindings, then recognition after the one host push; never authorizes a push

| Field | Type | Description |
| --- | --- | --- |
| `status` | "not_evaluated" \| "recognized" \| "blocked" \| "invalid" | recognized: the draft was recognized at the one pushed update head (candidate_head); blocked: the live head moved but recognition failed (see errors); not_evaluated: the draft is still at from_head, and pre-push readiness is not evaluated by this version; invalid: schema or binding errors |
| `trust` | "host-asserted" |  |
| `sha256` | string or null | Canonical hash of the draft_update section; null when the host context is invalid |
| `from_head` | string or null | The record's from_head; null when the host context is invalid |
| `candidate_head` | string or null | The exact validated evidence HEAD that was recognized; non-null exactly when status is recognized |
| `live_head` | string or null | The live PR head of the first complete read; null when it was not read |
| `current` | boolean | Whether the record's interval contains the verification time |
| `errors` | string[] |  |
| `note` | string |  |

#### `verify_live_provenance`

Provenance of the live inspect refresh

| Field | Type | Description |
| --- | --- | --- |
| `pulls` | `list_scan` |  |
| `labels` | `list_scan` |  |
| `policy_state` | "missing" \| "present" \| "unknown" |  |
| `policy` | `policy_file` |  |
| `proposed_target_pulls` | `target_pulls_scan` (optional) |  |
| `proposed_target_metadata` | `metadata_read` (optional) | Schema 0.1 fork target metadata read |

#### `verify_overlap_dispositions`

Host-context 0.2 overlap_dispositions report; waives only topical overlaps whose bound observations still hold

| Field | Type | Description |
| --- | --- | --- |
| `status` | "absent" \| "evaluated" \| "invalid" | absent: no section; evaluated: bindings valid and each entry checked against fresh reads; invalid: schema, binding or expiry errors, nothing waived |
| `trust` | "host-asserted" |  |
| `sha256` | string or null | Canonical hash of the overlap_dispositions section; null when absent or the host context is invalid |
| `errors` | string[] |  |
| `waived` | `verify_waived_overlap`[] |  |
| `unused` | integer[] | Disposed PRs that match nothing now; informational |

#### `verify_own_pr`

The verified own exact-head draft PR; null otherwise

| Field | Type | Description |
| --- | --- | --- |
| `repository` | string |  |
| `repository_id` | integer |  |
| `number` | integer |  |
| `id` | integer |  |
| `url` | string |  |
| `head_sha` | string |  |
| `head_ref` | string |  |
| `base_ref` | string |  |
| `author_id` | integer |  |
| `created_at` | string |  |

#### `verify_publication`

| Field | Type | Description |
| --- | --- | --- |
| `status` | "unknown" \| "blocked" \| "absent" \| "own_draft" | absent: no exact-head PR history; own_draft: the claimed draft was verified |
| `verified` | boolean | identity_verified and no completion-stage blockers |
| `creation_clear` | boolean | Exact-head history and timing permit creating a draft |
| `own_pr` | `verify_own_pr` |  |
| `errors` | string[] |  |
| `provenance` | object | Empty when exact-head history was not checked (no valid mandate) |
| `provenance.publication_claim_trust` | "untrusted" (optional) |  |
| `provenance.authority_evaluated` | false (optional) |  |
| `provenance.history` | object (optional) |  |
| `provenance.history.endpoint` | string |  |
| `provenance.history.complete` | boolean |  |
| `provenance.history.pages` | integer |  |
| `provenance.history.matches` | integer |  |
| `provenance.history.errors` | string[] |  |
| `provenance.detail_endpoint` | string (optional) |  |
| `identity_verified` | boolean | The claimed PR matched the binding and evidence head |
| `stage_errors` | string[] | Blockers for verified |

#### `verify_publication_pending`

Placeholder; publication was not checked

| Field | Type | Description |
| --- | --- | --- |
| `status` | "unknown" |  |
| `verified` | false |  |
| `creation_clear` | false |  |
| `own_pr` | null |  |
| `errors` | string[] |  |
| `provenance` | object |  |

#### `verify_review`

Independent review recorded in the evidence

| Field | Type | Description |
| --- | --- | --- |
| `valid` | boolean |  |
| `status` | "pending" \| "invalid" \| "passed" |  |
| `errors` | string[] |  |
| `trust` | "self-attested" |  |

#### `verify_review_pending`

| Field | Type | Description |
| --- | --- | --- |
| `valid` | false |  |
| `status` | "pending" |  |
| `errors` | string[] |  |

#### `verify_signoff`

Final human sign-off from the host context

| Field | Type | Description |
| --- | --- | --- |
| `valid` | boolean |  |
| `status` | "pending" \| "invalid" \| "passed" |  |
| `trust` | "host-asserted" |  |
| `errors` | string[] |  |
| `sha256` | string or null |  |

#### `verify_unrefreshed_approval`

Placeholder before (or without) a live refresh

| Field | Type | Description |
| --- | --- | --- |
| `status` | "unknown" |  |
| `reason` | string |  |

#### `verify_user_authorization`

Host-asserted mandate checked against live credential facts; never proof of human consent. mandate_id, event_reference and event_text_sha256 are present once the host context validates

| Field | Type | Description |
| --- | --- | --- |
| `authorized` | boolean | historical_valid and not expired for new actions |
| `historical_valid` | boolean | The mandate matched the contract and credential when issued |
| `implement` | boolean | implement is currently authorized |
| `create_draft` | boolean | create_draft is currently authorized |
| `mandate_trust` | "host-asserted" |  |
| `mandate_sha256` | string or null |  |
| `credential_actor` | object or null | The authenticated GitHub user; null when unreadable |
| `credential_actor.id` | integer |  |
| `credential_actor.login` | string |  |
| `credential_actor.type` | "User" |  |
| `permission` | object or null |  |
| `permission.role_name` | "admin" \| "maintain" |  |
| `permission.user_id` | integer |  |
| `permission.endpoint` | string |  |
| `binding` | `verify_binding` |  |
| `actions` | "implement" \| "create_draft"[] |  |
| `errors` | string[] | Why the mandate is not historically valid |
| `current_errors` | string[] | Why a valid mandate does not authorize new actions now (expiry) |
| `source_errors` | string[] | Source identity failures; also listed in errors |
| `provenance` | `authorization_provenance` |  |
| `mandate_id` | string (optional) |  |
| `event_reference` | string (optional) |  |
| `event_text_sha256` | string (optional) |  |

#### `verify_waived_overlap`

A topical overlap waived by a host disposition at the observed PR state

| Field | Type | Description |
| --- | --- | --- |
| `repository` | string |  |
| `number` | integer |  |
| `url` | string |  |
| `reason` | string |  |
| `pr_id` | integer |  |
| `head_sha` | string |  |
| `base_tip_sha` | string |  |
| `updated_at` | string |  |
| `untrusted_rationale` | string | Host-supplied rationale, sanitized; untrusted text |

<!-- output-reference:end -->
