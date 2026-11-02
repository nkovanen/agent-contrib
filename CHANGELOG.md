# Changelog

## 0.3.0 — unreleased

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
