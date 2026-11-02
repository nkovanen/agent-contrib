# Development status

The published release is **v0.2.0**. This branch contains unreleased v0.3.0 work;
these entries describe implementation scope, not closed issues or a release.
The Skill stays portable and all GitHub operations in the CLI remain read-only.

## Implemented on this branch

| Issues | Delivered behavior |
| --- | --- |
| [#3](https://github.com/nkovanen/agent-contrib/issues/3) | Explicit schema 0.2 same-repository candidate mandates, separate lifecycle stages and exact-head own-draft recognition. Schema 0.1 retains its decisions. |
| [#4](https://github.com/nkovanen/agent-contrib/issues/4) | Quiet handling of closed or missing stdout, preserving writable output and caller-provided streams. |
| [#10](https://github.com/nkovanen/agent-contrib/issues/10) | Read-only repository audit with policy, instruction coverage and issue-quality observations. |
| [#13](https://github.com/nkovanen/agent-contrib/issues/13) | Multi-repository discovery with independent results, failure isolation and merged candidate ordering. |
| [#14](https://github.com/nkovanen/agent-contrib/issues/14), [#15](https://github.com/nkovanen/agent-contrib/issues/15) | Unfilled evidence skeletons and offline local scope checks using the same path rules as verification. |
| [#19](https://github.com/nkovanen/agent-contrib/issues/19) | PR-description rendering with live blockers, neutralized remote text and a pinned template pointer. It neither fills templates nor publishes. |
| [#20](https://github.com/nkovanen/agent-contrib/issues/20) | Read-only feedback on reviews, comments and exact-head checks, with strict response and pagination validation. |
| [#12](https://github.com/nkovanen/agent-contrib/issues/12) | Opt-in location (paths, file and module names), clarity, activity and association signals, and an opt-in one-read repository responsiveness sample. Association is not verified maintainer identity. |

## Partially implemented

| Issues | Available now | Still missing |
| --- | --- | --- |
| #5, #6 | Opt-in ownership, claims and prior-resolution reports | Adoption into readiness rules; current reports never change gates |
| #8 | Located AI-policy excerpts with explicit scan coverage | A versioned machine-readable refusal policy; excerpts are not a policy verdict |
| #16 | Aggregate issue/policy/overlap drift and pinned per-file instruction comparison | Historical per-component issue baselines in a new task schema |
| #17 | Exact-head CI observations | Required-check declarations and readiness enforcement |
| #24 | Opt-in text CLI summaries | Output JSON Schemas and an explicit output-schema version |
| #25 | Literal POSIX path and containment regressions | Working Windows host-context input and tested Windows/macOS CI |
| #27 | Optional rate-limit budget reports and a minimum-budget guard | Authenticated, freshness-aware response caching |

These reports expose uncertainty; they do not authorize work or turn observed
CI success into evidence that the required contract checks ran.

## Deferred

Overlap dispositions (#7), actor-specific label approval (#9), a reusable Action
(#11), signed evidence (#18), draft updates (#21), a new fork route (#22) and
mandate issuance (#23) need separate trust-boundary designs. In particular, fork
ownership is not permission to publish upstream, and a local interactive prompt
is not proof of human presence. PyPI publication (#26) and an external benchmark
(#28) have not been implemented.

The bounded discovery limit in [PR #2](https://github.com/nkovanen/agent-contrib/pull/2)
remains independent. This branch does not incorporate or modify that PR.

## Acceptance and next steps

The fresh-agent trial discovered issue #4 without an issue-specific prompt,
prepared a contract, stopped for real task approval, then implemented and passed
technical verification and independent review. It was authorized for local
implementation only. Draft publication and final human sign-off remain pending.

The trial did **not** satisfy the strict host-issuance acceptance criteria: its
nonce was generated after approval, a coordinator serialized the otherwise
faithful mandate, and independent human retention of the mandate hash was not
established. Policy clearance was a host assertion. This is a useful partial
trial, not proof of a completed autonomous authorization/publication workflow.
No native host issuer or cryptographic proof of human consent is implemented.

Next priorities are an explicit human/host issuance handoff, a separately
authorized draft-publication acceptance round, and a versioned opt-out policy.
Resolve those boundaries before adding waivers, draft updates or a new fork route.
Release only after final-commit tests, independent review and hosted CI; nothing
in this status page authorizes a merge or release.
