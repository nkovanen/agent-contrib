# Changelog

## 0.3.0 — unreleased

The v0.3.0 candidate adds a task-scoped authorization route (task schema 0.2),
read-only helper commands and report-only options, and hardens untrusted-input
handling. Schema 0.1 formats are unchanged and its routes keep their meaning;
every 0.1 behaviour change, including fail-closed hardening and message
changes, is listed under "Compatibility notes". No GitHub write API, merge, release
channel or runtime model provider is added.

### Added

- Explicit task and evidence schema **0.2** (`prepare --schema-version 0.2`) for
  one same-repository candidate issue (#3). A human/host-issued mandate in
  host-context schema 0.1 (`verify --host-context-stdin`, at most 8 MiB, 5 s) is
  bound to the contract hash, numeric repository, owner, issue and credential IDs,
  refs and actions. Live GETs require a personal credential with exactly the
  `admin` or `maintain` role. Mandates and sign-off are host-asserted, not
  cryptographic consent. The base must be the source default branch; a
  case-variant repository spelling is refused with `case_mismatch`.
- Separate schema 0.2 gates selected with `verify --stage
  implementation|draft|completion`. Implementation needs complete, empty
  exact-head PR history; without a valid mandate the blockers say `Exact-head PR
  history not checked: requires a valid mandate`. Exactly one authenticated open
  draft at the tested head is recognized after publication; unrelated overlaps
  still block. A draft created inside an expired mandate's interval stays
  recognized; new actions need a current mandate. Final sign-off is a separate,
  later host record whose expiry is checked after all GitHub reads.
- `authorization-request` (schema 0.2): an unsigned request with every mandate
  binding pre-filled from the contract and live reads and every human-only field
  `null`. It validates the full schema before any read, labels its diagnostics
  untrusted, contains no display summary and cannot pass as host context.
- `scope-check` (#15): offline check of committed, staged, unstaged and untracked
  paths with the same scope evaluator as `verify`.
- `evidence init` (#14): an evidence skeleton with only observed Git facts and
  contract IDs; it never runs argv or writes `passed` and fails validation until
  filled.
- `--base` for `scope-check` and `evidence init` accepts exactly a full SHA,
  `HEAD` or a full `refs/...` name, optionally followed by `~N`/`^N`, looked up
  exactly (never through Git's short-name lookup). Other forms are refused with
  a conversion hint. `scope-check` warns when the default base is not an
  ancestor of HEAD.
- `pr-body` (#19): a Markdown PR description from the contract, evidence and a
  fresh `verify`, with remote text neutralized and `Refs` by default. For schema
  0.2 it shows only `technical_evidence_valid` with source (including identity),
  evidence and review blockers, and says that authority gates, `next_action` and
  sign-off are omitted because it takes no host context.
- `feedback 'owner/repo#PR'` (#20): latest reviews, comments, outdated flags and
  failing or pending checks for the exact head. Each reviewer's decision is
  classified by the association on the review that made it (`decision_author`).
- `audit owner/repo` (#10): read-only maintainer report using exactly the reads
  `discover` makes.
- `drift task.json` (#16, part): issue, per-file instruction, branch, policy and
  overlap changes since preparation, plus changed source repository, issue URL
  and (0.2) numeric identities. It never rewrites the contract.
- Multi-repository `discover` (#13) for 2–20 repositories with isolated results
  and a merged candidate order; a single repository's output is unchanged.
- Optional reports that grant no approval or authority and change no readiness
  gate. `--signals` re-ranks candidates by its score after exclusions,
  overlaps and low likelihood; the others leave ordering unchanged:
  `discover --signals` (#12; code location including unique dotted and `::`
  module names, clarity, activity, author association; over-long, truncated or
  partly non-word module names are refused whole, never shortened), `discover
  --responsiveness` (#12; one read of recently closed PRs, skipped after an
  incomplete snapshot; malformed, repeated or out-of-interval PR entries make it
  `unknown`), `inspect
  --ownership` and `ownership` (#5, #6; a conflicting repository ID for one
  cross-referenced PR leaves the report incomplete), `inspect --ai-policy` (#8,
  part), `verify --observe-ci` (#17, part), `verify --observe-signatures` (#18,
  part; GitHub's verification of the evidence head, labelled as not approval;
  active `required_signatures` rulesets on the base branch; and, with
  `--repo-dir`, signature-header presence for at most 1000 commits in
  `base_commit..git_head`, never truncated; no gpg, ssh-keygen or
  `verify-commit` runs) and `--report-budget` / `--min-remaining` (#27, part).
  An opted-in report that is incomplete exits 1 where documented.
- `--format text` summaries (#24, part); JSON stays canonical and unchanged.
- `--help` describes every command and option, input constraints and exit status.
- Installed workflow: a source-linked requirements ledger, precommit gates,
  independent compliance review, the contract fields that hold the AI-policy
  review and ledger reference, an implement-only local profile, coordinator relay
  rules, the stacked-base limitation and normative host issuer requirements.
- Versioned JSON Schemas for every command's JSON output ship in
  `schemas/output/1/` (#24). `agent-contrib schema COMMAND` prints one (`error`
  is the error envelope), `instructions` reports `output_schema_version` and the
  directory, and `docs/cli.md` has a field reference generated from them. Every
  output the test suite produces is validated against its schema. Output values
  do not carry the version, so existing results are unchanged; a shape change
  bumps it. The bundled validator gained `null`, `number`, type lists, `anyOf`,
  local `$ref` and `additionalProperties` maps, which the task, evidence and
  host-context schemas do not use. It now checks every item of a list whose
  length the schema allows (previously only the first 1000) and rejects NaN and
  infinities as numbers. Output schemas state every length bound and anchor
  every pattern, so standard validators decide like the bundled one.
  Error, warning and other diagnostic lists, free text and remote-derived
  lists claim no cap below the input bounds, because producers never truncate
  them (R5-04).

### Changed

- The prerequisite blocker names each failing prerequisite, for example
  `Prerequisites are not satisfied with evidence: P1 (pending), P4 (satisfied
  without evidence)`. The condition is unchanged.
- A heuristic overlap `reason` ends with the shared title words and checklist IDs
  that triggered it. Matching and fields are unchanged.
- A global option placed after the subcommand is still a usage error; the
  message now says to move it before the subcommand. `discover` with no
  repository reports the missing `reference`.
- CLI input files are read once and validated before any GitHub or budget read,
  with identical errors with or without `--report-budget`. Schema-invalid
  `drift`, `pr-body` and `authorization-request` contracts make no GitHub read.

### Security

- Reject JSON strings containing a lone surrogate escape (`"\ud800"`) and
  numbers that overflow to infinity (`1e999`) as `invalid_json` in GitHub
  responses, contracts, evidence and host context. A lone surrogate used to
  abort a whole multi-repository `discover` at hashing time; an overflowing
  number in a repository policy used to crash `inspect` output. Now only the
  affected read or repository is incomplete or unknown.
- Overlap scans treat a PR whose `body`, `head` or `head.ref` is missing or has
  the wrong type as malformed, making the scan incomplete. Values such as `[]`,
  `false` or `0` used to be scanned as empty text. An explicit `null` body or
  head stays empty.
- `--repo-dir` must be the Git worktree top level for `verify`, `scope-check`
  and `evidence init` (`not_worktree_root`). From a subdirectory, tree, index and
  untracked reads omitted the rest of the checkout, hiding gitlinks and
  out-of-scope files.
- HEAD is captured once with an exact lookup and used for every tree, diff,
  ancestry, gitlink and timestamp read. An unborn or deleted branch, or a HEAD
  naming a non-commit, fails with `unborn_head`; a `refs/tags/HEAD` tag can no
  longer stand in for it.
- Schema 0.2 requires the collaborator-permission login to be a valid ASCII
  GitHub login before its case-insensitive comparison, so Unicode confusables
  such as `ſ` or the Kelvin sign no longer match.
- `verify`, `scope-check` and `evidence init` fail closed with `index_flags`
  when the index marks tracked paths assume-unchanged or skip-worktree
  (including sparse checkouts), because status and diff would hide changes to
  those files. The index is only read, never modified.
- Schema 0.2 binds the local branch by its exact full ref: symbolic HEAD must
  equal `refs/heads/` plus the reviewed `head_ref`, so a same-named tag or a
  name differing only by trailing Unicode whitespace no longer matches. Git
  output loses only its trailing newline, never other whitespace.

### Fixed

- Closed or missing stdout exits 1 quietly, including buffered errors and
  caller-provided write-only streams (#4). Help and version are unchanged.
- Library `verify` of a schema-valid 0.1 contract with host context keeps
  `schema_valid: true` and reports the refusal only in `errors`.

### Compatibility notes

- CLI/library versions follow semantic versioning; task, evidence and
  host-context schema versions are independent. Supported sets: task/evidence
  0.1 and 0.2, host-context 0.1. Unknown versions fail closed; nothing is
  migrated. `prepare` still defaults to 0.1.
- Schema 0.1 changes, all fail-closed or message-only:
  - `verify --repo-dir` from a subdirectory or Git directory now fails with an
    evidence error instead of reading part of the checkout.
  - An unborn, deleted or non-commit HEAD now fails with `unborn_head`.
  - An index with assume-unchanged or skip-worktree entries, including a sparse
    checkout, now fails with `index_flags`.
  - Malformed or missing PR `body`/`head`/`head.ref` fields now make discovery
    and verification scans incomplete instead of empty.
  - Lone-surrogate strings and overflowing numbers now fail as `invalid_json`;
    contracts or responses that used to fail with `input_error`, or to parse to
    infinity, change error code.
  - The prerequisite blocker and heuristic overlap reasons carry more detail,
    so their strings differ; the decisions do not.
  - Misplaced global options produce a more specific usage message.
  - `--base` grammar applies only to the new `scope-check` and `evidence init`;
    evidence `base_commit` stays a full SHA, so 0.1 `verify` is unaffected.
  - Lifecycle options (`--stage`, `--host-context-stdin`) are rejected for 0.1
    contracts rather than reinterpreted.
- Default `discover` read sequence and output structure are pinned by goldens.
  Individual values can still differ where listed above: heuristic overlap
  reasons and malformed-input completeness.

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
