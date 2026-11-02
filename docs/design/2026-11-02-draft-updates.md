# Updating a recognized draft after review (#21): design proposal

- Date: 2026-11-02
- Status: proposal, **revision 2**. Review round 1 (DU-01 to DU-05) is resolved in [Review resolution](#review-resolution). Design only; no code in this change.
- Base: `rsi/v03-land` at `e454848` (unreleased v0.3.0 candidate: task and evidence schemas 0.1 and 0.2, host-context 0.1 and 0.2).
- Issue: [#21](https://github.com/nkovanen/agent-contrib/issues/21), product-map key F3. Depends on #3. Uses #20 (`feedback`).

## Summary

After a schema 0.2 draft PR is recognized, the human may authorize one **update round** with a separately issued host-context record, `draft_update`. The record is bound to the contract, the original mandate, the recognized PR and the head the round starts from (`from_head`, `F`).

A round authorizes local fixes on the reviewed `head_ref`, and **exactly one** host push. That push must be a fast-forward from `F` to the evidence head `E`, which the verifier reported as `push_update`.

After the push, `verify` recognizes the updated draft only when all of these hold:

- the live head `P` equals `E` and strictly advances `F`;
- the history from the creation head is fast-forward only;
- the PR timeline has no rewrite, close, reopen or ready events;
- the evidence base is the reviewed source commit, and the round contains no merge commits;
- fresh technical evidence and an independent review exist for exactly `P`, both newer than the round.

Old evidence, reviews and sign-offs never carry over. Completion still requires a separate final sign-off for exactly `P`, issued after the host observed that head's publication.

Task schemas 0.1 and 0.2, schema 0.1 routes and host-context 0.1 are unchanged. The CLI writes nothing to GitHub. With no `draft_update` record, every result is byte-identical to today.

## What the code does today

- **Claim head.** `pr_identity.check_publication` requires the publication claim `head_sha` to equal the validated evidence head (`pr_identity.py:189-190`).
- **Live head.** It requires the live head to equal it too (`:202-203`).
- **Creation time.** `created_at` must lie in the mandate interval (`:204-205`).
- **History.** The exact head/base history must contain exactly one PR (`:162-176`, `:191-192`).
- **Implementation gate** (`lifecycle.py:228-252`). It is a conjunction: no historical errors, a current mandate (`current_errors`), the `implement` action, **no duplicates at all** (the own PR counts), and an empty exact-head history. After publication it can never pass.
- **Own-PR exemption.** `without_own` applies only to post-publication blockers (`:258-263`).
- **`next_action`.** `resolve_blockers`, `implement`, `create_draft` or `none` (`:295-300`; output enum in `schemas/output/1/verify.schema.json`).
- **Evidence base.** `core.check_evidence` accepts any `base_commit` that GitHub shows in current default-branch history and that descends from `task.source.commit` (`core.py:878-910`). Scope compares changed **paths** from `base_commit` to HEAD (`:913-916`). It does not require base equality and does not inspect merge commits.
- **Final sign-off.** It binds `git_head`, the review hash, the contract and the mandate. It must follow PR creation and the review (`lifecycle.py:86-107`).
- **Issuer requirements.** They keep a status per `mandate_sha256` (`active`, `revoked`, `superseded`) and make draft creation and sign-off consumption single-use (`docs/host-authorization.md`, "Status and action-time checks", "What repeats").
- **Workflow.** "No updates, ancestor-only exemption, force-push adoption or reopening are supported" (`instructions.md:356-367`).

## Decisions

| ID | Decision | Rationale |
| --- | --- | --- |
| D1 | An optional `draft_update` section in host-context **0.2**, before the v0.3.0 release | 0.2 is unreleased and already the precedent for an optional section (`overlap_dispositions`). The task schema is untouched. A mandate action would need a task schema change, and a fresh mandate would stop recognizing the PR (the claim binds the mandate hash; creation must lie in the mandate interval). |
| D2 | **One host-consumed push per record** (maintainer decision) | This keeps a coherent state machine: every push corresponds to exactly one passing `push_update` gate (DU-01). Another round needs a new record from the newly recognized head. |
| D3 | **No exact `to_head` human approval** | See below. |

**Why `to_head` approval is not needed.** The round is a prospective, scoped delegation, exactly like the mandate that authorized creation without approving the created head. The published content is covered by gates that bind the exact SHA:

1. fresh technical evidence at `E`;
2. an independent code and compliance review at `E`;
3. final human sign-off for exactly `E`, issued after the host observed `E`'s publication.

Nothing completes without (3). The approval view must state the delegation plainly: the scope, the PR and ref, one push, and the window. It is not consent to exact content. If a repository needs per-diff consent before publication, that is a different product requirement, out of scope here.

## The `draft_update` record

It is optional and human/host-issued. The worker relays it unchanged and never writes it.

| Field | Binding |
| --- | --- |
| `id`, `nonce`, `issued_at`, `expires_at` | As for `final_signoff`. The interval must be positive, at most 24 h and not in the future. It is evaluated after all blocking reads. |
| `contract_sha256`, `mandate_sha256` | The exact contract, and the unchanged original mandate. |
| `credential_actor_id` | Must equal the mandate actor and the live `GET user` ID. |
| `repository_id`, `pr_number`, `pr_id` | Must equal the publication claim and the live PR. |
| `from_head` (`F`) | A 40-hex SHA: the live head the human saw when opening the round. |
| `event` | `kind`, `reference`, `text_sha256` and `binding_sha256` (`authorization.event_hash`). |

**Distinct identities.** `id`, `nonce` and `event.reference` must differ pairwise across every human record present: the mandate, `final_signoff`, `overlap_dispositions` and `draft_update`.

**Claims and the mandate.** The publication claim keeps the creation head `A` as untrusted association data, unchanged. The mandate bytes and hash never change. A host context carries at most one `draft_update`: the current round.

## State machine

Notation:
- `A`: the claim's creation head.
- `F`: the record's `from_head`.
- `P`: the live PR head.
- `E`: the evidence head (local `HEAD` at the reviewed `head_ref`).

Comparisons use GitHub `compare/{x}...{y}` on full SHAs, interpreting only `status`. They never use the truncated commit or file arrays.

| State | Required facts | `draft_update.status` / `next_action` | Stage exit 0 |
| --- | --- | --- | --- |
| No record | as today | (absent) / as today | as today |
| **Round open** | `U` and `I(F)` below, record current | `implement` / `implement_update` | implementation |
| **Ready to push** | round open, plus `T(E)`, plus `E` strictly descends from `F` locally, plus no merge commits in `F..E` | `push` / `push_update` | draft |
| **Updated draft recognized** | `U`, `I(P)` with `P == E`, `P != F`, `compare F...P == ahead`, `T(E)`, no merge commits in `F..E` | `recognized` / `none`; `publication.verified: true` | draft; completion with a valid sign-off |
| **Blocked** | anything else: `P` is neither `F` nor `E`, `P == F == E`, `diverged` or `behind`, a forbidden event, a wrong PR, stale evidence, an expired record before the push, an invalid record | `blocked` or `invalid` / `resolve_blockers` | none |

**Unchanged draft is not an update.** `P == F == E` with old evidence is never "recognized" under a record (DU-03). Without a record, the unchanged draft at `A` is recognized exactly as today. For the post-round audit, see Host lifecycle.

### `U`: authority and source facts (shared)

All of these are required. Only the original mandate's expiry is waived.

1. The contract is schema-valid and reviewed. The live source refresh is complete: issue, instructions, policy and default branch are unchanged, and the reviewed commit is still in default-branch history. Approval policy is resolved, the issue is not excluded, and prerequisites are satisfied. That is, every `historical_errors` entry that `lifecycle.verify` collects today is absent.
2. The original mandate is `historical_valid`, and its actions include `create_draft`. Its expiry (`authority['current_errors']`) is **not** a blocker for update states. Nothing else is waived.
3. The `draft_update` record is schema-valid, and every binding, the event hash and the distinct identities hold.
4. Currency: `issued_at <= now < expires_at` is required for round open and ready to push, judged after every blocking read. After the push, the record may have expired.
5. Overlaps: `without_own(live_duplicates + prepared_duplicates, own)` is empty, where `own` is the PR identified in `I`. Every unrelated or prepared overlap still blocks. `overlap_dispositions` stays inert and never waives anything.
6. The verify result is void if the host's status for the mandate or the record is `revoked` or `superseded`. This is a host rule; the stateless CLI cannot see it.

### `I(X)`: identity of the own draft at head `X`, with no evidence needed

1. The publication claim's schema holds and it matches the binding, as today, except that its `head_sha` is `A` and need not equal `X`.
2. The exact head/base history has exactly one PR, the claimed one. List and detail agree. It is open, draft and unmerged, authored by the bound actor, with an unchanged route and URL, created inside the mandate interval.
3. Live `P == X`. Then `compare A...X` is `identical` or `ahead`, and `compare A...F` is `identical` or `ahead`.
4. Timeline: the paginated `repos/{repo}/issues/{n}/timeline` has no `head_ref_force_pushed`, `head_ref_deleted`, `head_ref_restored`, `closed`, `reopened`, `merged`, `ready_for_review` or `convert_to_draft` event.
5. After the timeline and compare reads, a second detail read must show the same head SHA, PR ID, state and draft flag, so there is no mid-read race.

### `T(E)`: fresh technical evidence at `E`

1. `core.check_evidence` passes unchanged, with `git_head == E`, a clean worktree, the reviewed `head_ref`, scope, and validations after `E`'s committer time.
2. **Update-only base rule (DU-04):** `evidence.base_commit == task.source.commit` exactly. A newer authenticated base, which is allowed for creation, blocks an update. If creation used a newer base, the update needs a re-prepared contract.
3. **Update-only history rule:** `rev-list --merges F..E` is empty, through the hardened `core.git_read`. A merge of the newer default branch, or of anything else, blocks even when its net paths are allowed. Non-merge commits are judged by the existing path scope and the independent review.
4. Every validation's `started_at` is at or after `draft_update.issued_at`.
5. The independent review is valid at `E`: bound to `E` and the contract, by a reviewer other than the implementer, and after the validations (existing rule).

The legacy no-record path keeps today's base and scope behaviour unchanged.

## Host lifecycle (normative issuer requirements for `draft_update`)

These extend "Status and action-time checks" in `docs/host-authorization.md`. They ship with slice 1, before any authority-bearing slice (DU-02).

1. **Status per `draft_update_sha256`:** `active`, `consumed`, `revoked` or `superseded`. Expiry ends permission for new actions only.
2. **Current round.** At most one round per (contract, mandate, PR) is `active`. Before issuing a new round, the host marks the previous round `superseded`: it must be `consumed` and its updated head observed as recognized. Otherwise the host `revoke`s it. Revoking also stops the worker's session for that round.
3. **Issuing a round.**
   - The host renders the approval view from its own copy of the contract, plus the live PR, plus `F` (read from the live PR at issuance), plus the reviewed feedback it chooses to show.
   - It states the delegation: scope, the PR and ref, **one push**, and the window.
   - It retains the view, the approval text and the record hash outside worker-writable roots.
4. **Consuming the push (single use).** The host pushes only when all of these hold:
   - `verify --stage draft` reports `push_update` for exact head `E` under an `active`, unexpired round;
   - the push is exactly `E` to `refs/heads/{head_ref}` as a fast-forward (never `--force`);
   - the round is still `active` at push time.

   It then marks the round `consumed`, and retains `F`, `E` and the push time.
5. **Recognition and completion** accept a round that is `consumed`, or `superseded` after consumption, and never one that is `revoked`. The `verify` result must echo the round's hash. A result that echoes a `revoked` round, or an `active` round whose push was never consumed, is void for recognition.
6. **Final sign-off ordering.** The host issues final sign-off for head `E` only after all of these:
   - it observed a `verify` result with `draft_update.status: recognized` for exactly `E` under the latest consumed round;
   - the independent review at `E` is valid;
   - its own retained push time for `E`.

   The CLI additionally checks `final_signoff.issued_at > draft_update.issued_at`, plus the existing review ordering. The push time itself is host data.
7. **Audit.** The live PR head and `GET repos/{repo}/pulls/{n}/commits` are compared with the retained creation head and every consumed round's `F` and `E`. A head that no consumed round explains voids acceptance.

## Interplay

- **`feedback` (#20).** This is the loop:
  1. `feedback --expected-head A` (or the latest recognized head) reports change requests.
  2. The host shows them with the live PR and issues a round with `F` equal to that head.
  3. The worker fixes, validates and obtains an independent review at `E`.
  4. `verify --stage draft` gives `push_update`, and the host consumes the round.
  5. `verify` reports `recognized`.
  6. `feedback --expected-head E` starts the next round, under a new record.

  Review text stays untrusted and never widens scope; a scope change needs a new contract, and so a new PR.
- **Final sign-off.** It binds `git_head = E` and the review hash at `E`. A sign-off for `A` or `F` is stale automatically. Completion requires the recognized state at exactly the signed head.
- **Overlap dispositions (#7).** Inert as today. The new section must not activate any waiver.
- **`pr-body`.** Unchanged.

## Replay and staleness

| Attack or race | Outcome |
| --- | --- |
| A second push under the same record (`P = E`, new `E2`) | The pre-push gate needs `P == F`, so no `push_update`. A host that pushes anyway violates single use. Recognition at `E2` cannot distinguish this statelessly, so the host audit (rule 7) voids it. |
| Reusing a record for another PR, contract or mandate | Bound IDs and hashes differ: invalid. |
| An old genuine round `U1` supplied after `U2` (rollback) | The CLI accepts the bindings, but the host status `superseded` or `revoked` voids the result (rule 5). Only the current round's hash is valid. |
| A no-op round (`P == F == E`, old evidence) | Blocked: an update needs `P != F`, and the validations must post-date the round. |
| Someone else pushes to the branch | `P` is neither `F` nor `E`, or the evidence doesn't match `P`: blocked. |
| A force push, ref delete or restore, close or reopen, ready-for-review | A forbidden timeline event blocks, even when the final head descends. |
| A retarget of the base and back | Only the current base identity is checked (`base_ref_changed` is on the issue-events endpoint, not the timeline). Historical retargeting is prevented and audited by the host; it does not change the tested tree. |
| A merge of the newer base, including one with only allowed paths | Blocked by the update-only base rule and the no-merges rule. |
| A false creation head `A` in the claim | It must be an ancestor of `F` and `P`. Rewriting is caught by the timeline. The host retains the true `A`. |
| A head that moves during the reads | The second detail read must match, otherwise blocked. Snapshots are not atomic, so re-verify. |

## Read bounds and parsing

- **Timeline.** It is read with the existing bounded pagination: 100 per page, at most 40 pages, 8 MiB per response, bounded retries. It fails closed on the limit, errors or a repeated identity.
  - Typed identity: an event with a positive integer `id` uses `id`.
  - A `committed` item uses `commit:` plus its 40-hex `sha`.
  - Any other item without either is malformed, and the read is incomplete.
  - Every item must be an object with a string `event`.
  - Event types not on the denylist are allowed, because GitHub adds types.

  The denylist plus host prevention is the stated guarantee. A successful listing is an observation, not an authenticated event log.
- **Compare.** Only full SHAs, in the stated order; only `status` is interpreted. It is never cached: the content cache's allowlist excludes it.
- **Expiry.** The record and final sign-off are evaluated after every blocking read. The host re-checks the round's status at push time.

## Compatibility

- **Unchanged:** task and evidence schemas 0.1 and 0.2, host-context 0.1, schema 0.1 routes, and every result without a `draft_update` record. Golden JSON and GET traces are pinned for the no-record path.
- **Host-context 0.2:** one optional section, before release. Unknown sections and versions still fail closed. Mandate bytes and hash are independent of the wrapper.
- **Output schema `verify` (version 1, unreleased):** an optional `draft_update` report (`status`, `sha256`, `from_head`, `errors`) and two `next_action` values, `implement_update` and `push_update`.
- **Workflow:** the "No updates …" paragraph is replaced by the round loop and the host rules.

## Adversarial test plan

All tests use fixtures: fake PR, compare, timeline and detail responses, and temporary Git repositories. **State-table cases**, each asserting the state, `next_action` and stage exits:

1. `A = F = P = E` (old evidence) under a record: blocked, never recognized.
2. `A < F = P = E`: blocked.
3. `A = F = P`, `E > F`, with fresh evidence: push.
4. `P = E > F`, fresh: recognized.
5. `P = E = F`: blocked.
6. `P > E`, and `P` unrelated: blocked.

**Authority:**

7. The original mandate expired with a current round: open and push pass. With a non-current round: blocked before the push, recognized after it.
8. Revoked and superseded rounds: documented as void by host status. The CLI-visible bindings are tested.
9. Record schema: missing or extra fields, a bad SHA, an interval over 24 h or in the future, an id, nonce or reference reused against each other record, a 0.1 context with the section, a bad event hash.
10. Wrong binding: another contract, mandate, actor, repository, PR number or PR ID.

**Overlaps:**

11. The own PR alone passes. The own PR plus an unrelated PR blocks. A prepared duplicate blocks. An `overlap_dispositions` section present (valid, invalid or expired) changes nothing.

**Evidence:**

12. Evidence at `A` or `F`. A review bound to an older head. A review before the validations. A validation before `issued_at`. A validation before `E`'s commit.
13. `base_commit` newer than `source.commit` (authenticated) blocks only on the update path. A merge commit in `F..E` touching only allowed paths blocks. The no-record path is unchanged.

**History:**

14. Each forbidden timeline event alone. Pagination at the limit. A repeated identity. A malformed item. A `committed` item without a SHA.
15. Compare `diverged` or `behind`, for both `A...F` and `F...P`; compare errors; a malformed status.
16. A head moving between the first and second detail reads.

**Sign-off:**

17. A sign-off for `A` after the update; a sign-off issued before the round; a valid sign-off at the recognized `E` completes.

**Other:**

18. Unchanged prerequisites, policy, instructions and route each still block in every update state. Missing evidence blocks push and recognition but not round open.
19. Without a record: byte-identical JSON and GET traces versus the parent.
20. Mutants, each to be killed: drop `P != F`; accept `identical` for `F...P`; drop the merge rule; drop base equality; waive all `current_errors` instead of mandate expiry only; drop own-only overlap filtering; drop the second detail read; drop the sign-off ordering rule.

## Slices

1. **Inert schema plus host requirements.** The host-context 0.2 `draft_update` section, record checks (bindings, event, interval, pairwise identities), and `status: not_evaluated`. The output schema key. The **issuer requirements above** go into `docs/host-authorization.md`. No gate change.
2. **Recognition after a push.** The `I`, `T`, compare, timeline, second-read, base and merge rules. `publication.verified` at the updated head. Sign-off ordering.
3. **Pre-push readiness.** `implement_update` and `push_update` with the complete conjunctions, and the stage gates and text summaries.
4. **Workflow.** The `instructions.md` loop, and `authorization-request --draft-update` (an unsigned envelope, `null` human fields, an approval view rendered by the host). An acceptance trial with a real host-issued round.

## Review resolution

| Finding | Verified | Resolution |
| --- | --- | --- |
| DU-01: multiple pushes conflict with the pre-push gate | Confirmed. With `F = A`, a second push has `P = B != F`, so `push_update` fails, yet revision 1's recognition row accepted `P = E = C`. | D2 changed to **one host-consumed push per record**. The only authorized transition is `F` to `E` after `push_update`. A further round needs a new record from the recognized head. The replay table states the stateless limit and the host audit that voids an unauthorized second push. |
| DU-02: no host lifecycle for the record | Confirmed. `host-authorization.md` tracks status per mandate only. A rollback to an older genuine round was undetectable, and sign-off could precede the push. | Normative issuer rules: status per record hash (active, consumed, revoked, superseded), one current round, supersession only after consumption and recognition, single-use push, void results for revoked or superseded rounds, sign-off after observed recognition of `E`, and an audit of every consumed round. These ship in slice 1, before authority-bearing code. The CLI adds `final_signoff.issued_at > draft_update.issued_at`. |
| DU-03: a no-op was accepted as an update | Confirmed. `A = F = P = E` with old evidence passed every revision 1 predicate. | Recognition now needs `P == E`, `P != F` and `compare F...P == ahead`. `identical` is allowed only for `A...F`, and only in the open and push states. Validations must start after the round's `issued_at`. Cases 1–6 pin the boundary. |
| DU-04: the claimed base and merge rejection was not real | Confirmed against `core.check_evidence` (`core.py:878-916`): a newer authenticated base is accepted, and scope is path-only. | Update-only rules: `evidence.base_commit == task.source.commit` exactly, and no merge commits in `F..E` (hardened `rev-list --merges`). The claim that the path scope rejects such merges is removed. Legacy behaviour is unchanged. Test 13 covers a merge with only allowed paths. |
| DU-05: incomplete update-readiness conditions | Confirmed. The implementation gate (`lifecycle.py:228-252`) also needs a current mandate, `implement`, and no duplicates (the own PR counts). | Complete conjunctions `U`, `I(X)` and `T(E)`. Only the original mandate's expiry is waived. Historical validity and `create_draft` are required, and the record must be current. Own-PR-only exemption via `without_own`; every unrelated or prepared overlap still blocks; dispositions stay inert. Identity at `F` needs no evidence. Tests 7, 11 and 18 cover these. |
| Attack surface: event coverage, retargeting, timeline identities, compare, races | Accepted. | `ready_for_review` and `merged` were added to the denylist. Retargeting is narrowed to current base identity plus host prevention. Typed timeline identities and minimum shapes. Compare uses status only and is never cached. A second detail read after the added reads. Expiry is judged after blocking reads and again at push time. |
| Attack surface: `to_head` semantics | Accepted. | D3: no exact `to_head` approval. The approval view states the delegation (scope, PR and ref, one push, window). The exact published content is bound by evidence, independent review and final sign-off at `E`, the sign-off issued after the host observed `E`'s publication. This is not advertised as exact-content consent. |
