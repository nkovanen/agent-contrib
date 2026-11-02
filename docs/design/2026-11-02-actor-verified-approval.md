# Actor-verified approval labels: design proposal

- Date: 2026-11-02
- Status: proposal, not implemented. Issue [#9](https://github.com/nkovanen/agent-contrib/issues/9).
- Base: `d9285be` (unreleased v0.3.0 candidate). Depends on #3's credential role check.

## Summary

Policy 0.1 (`label_authority: repository-label-permission`) approves an issue when
it carries a configured label, whoever applied it. Anyone GitHub lets apply labels
counts, triagers included. Maintainers who want approval to mean "a maintainer
applied this label" cannot opt in today.

Proposal: a new policy version, 0.2, with `label_authority: "maintainer-role"`.
An issue is `approved` only if a configured label is present and the latest
`labeled` event for that label meets four conditions:

1. A personal user applied it, not a bot or a GitHub App.
2. It was applied after the policy file last changed.
3. That user's current role in the source repository is in `approver_roles`.
4. All reads needed to decide this completed.

In every other case the issue is a `candidate`, never `approved`. Policy 0.1, a
missing policy and unknown policy versions behave exactly as today.

## Invariants

1. Approval is still source approval only. It never authorizes execution or
   publication, and the 0.2 task route still needs a human/host mandate.
2. Missing, partial or unverifiable data never yields `approved`.
3. Policy 0.1 decisions, read sequence and output are unchanged; the existing
   discover and legacy goldens must still pass byte for byte.
4. The CLI stays read-only and never executes repository content.

## Current behaviour

`core.approval_for(snapshot, issue)` is a pure function of the default-branch
snapshot and the issue's current labels. A policy file is valid only with exactly
the keys `schema_version` (compared with the task `VERSION` constant `'0.1'`),
`agent_approved_labels` (1 to 30 distinct non-generic names) and
`label_authority: "repository-label-permission"`. An unreadable or invalid policy
is `unknown`. A valid policy with a matching label is `approved`. No label actor
is read. The 0.2 task route binds the policy by hash (`policy_sha256`) and blocks
on `unknown`, but does not need `approved`.

## Policy file 0.2

```json
{
  "schema_version": "0.2",
  "agent_approved_labels": ["agent-approved"],
  "label_authority": "maintainer-role",
  "approver_roles": ["admin", "maintain"]
}
```

- Exactly these four keys; any other key, value or type makes the policy invalid,
  so its status is `unknown`.
- `agent_approved_labels`: same rules as 0.1.
- `approver_roles`: a non-empty list of distinct values from `admin` and
  `maintain`. Only these two values are supported. `write`, `triage`, `read`,
  custom role names and anything else make the policy invalid, not merely
  ignored. `["admin"]` is the "owners and admins only" profile.
- The policy version is a new constant, separate from the task schema
  `VERSION`. A policy whose `schema_version` is not `0.1` or `0.2` stays
  `unknown`. A 0.1 policy must still say `repository-label-permission`, and a
  0.2 policy must say `maintainer-role`; crossing them is invalid.

## Decision procedure (policy 0.2)

Run this only when the policy is valid and at least one configured label is on
the issue. Otherwise the result is the same as 0.1: `candidate` with the
existing reason.

1. **Policy change time.** Read
   `repos/{source}/commits?path=.agent-contrib.json&sha={snapshot.commit}&per_page=1`
   once per snapshot. Record the committer date of the first item as
   `policy_changed_at`. An empty list, a malformed item or a read failure makes
   every label unverifiable.
2. **Label events.** Paginate `repos/{source}/issues/{n}/events` with the existing
   `core.paginate` (100 per page, 40-page cap, repeated IDs make the read
   incomplete). Sort by `(created_at, id)`. Do not rely on response order.
3. **Transfer cut-off.** If any event has `event: "transferred"`, drop every event
   at or before the latest such event (unverified, see [Slice 0](#slices)).
4. **Per configured label that is present** (exact name match, as in 0.1):
   1. Take the latest event whose `event` is `labeled` or `unlabeled` and whose
      `label.name` equals the label exactly. If it is not `labeled`, or there is
      none, the label is unverified. This covers removed-and-re-added labels and
      renamed labels.
   2. That event must be after `policy_changed_at`.
   3. The event must have `actor.type == "User"`, a positive `actor.id`, and a
      null or absent `performed_via_github_app`. A `null` actor (deleted account)
      fails.
   4. Resolve the actor's current login with `user/{actor.id}`, which must return
      the same ID, `type: "User"` and a login matching #3's `_LOGIN`. Event logins
      can be stale after a rename, so they are reported but never used for
      lookups.
   5. Check the role with the same helper #3 uses: read
      `repos/{source}/collaborators/{login}/permission` and require
      `user.id == actor.id`, `user.type == "User"`, an ASCII login and a
      `role_name` in `approver_roles`. A custom, missing or unknown role fails.
5. The issue is `approved` if at least one present label passes every step.
   Otherwise it is `candidate`. With any failure it is still `candidate`.

`approval_for` stays pure. A new reader in `inspect_from_snapshot` gathers the
events and role facts and passes them in, so the decision is unit-testable
without a client. #3's role check moves into one helper,
`authorization.collaborator_role(repository, login, user_id, client)`, which both
`authorization.check` and approval call. The role logic is not duplicated.

### Fail-closed rules

| Condition | Status | Completeness |
| --- | --- | --- |
| Policy unreadable, invalid or of unknown version | `unknown` (as today) | snapshot error (as today) |
| Valid 0.2 policy, no configured label on the issue | `candidate` | unaffected |
| Events or policy-history read failed, incomplete or malformed | `candidate`, reason names the read | `approval.errors` lists it; issue completeness unaffected |
| Latest event for the label is `unlabeled`, missing or renamed away | `candidate` | unaffected |
| Event not after `policy_changed_at` | `candidate` | unaffected |
| Actor bot, app, null, non-User, or `performed_via_github_app` set | `candidate` | unaffected |
| User lookup or permission read failed or returned 403/404 | `candidate` | `approval.errors` lists it |
| Role not in `approver_roles` (including demotion since labelling) | `candidate` | unaffected |
| Identity mismatch (ID, type, non-ASCII login) | `candidate` | `approval.errors` lists it |

**Why `candidate`, not `unknown`, for actor failures.** `unknown` means the
repository's *policy* could not be determined, and the 0.2 task route blocks on
it. An unverifiable *label* is exactly an issue without verified approval, which
is `candidate`. That denies approval to every route that needs it (0.1
`upstream-contribution`). It changes nothing for routes that never needed
approval (0.1 `fork-experiment`, the 0.2 candidate route). Approval reads do not
mark the overlap/instruction snapshot incomplete, because nothing they could
return would make another gate more permissive.

## Output and provenance

`approval` gains `approvers` (one entry per present configured label) and
`errors`. Each entry has `label`, `event_id`, `labeled_at`, `event_actor_login`,
`actor_id`, `current_login`, `role_name`, `role_read_at` and `verified`
(boolean). There are also top-level `policy_changed_at` and `reads`
(`events_pages`, `complete`). Logins and labels are remote text and go through
`safe_text`.

Output schemas are closed (`additionalProperties: false`), so this is a shape
change. Per `docs/cli.md`, that bumps the output schema version to `2`, together
with the CLI minor version and the changelog. Policy 0.1 and missing-policy
outputs keep every current value, but the schemas still change version
because the object gains optional fields.

`verify` already reruns inspection, so it rereads the events, user and role on
every run. A demotion or removal between `prepare` and `verify` turns `approved`
into `candidate`, and 0.1 upstream readiness then fails. A 0.2 task's
`policy_sha256` already binds the policy content.

## Threat model

| Threat | Handling |
| --- | --- |
| A triager (or anyone with `write`) applies the label | `role_name` is not in `approver_roles`: `candidate`. |
| A bot or GitHub App applies it, including a maintainer's automation | `actor.type` is not `User`, or `performed_via_github_app` is set: `candidate`. Maintainers apply the label by hand (web UI or `gh`; Slice 0 confirms `gh` sets no app). |
| A maintainer applies it, then a triager removes and re-adds it | The latest `labeled` event belongs to the triager: `candidate`. |
| A collaborator is demoted after labelling | Only the current role is checked, at every `inspect` and `verify`: `candidate`. |
| A triager labels, and is later promoted to maintainer | **Accepted:** the label then approves. GitHub exposes no historical role outside organization audit logs (admin-only). A maintainer can re-label to be sure. Documented for maintainers. |
| Actor renamed | Lookups use the numeric ID; the stale event login is only reported. |
| Actor account deleted | A `null` actor or a 404 on `user/{id}`: `candidate`. |
| Label applied before the policy existed or changed | The event must be after `policy_changed_at`. Maintainers re-label after any policy change. |
| Commit date backdated to revive old labels | Only someone who can push to the default branch can do it. Revived labels still need a current approver-role actor. Accepted and documented. |
| Label renamed after being applied | No event carries the current name: `candidate`. Re-label after renaming. |
| Issue transferred from another repository | Events up to the latest `transferred` event are ignored, and roles are read in the current source repository. 0.2 tasks also bind the issue ID and URL. |
| Event list truncated (over 40 pages) or moves during pagination | `paginate` reports it incomplete: `candidate`. |
| Issue body rewritten after a maintainer labelled it | Not addressed (same as 0.1): GitHub's REST events do not expose body edits. The contract review and human mandate remain the guard. Documented. |
| Forged events or roles in a hostile `gh` / proxy | Out of scope: same trust as every other GitHub read. |

## Compatibility

- Policy 0.1 and a missing policy: same decisions, same reads in the same
  order, same values. The discover and legacy goldens must pass unchanged. No
  events, user or permission reads happen unless a valid 0.2 policy is present
  *and* a configured label is on the issue.
- Unknown policy versions and malformed 0.2 policies are `unknown` (blocking),
  as today.
- Task, evidence and host-context schemas are unchanged. A 0.2 task prepared
  under policy 0.1 that meets a policy 0.2 file at `verify` sees a policy hash
  change, which already blocks with "Source policy state/content changed".
- Output schema version goes from 1 to 2 (see above).
- The `audit` command validates 0.2 policies, and its `--print-policy` template
  stays 0.1 unless a flag selects 0.2 (Slice 3).

## API cost

Policy 0.1 and a missing policy: 0 extra reads.

Policy 0.2, per repository snapshot: 1 read (policy history). Per issue that
carries a configured label: the events pages (usually 1). Per distinct actor:
2 reads (`user/{id}` and permission), cached within one CLI run. A `discover`
over N labelled issues with A distinct actors costs about `1 + N + 2A` extra
reads. Issues without a configured label cost nothing. `--report-budget`
already measures this.

## Slices

0. **Live read-only probe (human-run, no code).** Confirm these behaviours,
   which this design assumes but has not checked:
   1. Which credentials can read `collaborators/{login}/permission`: maintainer,
      write, triage, read, and a non-collaborator; classic and fine-grained
      tokens; what a non-collaborator gets (403, 404).
   2. That issue events keep `labeled` events indefinitely, carry the label name
      at event time after a rename, and include `transferred`.
   3. That `user/{id}` returns the current login and 404 for deleted accounts.
   4. That labels applied in the web UI and with `gh` have no
      `performed_via_github_app`.
   5. That org owners and enterprise-managed users report `role_name: admin`.

   Record the results here. If non-collaborator tokens cannot read the role,
   policy 0.2 resolves to `candidate` for every contributor without push
   access. That must be stated in `docs/maintainers.md` before anyone adopts
   it: the policy then serves maintainers' own agents, not outside
   contributors.
1. **Policy parsing and pure decision.** Policy 0.2 validation, the
   `collaborator_role` extraction (with `authorization.check` goldens
   unchanged), and the pure decision over supplied events and role facts. There
   are no new reads yet: a valid 0.2 policy with a present label returns
   `candidate` with "actor verification not yet available".
2. **Reads and output.** The policy-history, events, user and permission reads
   with per-run caching. Approval provenance in inspect, discover and verify
   output; output schema 2; and `--report-budget` counts.
3. **Maintainer docs and audit.** `docs/maintainers.md` (adoption, re-label after
   policy changes or renames, the promotion and body-edit limits, the Slice 0
   credential limits); `audit` validation and an opt-in 0.2 template; SECURITY.md.

## Test plan

- Policy parsing. 0.2 is accepted only with the four exact keys. Each of these
  is `unknown`: unknown keys, empty or duplicate `approver_roles`, `write`,
  `triage`, custom roles, the 0.1 authority string in a 0.2 policy and the
  reverse, and versions `0.3`, `0` and `"0.2 "`.
- Pure decision, one fixture per row of the fail-closed and threat tables:
  - re-added by a triager;
  - `unlabeled` last;
  - renamed label;
  - event at or before `policy_changed_at`;
  - Bot actor, `[bot]` login with type User, `performed_via_github_app` set,
    null actor;
  - event login differing from the current login (rename); 404 user;
  - role `write`, `triage`, custom or missing; `admin` with `approver_roles:
    ["maintain"]`;
  - permission user ID or type mismatch; non-ASCII and confusable logins;
  - transferred cut-off; multiple labels where only one verifies;
  - event ordering independent of response order.
- Reads. Each of these is `candidate` with `approval.errors`, and issue
  completeness is unaffected: incomplete events (40-page cap, repeated ID,
  malformed page); policy-history empty or failing; user or permission 403/404;
  malformed responses through the existing remote-shape fuzz pattern.
- The per-run actor cache makes exactly 2 reads per distinct actor across
  `discover`.
- Compatibility. The existing discover and legacy goldens are unchanged (values
  and read sequences). With policy 0.1 or none, no `events`, `user/{id}` or
  `permission` endpoint is called.
- Integration. A 0.1 `upstream-contribution` contract becomes not ready when the
  approver is demoted between `prepare` and `verify`. The 0.2 candidate route is
  unaffected by an unverifiable label but blocked by a malformed 0.2 policy.
- The output-schema hook validates every new output. Mutants (role set, latest
  event, `unlabeled`, policy time, app check, ID match, cache) must be killed.

## Not proposed (YAGNI)

- Historical role at labelling time. There is no API outside admin-only
  organization audit logs.
- Signed or quorum approval, per-label role lists, team-based approvers, and
  `write` or `triage` as approver roles.
- GraphQL `userContentEdits` to detect body edits after labelling.
- Any write to GitHub, label management, or migration of 0.1 policies.
