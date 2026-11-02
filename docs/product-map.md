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

Details: [command reference](cli.md) and [CHANGELOG](../CHANGELOG.md).

### Implemented
- [3] Task-scoped owner/maintainer authorization: schema 0.2, host-context mandate, exact-head draft recognition, `implementation`/`draft`/`completion` gates ([#3](https://github.com/nkovanen/agent-contrib/issues/3))
- [3] Closed or missing stdout without traceback ([#4](https://github.com/nkovanen/agent-contrib/issues/4))
- [3] A1 Ranking signals: code location (paths, file and module names), clarity, activity, author association, and an opt-in one-read responsiveness sample ([#12](https://github.com/nkovanen/agent-contrib/issues/12))
- [3] A2 Multi-repository discovery, 2–20 repositories, isolated results ([#13](https://github.com/nkovanen/agent-contrib/issues/13))
- [3] C3 `audit`: read-only maintainer report ([#10](https://github.com/nkovanen/agent-contrib/issues/10))
- [3] D1 `evidence init` skeleton from observed Git facts ([#14](https://github.com/nkovanen/agent-contrib/issues/14))
- [3] D2 `scope-check` offline scope check ([#15](https://github.com/nkovanen/agent-contrib/issues/15))
- [3] F1 `pr-body` description from contract, evidence and live gates ([#19](https://github.com/nkovanen/agent-contrib/issues/19))
- [3] F2 `feedback`: reviews, comments and exact-head checks on a PR ([#20](https://github.com/nkovanen/agent-contrib/issues/20))
- [3] Requirements-ledger workflow, contract field mapping, local-only (implement-only) profile and coordinator relay rules in the installed workflow

### Partly implemented
- [~] B1 Ownership claims and cross-repository linked PRs, report only ([#5](https://github.com/nkovanen/agent-contrib/issues/5)). Missing: adoption into readiness gates
- [~] B2 Possible prior fixes and rejected approaches, report only ([#6](https://github.com/nkovanen/agent-contrib/issues/6)). Missing: adoption into readiness gates
- [~] C1 Default-on `repository_policy` report: bounded inventory of policy files incl. the owner `.github` repository, high-recall hints, unassessed and omitted sources, no verdict; mandatory workflow review recorded as `ai-policy-review` ([#8](https://github.com/nkovanen/agent-contrib/issues/8)). Missing: a versioned machine-readable opt-out policy and verifier enforcement
- [~] D3 `drift` report with per-file instruction comparison ([#16](https://github.com/nkovanen/agent-contrib/issues/16)). Missing: per-component issue baselines in a new task schema
- [~] E1 `verify --observe-ci`, report only ([#17](https://github.com/nkovanen/agent-contrib/issues/17)). Missing: required-check declarations and gating
- [~] F5 `authorization-request` and normative [host issuer requirements](host-authorization.md#host-issuer-requirements) ([#23](https://github.com/nkovanen/agent-contrib/issues/23)). Missing: a native issuer in Claude Code or Paseo
- [~] G1 `--format text` summaries ([#24](https://github.com/nkovanen/agent-contrib/issues/24)). Missing: output JSON Schemas and an output-schema version
- [~] G2 Literal POSIX path decisions pinned ([#25](https://github.com/nkovanen/agent-contrib/issues/25)). Missing: Windows host-context input and Windows/macOS CI
- [~] G4 `--report-budget` and `--min-remaining` ([#27](https://github.com/nkovanen/agent-contrib/issues/27)). Missing: freshness-aware response cache

## Planned

- [ ] Bounded `discover --limit` display ([#1](https://github.com/nkovanen/agent-contrib/issues/1), draft [PR #2](https://github.com/nkovanen/agent-contrib/pull/2), not part of the candidate)
- [ ] B3 Reviewed overlap dispositions bound to live PR state ([#7](https://github.com/nkovanen/agent-contrib/issues/7))
- [ ] C2 Actor-verified approval labels (maintainer-applied only) ([#9](https://github.com/nkovanen/agent-contrib/issues/9))
- [ ] C4 Passive verification GitHub Action for maintainers ([#11](https://github.com/nkovanen/agent-contrib/issues/11))
- [ ] E2 Signed commits and SSH-signed evidence attestations ([#18](https://github.com/nkovanen/agent-contrib/issues/18))
- [ ] F3 Fast-forward draft updates with fresh evidence ([#21](https://github.com/nkovanen/agent-contrib/issues/21))
- [ ] F4 Fork-to-upstream route in schema 0.2 ([#22](https://github.com/nkovanen/agent-contrib/issues/22)) (after C1)
- [ ] G3 PyPI trusted publishing with build provenance ([#26](https://github.com/nkovanen/agent-contrib/issues/26)) (needs maintainer decision)
- [ ] H1 Blind task-selection benchmark from historical issues ([#28](https://github.com/nkovanen/agent-contrib/issues/28))

Each planned item and each "Missing" part needs its own trust-boundary design.
Fork ownership is not permission to publish upstream, and a local interactive
prompt is not proof of human presence.

## Suggested sequence

1. Release v0.3.0 after the acceptance gate in [development status](development-status.md).
2. Maintainer safety: C1 opt-out policy, a native issuer for F5, then gate adoption of B1/B2.
3. Contributor ergonomics: G1 output schemas, #1.
4. Lifecycle: F3, then F4 and B3.
5. Trust and adoption: E1 gating, C2, C4, E2.
6. Scale and reach: G4 cache, G2, G3; H1 to measure A1.

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
