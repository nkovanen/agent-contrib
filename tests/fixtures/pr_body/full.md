## Summary

Refs acme/photos#12

**Objective:** Reject out-of-bounds thumbnails

**Scope:** allowed src/\*\*; prohibited .github/\*\*

## Acceptance criteria

- bounds: Malformed dimensions return an error (passed: Regression rejects 0x0)

## Validation

- unit (tests): python3 -m unittest; status passed, exit 0, tests run 7, skipped 0

Evidence is self-attested by the contributor; the verifier does not prove that tests ran.

## Review and sign-off

- Independent review: passed by independent
- Human signoff: passed by human

## Verification gates

`agent-contrib verify` reported:

- `execution_ready`: yes
- `evidence_valid`: yes
- `upstream_submission_ready`: yes
- `fork_completion_ready`: no

No pending gates were reported.

## Overlap scan

Live open-PR scan complete: yes. Overlapping PRs: 0.

## AI assistance disclosure

Prepared with Agent Contrib CLI 0.3.0. Contract SHA-256: `b673ee6e2a4f664683592e7b545978d2a23ce5359cad86df1c280b1b6249f05c`.
Host-reported assistant: Claude Opus 5.5.

<!-- If the repository has a pull request template, merge these sections into it. Rendering is not publication authority. -->
