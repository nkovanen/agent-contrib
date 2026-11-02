# Development status

The published release is **v0.2.0**. This branch is the unreleased **v0.3.0
candidate**. Per-issue status (shipped, partial, planned) lives in the
[product map](product-map.md); this page records acceptance evidence and the
release gate. The Skill stays portable and all GitHub operations in the CLI
remain read-only.

For mandate issuance (#23), issuer requirements are specified; no native issuer
ships. Partial reports (#5, #6, #8, #16, #17) expose uncertainty; they do not
authorize work or turn observed CI success into evidence that the required
contract checks ran.

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
