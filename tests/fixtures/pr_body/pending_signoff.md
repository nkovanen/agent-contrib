## Summary

Refs acme/photos#12

**Objective:** Reject out-of-bounds thumbnails

**Scope:** allowed src/\*\*; prohibited .github/\*\*

## Acceptance criteria

Supplied evidence did not pass `verify`; its statuses below are unverified claims.

- bounds: Malformed dimensions return an error (unverified claim: passed: Regression rejects 0x0)

## Validation

- unit (tests): argv ` ["python3", "-m", "unittest"] `; unverified claim: status passed, exit 0, tests run 7, skipped 0

Evidence is self-attested by the contributor; the verifier does not prove that tests ran.

## Review and sign-off

- Independent review: unverified claim: passed by independent
- Human signoff: unverified claim: pending

## Verification gates

`agent-contrib verify` reported (text neutralized, none omitted):

- `execution_ready`: yes
- `evidence_valid`: no
- `upstream_submission_ready`: no
- `fork_completion_ready`: no

Pending gates (1):
- evidence: human\_signoff is missing, failed, pending or stale

## Overlap scan

Live refresh complete: yes. Overlapping PRs: 0.
- Source open PRs (acme/photos): complete yes, pages 1, errors 0

Only open PRs are scanned; PRs that are no longer open, timeline claims and file-level conflicts are not checked.

## AI assistance disclosure

Prepared with Agent Contrib CLI 0.3.0. Contract SHA-256: `b673ee6e2a4f664683592e7b545978d2a23ce5359cad86df1c280b1b6249f05c`.

## Pull request template

No pull request template exists at the pinned commit `aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa`.

<!-- Rendering is not publication authority. -->
