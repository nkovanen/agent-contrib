# Changelog

## 0.3.0 — unreleased

- A failed GitHub read now says when it was HTTP 404 (not found or not visible
  to this account) or HTTP 401 (not authenticated) instead of always "check gh
  auth" (E-17). `gh` output is still never echoed; codes and exits are unchanged.
- `discover --signals` adds `code_location.named_paths_missing`: file paths the
  issue names that are not in the snapshot tree (F13). Report only; score and
  ordering are unchanged.
- Text `discover` shows each issue's overlapping-PR count, excluded flag and
  (with `--signals`) score, plus overlapping and excluded totals that include
  issues beyond the 20-line cap (F8). JSON is unchanged.
- `scope-check` warns when the default base is more than one commit behind
  HEAD and out-of-scope paths changed, naming the base and suggesting `--base`
  for stacked work (F36). Report only; violations and exit status are unchanged.
- Overlap detection no longer treats standards, algorithm or encoding names
  followed by numbers (`SHA-256`, `UTF-8`, `ISO-8601`, `RFC-3339`) as checklist
  IDs (F34). Fewer false overlaps; shared project IDs, CVEs and other uppercase
  IDs still overlap and block.
- `verify`, `scope-check` and `evidence init` capture HEAD once with an exact
  lookup and use that commit for every tree, diff, ancestry, gitlink and
  timestamp read (R4-05). An unborn or deleted current branch, or a HEAD naming
  a non-commit, now fails with `unborn_head`; previously a `refs/tags/HEAD`
  tag could stand in for it. This also hardens schema 0.1 `verify`.
- Schema 0.2 `user_authorization` adds `source_errors`, the source identity
  failures also listed in its `errors`; `pr-body` keeps them as source blockers
  instead of omitting them with the authority states (R1-10).
- Schema 0.2 authorization requires the collaborator-permission login to be a
  valid ASCII GitHub login before its case-insensitive comparison, so Unicode
  confusables such as `ſ` or the Kelvin sign no longer match (R1-08).
- Reject JSON strings containing a lone surrogate escape (such as `"\ud800"`)
  as `invalid_json` when parsing GitHub responses, contracts, evidence and host
  context (R1-07). Such a value used to raise an uncaught encoding error at
  hashing time, which aborted a whole multi-repository `discover`. It now
  makes only the affected repository incomplete. For schema 0.1 inputs this is
  a fail-closed hardening: a contract or response that already failed with
  `input_error` now fails with `invalid_json`.
- `drift` reports a source repository or issue URL change, and for schema 0.2 a
  changed repository, owner or issue numeric ID, as drift; an unresolved 0.2
  identity makes the report incomplete (R1-06).
- Schema 0.2 final sign-off expiry is checked at the current time after all
  GitHub reads, not at the start of `verify` (R1-05).
- Require `--repo-dir` to be the Git worktree top level for `verify`,
  `scope-check` and `evidence init` (R1-01). From a subdirectory, Git tree, index
  and untracked reads omitted the rest of the checkout, hiding gitlinks and
  out-of-scope untracked files. This also changes schema 0.1 `verify`: a
  subdirectory or Git directory now fails closed with an evidence error.
- Reject non-null, non-string PR `body`/`head.ref` and non-object `head` values in
  every overlap scan (R1-02). Values such as `[]`, `false` or `0` were scanned as
  empty text, so a complete-looking scan could report no overlap. `null` stays the
  only empty value. Schema 0.1 discovery and verification also fail closed on such
  data now (incomplete scan), a hardening of malformed-input handling only.
  A PR record missing its `body` or `head` key, or a `head` without `ref`, is
  likewise malformed and makes the scan incomplete; an explicit `null` body or
  head stays empty (R1-11). This also applies to schema 0.1.
- `feedback` classifies each reviewer's decision by the association on the review
  that made it, reported as `decision_author`; `author` is now the latest
  observation (R1-03). Previously the first review's association was kept.
- For schema 0.2, `pr-body` shows only `technical_evidence_valid` with source,
  evidence and review blockers, and states that authority gates, `next_action`,
  final sign-off and authorization blockers are omitted (A1-12). Without host
  context it previously rendered authorized work as unauthorized.

- Require a source-linked repository requirements ledger in the installed
  workflow, precommit gates before commits, and independent review of compliance
  as well as code. Include required docs, PR-visible artifacts and template items;
  do not equate passing CLI gates with prose compliance. Schemas are unchanged.

