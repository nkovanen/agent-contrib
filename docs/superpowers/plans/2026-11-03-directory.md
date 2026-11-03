# Tipjar Directory Implementation Plan

Goal: deliver the approved, delegated static directory scope.
Architecture: separate a pure validation/model module from DOM rendering; no build.
Tech stack: browser HTML/CSS/JavaScript, Node built-in assertions for pure tests.
Spec: ../specs/2026-11-03-directory-design.md

Constraints: no runtime dependencies, network reads, mutation, or implied authority.
Review focus: malformed identities; incomplete welcome; oversized imports; hostile
HTML; strict manifest download. Test each in model tests and browser QA.

- [x] Write failing model regressions in tests/web/model.test.cjs and expose them
  through unittest (skip only when Node unavailable).
- [x] Implement web/model.js: bounded snapshot validation, safe source identities,
  filtering, schema 0.1 editor serialization; run model tests to green.
- [x] Build web/index.html, style.css and app.js with demo data, import, filters,
  detail dialog and manifest download. Exercise actual DOM flows in Paseo.
- [x] Document local serving and manual Pages hosting, add sdist assets and
  packaging assertion, run full unittest and installed-package checks.
- [x] Merge latest origin/main without rebase, reverify and commit source only.

Controller supplies independent review and CI; no subagents/push/PR/deployment here.

Validation: Node model regressions and Python-parser interoperability pass.
Desktop and 390px mobile views inspected in Paseo; local hostile/invalid file
imports, search empty state, editor errors and download action exercised.
Paseo CSP blocks browser_evaluate and later paint/action timeouts limited final
keyboard/drop/copy checks. Controller owns independent review and CI.

Terra follow-up: explicit Unicode whitespace parity, preserved editor text,
malformed nullable-jar rejection and compatible input memory cap are covered by
Node, Python-parser and repeatable browser DOM regressions. Finder exporter is
explicitly marked pending preview until separately reviewed integration. Browser
copy/download OS boundaries are inspected via spies; native keyboard/focus remains
limited by the host, not claimed passing. Fullsuite:1127 tests; package checks pass.
