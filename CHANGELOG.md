# Changelog

CLI/library versions follow semantic versioning. Task/evidence schema versions
are independent and require an explicit compatibility decision.

## 0.2.0 — 2026-11-01

First standalone release, extracted from the reviewed LightCraft experiment.

- Read-only GitHub issue discovery, policy/instruction inspection and open-PR
  overlap detection through `gh`.
- One-hop parent issue discovery for forks with Issues disabled; distinct
  requested, source and proposed-target identities with provenance.
- Draft task contracts and passive evidence verification using schema `0.1`.
- Separate repository approval, execution authorization and publication mandate.
- A portable Skill that loads the workflow from the installed CLI.
- Standalone Python packaging, GitHub installation and CI; no LightCraft or Rust
  build dependency. The 65 protocol regressions are retained.

The standalone release preserves the POC's protocol behavior. Approval delegates
to accounts with label permissions; evidence is self-attested; topical overlap
and existing own drafts can block verification. No automatic submission,
execution harness, actor-specific approval or PyPI publication is included.

### Earlier experiment

The 0.1.0 prototype and development of 0.2.0 occurred in
[LightCraft PR #1](https://github.com/nkovanen/lightcraft/pull/1).
Historical pilot logs remain there rather than in this distribution.
