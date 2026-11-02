# Architecture and contributor workflow

Agent Contrib separates a small portable adapter from a versioned protocol.

- **Skill:** asks the installed CLI for its workflow, then uses the host agent's
  normal tools. One canonical source is packaged and exported without overwrite.
- **CLI (`agent_contribute.cli`):** fixed commands and canonical JSON, with optional text summaries;
  exclusive local contract, evidence-skeleton, PR-body and Skill writes; no model, task executor or GitHub write operations.
- **Library (`agent_contribute.core`):** GitHub GETs through `gh`, bounded discovery,
  repository resolution, policy evaluation, contract/evidence validation and
  defensive Git reads. The agent still judges feasibility and implements work.
- **Schemas and instructions:** release resources read through Python's package
  resource API, not a source-checkout path. No LightCraft imports or build system.

The installed workflow from `agent-contrib instructions` is authoritative. This
page is an overview, not a second independently maintained execution protocol.

1. Discover the requested repository's tracker, resolving one parent when needed.
2. Rank feasible work; inspect requirements, repository policies, ownership and
   PR overlap. Manually check timeline claims and recently merged work.
3. Prepare and review a scoped contract. Candidate issues remain candidates
   until the source's explicit approval policy says otherwise.
4. Verify execution gates and the user's actual scope. A bare help request stops
   at a reviewable draft; existing explicit authority is honored.
5. Use an isolated branch/worktree and the agent's own implementation tools.
   Inspect build/test commands before running them.
6. Record real revision-bound validation and artifacts. Obtain independent
   adversarial review and final-revision human sign-off.
7. Verify supplied evidence. Prepare a PR description following the discovered
   repository template and policies. Publication remains a separately authorized
   host action; never merge automatically.

GitHub is the source of truth. Task/evidence JSON is portable but not trusted
executable instruction. There is no central service, database, model credential,
agent subscription or automatic update channel.

CLI versions use semantic versioning; schema support is an explicit exact set
(`0.1` and explicit `0.2`). The closed schemas and bundled validator reject unknown
versions/properties and malformed JSON. A schema migration requires a future
reviewed release; it is never guessed from a contract.

## Same-repository candidates in schema 0.2

`authorization.py` checks an explicit human/host mandate against live GitHub
credential, role, repository and issue identities. `pr_identity.py` observes
exact-head PR history and details. `lifecycle.py` combines those facts with the
reviewed contract, technical evidence and separate final human sign-off.

Host context has independently hashed mandate, optional worker publication claim
and optional later human sign-off sections. It is explicit stdin/library input,
never discovered repository data. The host is responsible for the actual human
approval; the CLI labels the mandate host-asserted and verifies only GitHub facts
and record consistency.

Before implementation or first publication, overlapping PRs block. After a
separately authorized publication, exactly one matching draft can be recognized
at the tested commit. Every other overlap remains. Draft-stage success reports
whether to create or simply return the existing verified draft; completion still
requires final human sign-off. No draft-update lifecycle is implemented.

The old schemas and evaluator retain their behavior. The new mode does not
change the label approval policy or reinterpret a legacy task. Full details are
in [host authorization](host-authorization.md) and the installed workflow.

## Optional observations and local helpers

Ownership, prior-resolution hints, AI-policy excerpts and CI observations are
report-only additions. They cannot promote a candidate, satisfy a validation or
waive an overlap. `audit` reuses the discovery snapshot. `drift` compares current
facts with the pinned contract without rewriting it. Multi-repository discovery
keeps each repository's identities, errors and completeness separate.

`scope-check` and evidence verification share the path-scope evaluator. Evidence
initialization records observed Git facts and leaves claims unfilled.
`authorization-request` prepares an unsigned schema 0.2 mandate request and
issues nothing. `pr-body`
quotes live verification results with remote prose neutralized; it has no host
context input, so it omits schema 0.2 authority gates and human sign-off
rather than attesting or misstating them.

The [product map](product-map.md) lists what is shipped, partial and planned by
issue; [development status](development-status.md) records acceptance trials.
