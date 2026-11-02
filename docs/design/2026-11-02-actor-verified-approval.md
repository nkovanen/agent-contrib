# Actor-verified approval labels: design proposal

- Date: 2026-11-02
- Status: proposal, **revision 2**, not implemented. Issue [#9](https://github.com/nkovanen/agent-contrib/issues/9).
  Revision 1 (`7c1b2e9`) was blocked by hostile review R9; see
  [Review resolution](#review-resolution).
- Base: `d0bdf3d` (unreleased v0.3.0 candidate).

## Summary

Revision 1 proposed policy 0.2 for `.agent-contrib.json`: a label would approve
only if its latest `labeled` event came from an account whose current role is
`admin` or `maintain`. Review R9 and live read-only probes showed this cannot
work for the audience that needs it:

- **Only credentials with push access can read a role.**
  `collaborators/{login}/permission` returns 403 "Must have push access to view
  collaborator permission" to anyone else (R9-04, observed live). An outside
  contributor's agent could therefore never see `approved` under policy 0.2.
  That is the same result as the repository having no policy.
- **The accounts that can read roles do not need label approval.** Maintainers
  and their own agents already have the stronger schema 0.2 route: a human/host
  mandate bound to the contract and to their own credential.
- **Public data cannot replace the role read.** `labeled` events carry no
  `author_association` (live: the keys are `actor, commit_id, commit_url,
  created_at, event, id, intent, label, node_id, performed_via_github_app,
  url`). Their `label` is only `{name, color}`, with no durable label ID. Public
  org membership says nothing about repository roles.
- **Two promises in revision 1 were unsound:**
  - It treated the policy file's committer time as its activation time (R9-02).
  - It bound approval to a label by name, although names can be swapped
    (R9-03).

**Decision: no new approval policy version.** Policy 0.1 stays exactly as it
is. #9 ships as:

1. **Honest documentation** of what label approval means and who can verify
   what (docs only).
2. **Optionally, for maintainers only:** a report-only `audit --label-actors`
   that a credential with push access can run. It lists who applied each
   current approval label and that account's current role, so a maintainer can
   find and remove labels applied by triagers, bots or apps. It never changes
   any approval decision, task or gate.

If a future change requires outside contributors to see verified approval, it
needs evidence an outsider can read and bind to a durable label identity. None
exists in the REST GET surface this CLI uses.

## Invariants

1. Source approval never authorizes execution or publication.
2. Missing, partial or unverifiable data never yields `approved`, or a clean
   audit result.
3. Policy 0.1 decisions, read sequence, output values and task contents stay
   unchanged. No task, evidence or host-context schema changes.
4. The CLI stays read-only and uses fixed `GET` endpoints only (no GraphQL POST).

## Who can verify what

| Party | Reads labels and events | Reads an actor's repository role | Has a stronger authority path |
| --- | --- | --- | --- |
| Outside contributor (no push access) | yes (public issue) | **no**: 403 on the permission endpoint (live) | no |
| Triager, write collaborator | yes | yes (push access); write was observed, triage is not yet confirmed | not by default |
| Maintainer, admin, or their agent | yes | yes | yes: the schema 0.2 mandate route |
| GitHub App or bot | depends on its permissions | depends on its permissions | not used by this project |

Any approval rule that needs the role read helps only rows that already have,
or do not need, authority. That is why revision 2 drops the policy change.

## Part 1: documentation (ships first)

The existing policy text (`docs/maintainers.md`, the approval policy section)
gains these statements:

- Label approval means "an account GitHub lets apply this label applied it".
  The CLI does not and cannot verify that account's role for outside
  contributors.
- To make approval maintainer-only, restrict who can apply labels, for example
  by not granting triage to accounts you would not let approve agent work. Use
  a dedicated label name, and re-check the label after renaming labels.
- For your own agents, prefer the schema 0.2 mandate route over label approval.
- `audit --label-actors`, if shipped, is the maintainer-side check.

## Part 2 (optional): `audit --label-actors`, maintainer-only report

### Behaviour

- **Opt-in:** `audit owner/repo --label-actors`. Default `audit` output and its
  read sequence are unchanged.
- **Policy gate:** runs only when policy 0.1 is valid. Otherwise it reports
  `label_actors.status: unavailable` with the reason, and makes no extra reads.
- **Credential check:** the credential must pass #3's check:
  `authorization.collaborator_role` extracted from `authorization.check`, giving
  a personal user with `role_name` admin or maintain. Otherwise it reports
  `unavailable: requires an admin or maintain credential` and makes no event
  reads. This states the R9-04 audience limit in the output itself.
- **Per open issue carrying a configured approval label** (from the same issue
  list `audit` already reads):
  1. Paginate `repos/{source}/issues/{n}/events`, as `core.paginate` does.
  2. Validate every event the decision uses: positive `id`, RFC3339
     `created_at`, `event` kind, and `actor` and `label.name` shapes. A
     malformed event that is newer than the candidate event makes the item
     `unverifiable`; it is never skipped in favour of an older one (R9 review).
  3. Order by `(created_at, id)` and apply the cut-off at the latest
     `transferred` event.
  4. Take the latest `labeled`/`unlabeled` event whose `label.name` equals the
     configured name.
  5. Classify the item as one of:
     - `maintainer`: personal user, explicit `performed_via_github_app: null`,
       and current role admin or maintain.
     - `below_maintainer`: any other role, including `write`, `triage`, custom
       roles, and no access.
     - `automation`: a Bot actor, or `performed_via_github_app` that is
       non-null or absent.
     - `unverifiable`: a null actor, a user ID that does not resolve, a failed
       read, an incomplete page, a malformed newer event, or a latest event
       that is not `labeled`.
- **Lookups:** roles are read with `user/{id}` (exact ID match), then
  `collaborators/{login}/permission` (exact `role_name`, never legacy
  `permission`). Results are cached per **source repository and actor ID** for
  one invocation only, with the read time kept. A failed lookup is cached too,
  so one actor does not produce repeated denied reads.
- **Output:** each item has issue number, label name, `event_id`, `labeled_at`,
  `actor_id`, event login, current login, `role_name`, `role_read_at` and
  `class`. A summary gives counts by class and `complete`.
  - The audit exits 1 when any item is not `maintainer` or the report is
    incomplete. This is a maintainer signal, like today's audit gaps.
  - Wording: "applied by an account that currently holds role X". Never "applied
    while a maintainer": GitHub keeps no historical roles, so a promoted triager
    looks like a maintainer.
- **Stated limits, printed in the report:**
  - Labels are matched by name. A rename, or two labels swapping names, can
    attribute an event to the wrong label (R9-03); GitHub's REST events expose
    no label ID.
  - The reads are not an atomic snapshot: events added or roles changed after
    they were read are not seen.
  - Event retention is observed, not guaranteed.
  - A person's PAT used by automation looks like that person.

### Why this is safe and small

- No approval, task, contract, verify or prepare behaviour changes. That
  resolves R9-01 by construction: nothing new is copied into tasks.
- No activation-time logic at all (R9-02).
- Name-based matching is acceptable only because the output is an advisory for
  the maintainer who controls the labels. It never grants anything, and its
  limit is printed with every result (R9-03).
- It runs only where the role read works (R9-04).

### Output schema

`audit` output gains an optional `label_actors` object. The output schemas are
closed, so this is a shape change: following `docs/cli.md`, the output schema
version becomes `2`, with a CLI minor-version bump and a changelog entry. If
this slice is not worth that, ship Part 1 alone.

### API cost

Only with `--label-actors` and a valid policy:
- 2 reads for the credential check;
- per labelled open issue, its event pages (`P_i`, at most 40);
- per distinct repository/actor pair, 2 reads (`A`).

Total `2 + sum(P_i) + 2A`. Default `audit` makes no extra reads.

## Test plan (Part 2)

- Default `audit` output and read sequence are unchanged (existing goldens).
- With an invalid or missing policy, or without an admin/maintain credential:
  `unavailable` and no event reads (assert the call log).
- Classes:
  - `maintainer`;
  - `below_maintainer` for each of `write`, `triage` and a custom role;
  - `automation` for a Bot actor, non-null `performed_via_github_app`, and an
    absent field;
  - `unverifiable` for a null actor, an unresolved user ID, a 403/404 role read,
    a 40-page cap, a repeated ID, a malformed newer event (older valid event
    present), and a latest `unlabeled`.
- Same-second events ordered by ID, and the transfer cut-off with absent or
  malformed transfer evidence.
- The cache is keyed by repository and actor: the same actor is admin in one
  repository and write in another within one invocation.
- Exit status is 1 for any non-`maintainer` item or incomplete report, and the
  limit text is present.
- The output-schema hook validates every new output. Mutants on the class
  rules, the ordering, the newer-malformed rule and the cache key must be
  killed.

## Slices

1. Documentation (Part 1). No code.
2. Extract `authorization.collaborator_role` from `authorization.check`, with
   its goldens unchanged. This is a precondition for Part 2.
3. `audit --label-actors`, output schema 2, tests.

Slice 0 from revision 1 (the live probe matrix) shrinks to what Part 2 relies
on. Confirm before Slice 3:
- what a triage credential gets from the permission endpoint;
- what a known GitHub App user-token label event carries in
  `performed_via_github_app`.

## Review resolution

| Finding | Revision 2 |
| --- | --- |
| R9-01 (High): extended approval object breaks both closed task schemas via `prepare` | Resolved by removal: approval objects and tasks do not change. New data lives only in `audit` output. |
| R9-02 (High): committer time is not policy activation time | Resolved by removal: no policy-history read and no time-based promise. No approval epoch is introduced. |
| R9-03 (High, suspected): label names cannot establish identity across renames or swaps | Not solvable on the REST GET surface: live events show `label: {name, color}` with no ID. Revision 2 never bases approval on it; the advisory audit prints the limit. |
| R9-04 (Medium, confirmed live): outside contributors get 403 on the permission endpoint | Central to revision 2. Public alternatives were checked and found insufficient: no `author_association` on labeled events, and org membership is not a repository role. Policy 0.2 is dropped, and the audience limit is documented and enforced (`unavailable` without an admin/maintain credential). |
| Role semantics | Exact `role_name` only; custom roles are rejected; enterprise-managed users are not assumed admin. |
| Promotion wording | "currently holds role X", never "applied while a maintainer". |
| Cache scope | Per source repository and actor ID, invocation-local, with read time. Failed lookups are cached. |
| Pagination and atomicity | Every used event field is validated; a malformed newer event makes the item unverifiable. The non-atomic observation window is stated. |
| Transfer | `(created_at, id)` ordering for the cut-off; tests for absent or malformed transfer evidence. |
| Ghost and renamed users | Numeric-ID lookup with exact match. The `ghost` login is never special-cased; a 404 means unverifiable, not deleted. |
| Apps | A non-null *or absent* `performed_via_github_app` counts as automation. A person's PAT used by automation is indistinguishable, and that is stated. |
| Multiple labels and failures | Each item is classified independently. A shared read failure (credential, issue events) makes every affected item `unverifiable`. |
| API cost | `2 + sum(P_i) + 2A` per repository/actor; no repeated denied reads. |
| YAGNI | No policy version, no epoch, no GraphQL, no audit-log dependency. Part 2 is optional. |
