# Security

## Reporting

Please report suspected vulnerabilities privately through
[GitHub security advisories](https://github.com/nkovanen/agent-contrib/security/advisories/new).
Include the affected version, a minimal reproduction and the expected trust
boundary. Do not include credentials or private repository contents. Response
times are not guaranteed for this experimental project. The current release
line is 0.2.x; older prototypes have no separate security maintenance commitment.

## Boundaries

- GitHub issue text, repository instructions, policies and task/evidence files
  are untrusted input. They cannot override the host agent's permissions.
- GitHub calls use fixed `gh api --hostname github.com --method GET` arguments.
  The CLI has no GitHub write, push, PR creation or merge command. It uses the
  caller's `gh` authentication; it does not reduce that token's permissions.
  Prefer credentials appropriate for read-only public-repository discovery.
- Validation argv is data. `verify` never executes it. The host agent must inspect
  a checkout and its build scripts before running tests with its own tools.
- Source approval, execution authority and publication authority are separate.
  Policy v0 delegates approval to all accounts permitted to apply labels. There
  is no actor-specific maintainer authentication.
- Evidence is self-attested consistency data, not signed proof. Independent
  review and real human authorization remain necessary outside the verifier.
- Local Git reads disable hooks, fsmonitor, replacement objects and external
  diff/textconv execution paths. Artifact reads require bounded regular files
  inside the checkout. This is not a sandbox for a hostile checkout or Git binary;
  use isolation and keep credentials away from code you execute.
- Unknown schema versions, malformed or incomplete API results, unsupported
  submodules and unresolved overlap fail closed. No automatic updates occur.

CI uses read-only permissions and does not expose production secrets or execute
fork workflows through `pull_request_target`. Release installation runs Python
build tooling: review the source and pin a trusted release or immutable commit.
See the [installed workflow](agent_contribute/instructions.md) for exact limits.
