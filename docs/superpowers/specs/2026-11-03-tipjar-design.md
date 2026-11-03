# Tipjar: repository invitations for useful agent work

Status: controller accepted manifest filename, vocabulary, limits, no inheritance,
pinned source and inspection-first staging; independent review pending; **not implemented**.
Baseline: `6d4aee1`. This document chooses a small manifest and a staged build,
not a new consent system. No product code changes belong to this design task.

## Product and decisions

Tipjar gifts useful **agent work**, never money. A repository can display a
machine-discoverable invitation alongside its contribution rules. Users can
also name any repository explicitly before jars have adoption. An absent jar
means **undeclared**, not closed, forbidden, approved or authorized.

Recommend root `.tipjar.json`, separate from `.agent-contrib.json`.
The latter has a closed schema and a precise, different meaning: approval of
issues bearing designated labels. Extending it would make old clients reject
otherwise valid approval policies. A new jar is CONTRIBUTING metadata, not a
FUNDING configuration, issue approval, command runner or publication grant.

Alternatives considered: add fields to the old policy (incompatible); store only
prose in CONTRIBUTING (useful today, but lacks a reliable discovery signal);
introduce a registry (operational cost before adoption). Keep prose policy review
and add one small, versioned file. No hosted registry, GitHub App, payments,
webhooks, dependency scanning or automatic repository-wide search in this work.

## Existing implementation, and what stays separate

- `core.repository_snapshot` pins the source default branch, reads its tree,
  instructions and `.agent-contrib.json`; `approval_for` returns candidate,
  approved or unknown. Missing approval policy already means candidate.
- `resolve_repository` uses the requested tracker, or one immediate parent when
  a fork's tracker is disabled. It preserves requested/source/proposed target.
  Source policy never comes from the contributor's fork.
- `discover_with_snapshot` ranks issues after bounded scans; `audit` reuses it.
  `prepare` produces a pending contract, not execution permission.
- `policy.report` separately inventories repository and owner `.github` policy
  files, pinned bytes, unresolved references, limits and an inventory hash.
  CLI discovery/inspection/preparation adds this report; `audit` currently does
  not. It is report-only and does not determine CLI success or verification.
- Installed `instructions.md` requires source-linked policy review, the
  `ai-policy-review` prerequisite and the requirements ledger. Hints do not prove
  prose compliance. The canonical Skill delegates to installed instructions;
  repository-specific rules do not belong in that Skill.
- Task/evidence 0.1 supports authorized fork experiments and label-approved
  upstream work. Explicit task 0.2 supports same-repository admin/maintain work
  with host assertions. A jar does not change these route meanings.

## Manifest 0.1

Welcome example (the two optional arrays can be omitted):

```json
{
  "schema_version": "0.1",
  "status": "welcome",
  "wanted": ["Documentation examples", "Small bug fixes with regressions"],
  "boundaries": ["Do not change public APIs", "Read CONTRIBUTING.md before choosing work"]
}
```

Smallest opt-out:

```json
{"schema_version":"0.1","status":"closed"}
```

Exact rules:

- Root must be an object. Only `schema_version`, `status`, `wanted`, `boundaries`
  are allowed. Version is exactly the string `0.1`; status is exactly `welcome`
  or `closed`. The first two fields are required; optional arrays default to
  empty only in the parsed report, without rewriting source bytes.
- Each array has at most 16 distinct strings. Each string is 1–500 Unicode code
  points and contains a character outside this fixed Unicode White_Space set:
  U+0009–000D, U+0020, U+0085, U+00A0, U+1680, U+2000–200A, U+2028–2029,
  U+202F, U+205F, U+3000. Thus U+0085 alone is blank; U+FEFF is nonblank.
  Reject C0 controls and DEL even in otherwise nonblank text. Use this explicit
  set in both parser/schema validation, never runtime-dependent whitespace
  shorthands. Preserve text as untrusted data; sanitize terminal output.
- Maximum raw file size: 16,384 bytes, including whitespace. Strict UTF-8 JSON;
  reject duplicate keys, nonfinite values, unknown fields, wrong types and
  unsupported versions. Do not partially accept a `welcome` from invalid data.
- `wanted` is a preference, not task eligibility, a score bonus or approval.
  `boundaries` are requirements to read and record in the existing ledger.
  Closed status dominates wanted work. Do not classify or execute these strings.
