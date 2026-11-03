# Tipjar Directory Implementation Plan

Goal: deliver the approved, delegated static directory scope.
Architecture: separate a pure validation/model module from DOM rendering; no build.
Tech stack: browser HTML/CSS/JavaScript, Node built-in assertions for pure tests.
Spec: ../specs/2026-11-03-directory-design.md

Constraints: no runtime dependencies, network reads, mutation, or implied authority.
Review focus: malformed identities; incomplete welcome; oversized imports; hostile
HTML; strict manifest download. Test each in model tests and browser QA.

- [ ] Write failing model regressions in tests/web/model.test.cjs and expose them
  through unittest (skip only when Node unavailable).
- [ ] Implement web/model.js: bounded snapshot validation, safe source identities,
  filtering, schema 0.1 editor serialization; run model tests to green.
- [ ] Build web/index.html, style.css and app.js with demo data, import, filters,
  detail dialog and manifest download. Exercise actual DOM flows in Paseo.
- [ ] Document local serving and manual Pages hosting, add sdist assets and
  packaging assertion, run full unittest and installed-package checks.
- [ ] Merge latest origin/main without rebase, reverify and commit source only.

Controller supplies independent review and CI; no subagents/push/PR/deployment here.
