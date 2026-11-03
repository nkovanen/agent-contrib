# Product map

What Agent Contrib does today, what the unreleased v0.3.0 candidate adds and
what comes next. `[x]` is shipped in the published v0.2.0 release, `[3]` is
implemented in the v0.3.0 candidate (unreleased), `[~]` is partly implemented
and `[ ]` is planned. Keys (A1, B2, …) are referenced from the issues. Order
within a section is not priority. This page is the per-issue status;
[development status](development-status.md) records acceptance trials and the
release gate.

Every item keeps the core invariants: read-only GitHub access, no model or task
executor in the CLI, untrusted remote text, fail-closed incompleteness, and
separate source approval, execution authorization and publication authority.

## Tipjar invitation status

- [3] Inspection-only `jar owner/repo`: strict root manifest 0.1, pinned identities,
  welcome/closed/undeclared/unknown reports and preserved output schema 1; integrated reports use output schema 2.
- [3] Enforce jar declarations in discovery, preparation and live verification.
- [3] Filter supplied repository names by declared welcome; no global registry.
- [ ] New policy-reviewed outside-contributor upstream route for welcome or
  manually selected no-jar repositories. Existing fork/owner routes cover only
  part of this goal; a jar alone grants no execution or publication authority.

Explicit no-jar discovery and pending preparation remain available. See
[jar inspection](cli.md#jar-inspection-candidate-inspection-only) for the exact
source-policy boundary and route limitations.

## Shipped in v0.2.0

### Discovery and selection
- [x] `discover owner/repo`: open issues, ranked by deterministic heuristics
- [x] `inspect owner/repo#N`: detailed issue snapshot with policy, instructions and exclusions
- [x] One-hop fork resolution: forks with Issues disabled read the parent's tracker, keep the fork as proposed target
- [x] Distinct requested/source/proposed-target identities with provenance
- [x] Instruction discovery at the default-branch commit: README, CONTRIBUTING, nested AGENTS.md/CLAUDE.md, PR template, architecture/spec indexes (max 60 files, 200 kB each)
- [x] Exclusions: closed issues and `duplicate`/`invalid`/`wontfix`/`in progress`/`needs info`/`fixed` labels; assignee warnings

### Overlap and ownership
- [x] Open-PR scan, drafts included, on source and proposed target
- [x] Matches: local/qualified/URL issue references, branch numbers, title keywords, checklist IDs
- [x] Overlap blocks execution readiness; incomplete scans are `unknown`

### Approval and authority
- [x] Candidate by default; labels such as `good first issue` never approve
- [x] Opt-in `.agent-contrib.json` policy 0.1 (label-permission delegation), generic labels refused
- [x] `unknown` approval for unreadable or malformed policy
- [x] Execution modes `pending`, `fork-experiment` (live immediate-fork check), `upstream-contribution` (live approval)

### Contracts and evidence
- [x] `prepare`: schema 0.1 draft contract, exclusive creation
- [x] Strict task/evidence schemas 0.1 with bundled validator; unknown versions/fields, duplicate keys and NaN rejected
- [x] Canonical contract SHA-256
- [x] `verify`: separate `schema_valid`, `execution_ready`, `evidence_valid`, `fork_completion_ready`, `upstream_submission_ready`
- [x] Evidence checks: clean HEAD/tree, base ancestry authenticated through GitHub compare, allowed/prohibited path scope with renames, per-validation heads, timestamps, zero skips, test counts
- [x] Artifact hashing inside the checkout (32 MiB cap, containment)
- [x] Independent review and final human sign-off attestations; reviewer ≠ implementer
- [x] Gitlinks/submodules fail closed

### Safety and robustness
- [x] Fixed `gh api --method GET` argv, no shell; credentials never echoed
- [x] Bounded pagination, retries for transient errors, timeouts and an 8 MiB response cap
- [x] Terminal/Unicode control stripping for untrusted text
- [x] Hardened Git reads: no hooks, fsmonitor, replace objects, textconv/external diff
- [x] Validation argv is data; never executed

### Distribution and agent integration
- [x] `instructions`: installed workflow, schema support, no automatic updates
- [x] `skill --output`: canonical thin Skill export with SHA-256, no overwrite
- [x] Standalone wheel/sdist, clean-install check, CI on Linux Python 3.10–3.14
- [x] No runtime dependencies, hosted service or model provider

## v0.3.0 candidate (unreleased)

Details: [getting started](getting-started.md), [command reference](cli.md), [upgrading from 0.2](upgrading.md) and [CHANGELOG](../CHANGELOG.md).

### Implemented
- [3] Task-scoped owner/maintainer authorization: schema 0.2, host-context mandate, exact-head draft recognition, `implementation`/`draft`/`completion` gates ([#3](https://github.com/nkovanen/agent-contrib/issues/3))
- [3] Closed or missing stdout without traceback ([#4](https://github.com/nkovanen/agent-contrib/issues/4))
- [3] A1 Ranking signals: code location (paths, file and module names), clarity, activity, author association, and an opt-in one-read responsiveness sample ([#12](https://github.com/nkovanen/agent-contrib/issues/12))
- [3] Ranking aids, report only: `discover --signals --check-top N` (N 1–5, one repository) re-checks ownership of the top N and re-ranks only those; `discover --repo-dir` (one repository) reports issues referenced by local commits off the default branch and ranks them lower only with `--signals`
- [3] `lint`: offline check of a contract against its schema and the reviewed-contract rules
- [3] A2 Multi-repository discovery, 2–20 repositories, isolated results ([#13](https://github.com/nkovanen/agent-contrib/issues/13))
- [3] C3 `audit`: read-only maintainer report ([#10](https://github.com/nkovanen/agent-contrib/issues/10))
- [3] D1 `evidence init` skeleton from observed Git facts ([#14](https://github.com/nkovanen/agent-contrib/issues/14))
- [3] D2 `scope-check` offline scope check ([#15](https://github.com/nkovanen/agent-contrib/issues/15))
- [3] F1 `pr-body` description from contract, evidence and live gates ([#19](https://github.com/nkovanen/agent-contrib/issues/19))
- [3] F2 `feedback`: reviews, comments and exact-head checks on a PR ([#20](https://github.com/nkovanen/agent-contrib/issues/20))
- [3] G4 `--report-budget`, `--min-remaining` and an opt-in, blob-SHA-verified `--cache` for file contents of public repositories ([#27](https://github.com/nkovanen/agent-contrib/issues/27)); the cache needs a private directory chain, so a default Ubuntu `~/.cache` (0775) disables it unless `XDG_CACHE_HOME` points at a private directory
- [3] G1 `--format text` summaries and versioned output JSON Schemas for every command (`schemas/output/1/`, `agent-contrib schema`) ([#24](https://github.com/nkovanen/agent-contrib/issues/24))
- [3] Requirements-ledger workflow, contract field mapping, local-only (implement-only) profile and coordinator relay rules in the installed workflow
- [3] C2 Approval-label authority ([#9](https://github.com/nkovanen/agent-contrib/issues/9)): documented limitation; labeling-actor authority cannot be verified from public REST data (events name an actor, not its role). A maintainer-side label-actor report is deferred (R9-05, R9-06)

### Partly implemented
- [~] B3 Reviewed overlap dispositions bound to live PR state, host-context 0.2: active topical-overlap waivers and host issuer requirements ([#7](https://github.com/nkovanen/agent-contrib/issues/7)). Missing: a native host issuer that can produce the records
- [~] C4 Passive verification GitHub Action for maintainers, slice 1: `actions/verify/` checks the PR body's contract and evidence blocks against the PR's route, head, tree, base and scope from the event payload and the PR-head checkout, with no API calls ([#11](https://github.com/nkovanen/agent-contrib/issues/11), [design](design/2026-11-02-maintainer-action.md)). Missing: live checks (freshness, overlap, approval, identity), which are listed as not evaluated, and a live smoke test
- [~] G3 Release preparation: [release runbook](releasing.md), `tools/release_check.py` and a proposed PyPI trusted-publishing workflow with build provenance (`docs/examples/release-pypi.yml`, not activated) ([#26](https://github.com/nkovanen/agent-contrib/issues/26)). Missing: maintainer adoption of the workflow and a published PyPI release
- [~] F3 Draft updates, slices 1 and 2 of 4: a strictly validated host-context 0.2 `draft_update` record, host round requirements, and recognition of the draft after the one fast-forward host push ([#21](https://github.com/nkovanen/agent-contrib/issues/21)). Missing: pre-push readiness and the workflow ([design](design/2026-11-02-draft-updates.md))
- [~] H1 Offline task-selection benchmark (development only, not in the wheel): read-only snapshot collector, offline replay of discover and `--signals`, top-k precision with bounds for unjudged slots, a conditional bootstrap, a permutation null and a pre-registered held-out test; under the registered labels no ranking change qualifies ([results](benchmark.md), [#28](https://github.com/nkovanen/agent-contrib/issues/28)). Missing: reconstruction of PR titles renamed after the cutoff for PRs whose current title overlaps no issue (review BM-02, documented with its possible bias), the blind fresh-agent trial protocol, and overlap/exclusion correctness metrics
- [~] B1 Ownership claims and cross-repository linked PRs, report only ([#5](https://github.com/nkovanen/agent-contrib/issues/5)). Missing: adoption into readiness gates
- [~] B2 Possible prior fixes and rejected approaches, report only ([#6](https://github.com/nkovanen/agent-contrib/issues/6)). Missing: adoption into readiness gates
- [~] C1 Default-on `repository_policy` report: bounded inventory of policy files incl. the owner `.github` repository, high-recall hints, unassessed and omitted sources, no verdict; mandatory workflow review recorded as `ai-policy-review` ([#8](https://github.com/nkovanen/agent-contrib/issues/8)). Missing: a versioned machine-readable opt-out policy and verifier enforcement
- [~] D3 `drift` report with per-file instruction comparison ([#16](https://github.com/nkovanen/agent-contrib/issues/16)). Missing: per-component issue baselines in a new task schema
- [~] E1 `verify --observe-ci` (report only) and opt-in required CI checks for schema 0.2 completion: `ci_requirements` (check name plus app ID) gate `completion_ready` at the exact head ([#17](https://github.com/nkovanen/agent-contrib/issues/17), [design](design/2026-11-03-ci-gating.md)). Missing: pre-filling requirements and drift coverage (slice 3)
- [~] E2 `verify --observe-signatures`, report only: GitHub verification of the evidence head, required-signature rulesets and local signature-header presence ([#18](https://github.com/nkovanen/agent-contrib/issues/18)). Missing: contract-required verified heads and SSH-signed evidence attestations
- [~] F5 `authorization-request` and normative [host issuer requirements](host-authorization.md#host-issuer-requirements) ([#23](https://github.com/nkovanen/agent-contrib/issues/23)). Missing: a native issuer in Claude Code or Paseo
- [~] G2 Literal POSIX path decisions pinned; bounded host-context stdin transport and narrow Windows/macOS CI added ([#25](https://github.com/nkovanen/agent-contrib/issues/25)). Missing: full Git, cache and evidence workflow portability validation

## Planned

- [ ] Bounded `discover --limit` display ([#1](https://github.com/nkovanen/agent-contrib/issues/1), draft [PR #2](https://github.com/nkovanen/agent-contrib/pull/2), not part of the candidate)
- [ ] F4 Fork-to-upstream route in schema 0.2 ([#22](https://github.com/nkovanen/agent-contrib/issues/22)) (after C1)

Each planned item and each "Missing" part needs its own trust-boundary design.
Fork ownership is not permission to publish upstream, and a local interactive
prompt is not proof of human presence.

## Suggested sequence

1. Release v0.3.0 after the acceptance gate in [development status](development-status.md).
2. Maintainer safety: C1 opt-out policy, a native issuer for F5, then gate adoption of B1/B2.
3. Contributor ergonomics: #1.
4. Lifecycle: F3, then F4; a native issuer for B3 alongside F5.
5. Trust and adoption: E1 slice 3, C4 live checks, E2.
6. Scale and reach: G2, activating G3; H1 to measure A1.

## Parked ideas

Not yet issues; revisit when a real need appears.

- Multi-hop fork resolution (today: one parent).
- Submodule/gitlink evidence (today: fails closed).
- GitHub Enterprise Server and other forges (hostname is fixed to github.com).
- MCP server adapter exposing the read-only commands as typed tools.
- Local contribution ledger to avoid re-suggesting abandoned or rejected tasks.
- "Help what you use": candidate repositories from a project's dependency graph.
- Local-base mandates for stacked unpublished work (design preconditions in
  [docs/design](design/2026-11-02-owner-local-and-stacked-routes.md)).