- No argv, hooks, scripts, environment variables, provider configuration, remote
  includes, credential fields, payment addresses or executable configuration.
  Text containing a command or link remains text. It is never run or followed
  automatically; a referenced relevant policy still needs ordinary host review.
- No path glob language or automatic natural-language policy evaluator in 0.1.
  Reviewers translate applicable boundaries into the contract's existing scope
  and requirements. Unclear applicability stays unresolved.

This intentionally allows readable constraints without inventing another policy
DSL. The CLI can enforce `closed` and unreadability; it cannot prove a proposed
patch obeys “do not change public APIs.”

## Read states and provenance

Read the **actual issue source's** root file at the same default-branch commit
used for inspection. A direct `jar owner/repo` inspects that repository itself,
without tracker resolution or issue/label/PR reads. Discovery explicitly says
which source it inspected. Never read a worker branch as source policy.

Use validated metadata, a full 40-hex commit, a complete pinned tree and the exact
`.tipjar.json` entry. Accept only a regular blob (`100644` or `100755`), not a
symlink, tree or submodule. Require unique tree paths, matching content-response
blob identity, and recompute Git blob SHA-1 from bytes (as `policy._pinned` does).
Do not silently fall back to mutable contents or a different branch. Cache hits,
if used later, must retain existing live-tree blob verification.

| Observed state | Report `state` | `complete` | Consequence |
| --- | --- | --- | --- |
| Complete tree has no exact root entry | `undeclared` | true | Explicit targeting remains available; never call this a refusal |
| Valid supported welcome | `welcome` | true | Invitation only; other policy and route gates remain |
| Valid supported closed | `closed` | true | Stop selecting/preparing agent contributions through Tipjar |
| Malformed JSON/schema/UTF-8, oversized or unsupported version | `unknown` | false | No fallback to undeclared or a legacy welcome |
| Metadata/branch/tree/content read fails or tree is truncated | `unknown` | false | Cannot establish absence or invitation |
| Entry is unreadable, wrong kind or content/blob mismatch | `unknown` | false | Fail closed, retain available identity and reason |

A content endpoint 404 after the pinned tree lists the jar is a failed read,
not absence. Repository 404 likewise is unknown. The raw `jar` inspection exit
is 0 for complete states (including closed and undeclared), 1 for unknown/read
failure, 2 for usage errors. It reports facts; its exit code is not permission.

Report shape `tipjar-report/1`: `repository`, `default_branch`, `commit`,
`path` (always `.tipjar.json`), `blob_sha` and `sha256` (nullable when unavailable),
`fetched_at`, `state`, `complete`, `manifest` (validated object or null), `errors`
(bounded reason strings), and `notice` saying invitation is not approval or
execution/publication authority. Do not emit unvalidated raw config as policy.
Record exact byte SHA-256 before parsing where bytes were available. A bad blob
match may be reported but is not trusted provenance. A report with no tree or
commit must retain nulls, never fabricated identities.

When integrated, jar bytes enter the source-linked policy inventory even if
there are no prose hints. Manifest state and pinned absence/unknown must also
enter its fingerprint. Keep the historical instructions allow-list and
`instructions_sha256` unchanged, so old task baselines can be reconstructed.
Bump inventory format 2 to 3; tag/hash the format as today. Jar reads have a
separate fixed budget of at most four `gh api` invocations per jar inspection
(metadata, commit, tree, contents), without application retries. GitHub CLI may
follow internal HTTP redirects, so this is not a cap on raw HTTP GETs.
Validate canonical repository identity after redirects and reject a renamed
identity; never follow application-returned URLs. Every jar read site, including
historical and integration reads, uses the existing `request_once` path; do not
call helpers that silently use retrying `request`. A transient failure yields
unknown immediately, without retry or fallback. Only test clients lacking
`request_once` may fall back to their fake `request`; never fall back after an
existing `request_once` fails. Jar reads never consume a prose-policy file slot
or bypass a hiding limit. With `--report-budget`, the before/after `rate_limit`
snapshots are separate instrumentation outside the jar's four command reads;
the total command invocation count includes those snapshots and their existing
retry behavior, so do not advertise four invocations for the instrumented command. Do not silently treat
an old inventory digest as proof of jar review. Reconstruct historical jar state
at `task.source.commit` for drift; reread current state at each live gate.
Compare presence/state and exact-byte digest, not commit advancement alone. Any
jar change since preparation requires refreshing and reviewing the contract; a
failed baseline read is unresolved. This binds boundaries without new task fields.

