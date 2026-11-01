## Summary

Refs acme/photos#12

**Objective:** Reject out-of-bounds thumbnails

**Scope:** allowed src/\*\*; prohibited .github/\*\*

## Acceptance criteria

- bounds: Malformed dimensions return an error (no evidence supplied)

## Validation

- unit (tests): python3 -m unittest; no result supplied

Evidence is self-attested by the contributor; the verifier does not prove that tests ran.

## Review and sign-off

- Independent review: pending (not supplied)
- Human signoff: pending (not supplied)

## Verification gates

`agent-contrib verify` reported:

- `execution_ready`: yes
- `evidence_valid`: no
- `upstream_submission_ready`: no
- `fork_completion_ready`: no

Pending gates:
- evidence: No execution evidence, independent review or human signoff provided

## Overlap scan

Live open-PR scan complete: yes. Overlapping PRs: 0.

## AI assistance disclosure

Prepared with Agent Contrib CLI 0.3.0. Contract SHA-256: `b673ee6e2a4f664683592e7b545978d2a23ce5359cad86df1c280b1b6249f05c`.

<!-- If the repository has a pull request template, merge these sections into it. Rendering is not publication authority. -->