- Handle closed or missing stdout quietly, including buffered errors and
  caller-provided write-only streams (#4). Help/version behavior is unchanged.
- Add opt-in `--format text` summaries; JSON stays canonical (#24, part).
- Add offline `scope-check` (#15). `verify` and `scope-check` share one scope
  evaluator; schema 0.1 decisions are unchanged.
- Add `evidence init` (#14): an evidence skeleton prefilled only with observed
  Git facts and contract IDs. It never runs argv or writes `passed`, and it
  fails validation until filled.
- Add `pr-body` (#19): a Markdown PR description from the contract, evidence
  and live verify gates, with untrusted text neutralized and `Refs` by default.
- Add opt-in `discover --signals` (#12): code-location, acceptance-clarity,
  activity and maintainer signals with explanations; default output unchanged.
  Code location also resolves unique dotted and `::` module names.
- Add opt-in `discover --responsiveness` (#12): one extra read of recently
  closed PRs reporting the external merge rate and median days to close.
  Report only; an incomplete report exits 1 and changes no gate or ordering.
- Add read-only `audit owner/repo` (#10) for maintainers, using exactly the
  reads `discover` makes. Discover output and read order are frozen by goldens.
- Add read-only `feedback 'owner/repo#PR'` (#20): latest reviews, comments,
  outdated flags, bot authors and failing/pending checks for the exact head.
- Add opt-in, report-only ownership and resolution signals (#5, #6) via
  `inspect --ownership` and `ownership`; no gate or default output changes.
- Add opt-in `inspect --ai-policy` (#8, part): located AI-contribution
  statement excerpts from loaded instructions; the opt-out policy is deferred.
- Add read-only `drift task.json` (#16, part): per-file instruction changes from
  the pinned commit, issue, branch, policy and overlap changes; never rewrites.
- Add opt-in `verify --observe-ci` (#17, part): report-only check runs and
  combined status for the exact evidence head; gates and exit codes unchanged.
- Add opt-in `--report-budget` and `--min-remaining` (#27, part): rate-limit
  snapshots around a command; the response cache is deferred.
- Add multi-repository `discover` (#13) for 2 to 20 repositories with isolated
  per-repository results and a merged candidate order; one repository is unchanged.
- Pin literal POSIX scope and artifact path decisions across platforms (#25,
  part; no Windows or macOS support claim and no CI matrix change).
- Schema 0.2 `verify` reports `Exact-head PR history not checked: requires a
  valid mandate` instead of implying the history was read. Gates are unchanged.
- The prerequisite blocker names each failing prerequisite ID and status, for
  example `P1 (pending), P4 (satisfied without evidence)`.
- `--format text verify --stage X` leads with stage X, its exit gate and its
  blockers, and reduces other stages to blocker counts. JSON and exit codes are
  unchanged.
- Heuristic overlap reasons name the shared title words and checklist IDs that
  triggered the match. Duplicate entry fields and matching are unchanged.
- `scope-check --base` and `evidence init --base` accept a full SHA, `HEAD` or
  an exact `refs/...` name, optionally followed by `~N`/`^N` (previously only a
  full SHA). Short branch/tag names, abbreviated SHAs, other pseudo-refs and
  other revision syntax are refused with a conversion hint. `scope-check`
  adds a `warnings` list and warns when the default base is not an ancestor of
  HEAD.
- `agent-contrib --help` describes every command and option, including input
  constraints and exit status; the description no longer claims JSON-only output.
- A global option given after the subcommand is still a usage error, but the
  message now says to move it before the subcommand.
- `discover` with no repository again reports the missing `reference` instead
  of the 2-20 multi-repository bound. Exit status stays 2.
- `--format text` for `scope-check` lists violating paths, warnings and errors;
  for `drift` it lists each drift reason and informational changes separately.
- `pr-body` no longer renders a mangled `next_action` (previously
  `resolve_blockers` was escaped); with the A1-12 change it omits the value for
  schema 0.2 instead of showing it.

- Add explicit schema 0.2 for task-scoped same-repository candidate authorization.
  Live credential/role checks stay separate from host-asserted human mandates;
  repository policy approval is unchanged.
- Separate implementation, draft and completion gates. Recognize exactly one
  authenticated open draft at the tested head, preserving unrelated overlaps.
- Preserve schema 0.1 decisions and default preparation with golden fixtures.
- Add adversarial authorization/lifecycle/CLI tests and installed-resource checks.

This route is create-only, uses the source default branch and requires a personal
admin/maintain credential. Human records require an explicit host handoff; they
are not cryptographic consent. No merge, release, GitHub write API or runtime
model provider is added.

CLI/library versions follow semantic versioning. Task/evidence schema versions
are independent and require an explicit compatibility decision.

## 0.2.0 — 2026-11-01

First standalone release, extracted from the reviewed LightCraft experiment.
Licensed under MIT, with original attribution retained.

- Read-only GitHub issue discovery, policy/instruction inspection and open-PR
  overlap detection through `gh`.
- One-hop parent issue discovery for forks with Issues disabled; distinct
  requested, source and proposed-target identities with provenance.
- Draft task contracts and passive evidence verification using schema `0.1`.
- Separate repository approval, execution authorization and publication mandate.
- A portable Skill that loads the workflow from the installed CLI.
- Standalone Python packaging, GitHub installation and CI; no LightCraft or Rust
  build dependency. The 65 original protocol regressions are retained.
- Normalize Git UTC timestamps for Python 3.10 compatibility, with an additional
  regression covering newer Git versions that emit a trailing `Z`.

The standalone release preserves the POC's protocol behavior. Approval delegates
to accounts with label permissions; evidence is self-attested; topical overlap
and existing own drafts can block verification. No automatic submission,
execution harness, actor-specific approval or PyPI publication is included.

### Earlier experiment

The 0.1.0 prototype and development of 0.2.0 occurred in
[LightCraft PR #1](https://github.com/nkovanen/lightcraft/pull/1).
Historical pilot logs remain there rather than in this distribution.