## Conflicts, forks and owner policy

Read all ordinary policy sources regardless of jar status. A welcome cannot
waive a refusal or unresolved rule in CONTRIBUTING, AI policy, nested applicable
instructions or owner `.github` community policies. `.agent-contrib.json`
matching labels cannot override a closed jar. A jar cannot override label
policy unknowns either. For contradictory prose, stop and have the human resolve
it with the source owner; do not infer “the more specific welcome wins.” This
proposal authorizes no contact with maintainers.

Manifest 0.1 has **no inheritance**. Only the actual source root jar declares
that source's welcome. `owner/.github/.tipjar.json` declares the `.github`
repository itself; it does not natively or implicitly declare every owner repo.
Existing owner community-policy inventory remains required, with its current
404/not-accessible caveat and unresolved-read handling. Ordinary owner prose
explicitly governing all projects still binds. Do not advertise exhaustive
organization-policy coverage. No new owner manifest lookup is needed.

A permissive fork cannot waive the source's closed declaration or contribution
boundaries. Preserve source and destination identities in reports/contracts;
review a separately targeted destination's actual restrictions before publishing
there. A fork with an enabled tracker is its own issue source, as today: its jar
does not invite work into its parent. Tipjar's closed signal stops this guided
contribution workflow, including using a fork route to evade a source opt-out.
It is not a claim that a license prohibits unrelated private experimentation.

## Exact user paths

### Find welcomed repositories among a supplied set (planned)

Users obtain names from projects they use, bookmarks, a colleague, or a list they
provide. Existing `discover owner/repo`, positional lists and `--repositories-file` take explicit identifiers;
there is no global jar index and GitHub does not search arbitrary filenames for
this tool. Do not claim that Tipjar can yet find every welcoming repository.

```sh
agent-contrib discover acme/one acme/two --welcomed-only
agent-contrib inspect 'acme/one#12' --ownership
agent-contrib prepare 'acme/one#12' --output task.json
```

`--welcomed-only` is an explicit filter, not a change to default discovery.
Each source has `selection: {mode, included, reason}`; mode is `explicit` or
`welcomed-only`. Output version 2 declares both enum values when introduced
in Task 3, although Task 3 emits only `explicit`. Task 4 starts emitting
`welcomed-only` without changing that published schema. A compatibility
regression must validate Task 4 output against the unchanged Task 3 schema.
Default discovery may retain diagnostic issue findings for
closed/unknown sources, but excludes them from combined selectable candidates.
Welcome and undeclared remain selectable in explicit mode, subject to policy review.
Check each resolved source jar before admitting its issues. Closed, undeclared
and unknown sources stay visible in per-repository summaries with their states,
but have no selectable issues in this view. Unknown makes the combined command
incomplete/exit 1; known exclusions do not. Preserve caller identities and every
underlying issue/PR completeness gate. A valid welcome means “declared welcome;
policy review required,” never “approved” or “safe to run.” Review all policy
before choosing and preparing a task. No candidate is promoted by this flag.

### Explicitly target a repository without a jar (available today)

```sh
agent-contrib discover acme/project --signals
agent-contrib inspect 'acme/project#12' --ownership
agent-contrib prepare 'acme/project#12' --output task.json
agent-contrib lint task.json
agent-contrib verify task.json
```

After integration these same commands display `undeclared`, and still return
candidate work/drafts. No `--force`, opt-out bypass or “accept missing policy” flag
is needed. Read policies and resolve prerequisites; preparation is not execution.
Fresh `verify` is expected to report pending authorization and other blockers.

For an already available immediate fork, review the draft, record real local
execution authorization and set the existing 0.1 execution fields:
`mode: fork-experiment`, `target_repository: your-account/your-fork`,
`authorized_by`, `authorization_evidence`. A disabled-tracker fork may be named
in the first three commands instead; the parent remains the actual source.
The CLI does not create the fork. `verify task.json` must pass execution gates
before implementation through host tools. Later evidence verification is:

```sh
agent-contrib verify task.json --evidence evidence.json --repo-dir path/to/checkout
```

Fork completion never authorizes upstream submission. A user with actual
admin/maintain authority can instead explicitly prepare task 0.2 using
`--schema-version 0.2`, then follow existing host-mandate/stage instructions.

**Existing gap:** a no-jar arbitrary repository without a matching label policy
cannot pass schema 0.1 upstream mode merely because an outside user chose it;
0.2 requires admin/maintain. A local checkout with no immediate GitHub fork also
has no verified 0.1 fork route. Discovery, assessment and pending preparation
work; unrestricted external upstream execution/publication does not. A welcome
jar alone does not close either gap. Do not advertise a complete arbitrary-repo
upstream pipeline. The full no-jar manual-tip vision includes ordinary,
policy-compliant upstream PRs; local/fork completion is only a partial path.

**Next separate design assignment:** a compatibility-safe outside-contributor
route, likely a new task schema with explicit human-selected source and pinned
source-policy review. Its source-policy basis must distinguish a valid welcome
invitation from an undeclared jar with reviewed ordinary contribution policies;
neither absence nor a host assertion becomes maintainer approval. Preserve
`approval.status: candidate` where no label approval exists. A welcome supplies
an actual source invitation for that future route, subject to all boundaries;
it is not merely a decorative discovery signal. Closed, unreadable or unresolved
policy still blocks either basis. Scoped implementation authorization and exact
publication authorization remain separate host decisions. Do not remove the
0.1 approved-label check, relax 0.2 admin/maintain requirements, or let a task's
self-asserted policy review grant authority. Define the new schema/host assertion
binding in that separate assignment; no new issuer system is proposed here.
This route is central follow-up work, not permanently deferred.

## Compatibility and shipping boundaries

Manifest 0.1, report 1, output-schema version, inventory format and CLI SemVer
are distinct. Keep task/evidence 0.1 and 0.2 and host-context schemas unchanged.
Unknown manifest/task versions fail closed. Keep `.agent-contrib.json` exactly
as it is; no migration, aliases or dual-file approval precedence.

First slice is a runnable **inspection-only** `jar owner/repo` command with tests,
packaged schemas, and truthful limitations. Existing commands do not yet enforce
its result; do not ship it as full workflow support. Later integrate inventory,
discovery and live guards together. New live guards may make an old contract
unready when its source has become closed/unknown: document this safety behavior,
but do not rewrite or invalidate the contract's schema. Missing jar alone leaves
old route behavior intact. Old installed clients do not enforce this manifest;
maintainers should also state refusals plainly in existing contribution docs.

Inspection alone adds `schemas/output/1/jar.schema.json` and registers the new
command; it keeps `outputs.VERSION` at `1` because no existing command shape
changes. Do not clone the schema set for this slice. Later integration adds
fields to existing outputs: then bump `outputs.VERSION` from 1 to 2, publish the
complete command schema set under `schemas/output/2` and preserve version-1
resource files. Do not put jar fields into old contract objects or silently widen old
schemas. Format-3 policy review remains the existing host ledger obligation;
old digests remain recognizable as historical, not proof of new review. Existing
validators cannot prove the prose in that ledger is true.

Controller selects the release target; recommend additive inspection in the next
minor release, and explicit compatibility notes for the later tightening. This
spec does not change release version statements or create a release.

## Controller decisions and acceptance

Controller accepted `.tipjar.json`, welcome/closed vocabulary, the
16 KiB/16 items/500 characters bounds, no owner-jar inheritance, pinned source
and inspection-first staging. Inspection-only output stays at version 1; later
existing-shape changes can bump it. Supplied-repository discovery and prose
boundaries keep this proposal small.

The controller will assign the no-jar upstream route design separately next;
review must not mistake fork completion for full delivery of that product goal.
Acceptance for this manifest work is: missing is visibly undeclared and manually
targetable for assessment; welcome is discoverable among named repositories
without granting execution/publication authority; closed and uncertain data
never become welcome; source/fork/owner conflicts retain the correct provenance;
old contracts retain format and route meaning; no remote writes or execution
paths are added. The present deliverable ends at committed design and plan;
implementation and the separate upstream-route design require their own tasks.
