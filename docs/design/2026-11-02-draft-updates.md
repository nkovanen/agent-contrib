# Updating a recognized draft after review (#21): design proposal

- Date: 2026-11-02
- Status: proposal, **revision 4**. Review rounds 1 to 3 (DU-01 to DU-08) are resolved in [Review resolution](#review-resolution); DU-09 (wording) is fixed below. **Slices 1 (inert schema and host requirements) and 2 (recognition after a push) are implemented**; slices 3 and 4 are not.
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

Comparisons use GitHub `compare/{x}...{y}` on full SHAs. A `status` counts only when the base echo, merge base and counters agree with it (`core.compare_relation`, FR1-01). They never use the truncated commit or file arrays.

| State | Required facts | `draft_update.status` / `next_action` | Stage exit 0 |
| --- | --- | --- | --- |
| No record | as today | (absent) / as today | as today |
| **Round open** | `U` and `I(F)` below, record current. Evidence is not consulted. | `implement` / `implement_update` | implementation |
| **Ready to push** | round open, plus `T(E)`, plus `E` strictly descends from `F` locally, plus no merge commits in `F..E` | `push` / `push_update`, with `candidate_head: E` | draft |
| **Updated draft recognized** | `U`, `I(P)` with `P == E`, `P != F`, `compare F...P == ahead`, `T(E)`, no merge commits in `F..E` | `recognized` / `none`; `publication.verified: true` | draft; completion with a valid sign-off |
| **Blocked** | anything else: `P` is neither `F` nor `E` (when evidence is supplied), `diverged` or `behind`, a forbidden event, a wrong PR, stale evidence at a pushed head, an expired record before the push, an invalid record | `blocked` or `invalid` / `resolve_blockers` | none |

**Unchanged draft is not an update.** With `P == F` and either no evidence or evidence at `E == F` (including old evidence), the evidence is ignored. Such a call reports round open, or blocked if `U` or `I(F)` fails. It never reports push, updated recognition or completion (DU-03). Push needs `E > F` with `T(E)`, as in the table. Without a record, the unchanged draft at `A` is recognized exactly as today.

**`A...F` may be `identical`** in every state, including updated recognition after the first round (`A == F`). Only `F...P` must be `ahead` for recognition.

### `U`: authority and source facts (shared)

All of these are required. Only the original mandate's expiry is waived.

1. The contract is schema-valid and reviewed. The live source refresh is complete: issue, instructions, policy and default branch are unchanged, and the reviewed commit is still in default-branch history. Approval policy is resolved, the issue is not excluded, and prerequisites are satisfied. That is, every `historical_errors` entry that `lifecycle.verify` collects today is absent.
2. The original mandate is `historical_valid`, and its actions include `create_draft`. Its expiry (`authority['current_errors']`) is **not** a blocker for update states. Nothing else is waived.
3. The `draft_update` record is schema-valid, and every binding, the event hash and the distinct identities hold.
4. Currency: `issued_at <= now < expires_at` is required for round open and ready to push, judged after every blocking read. After the push, the record may have expired.
5. Overlaps: `without_own(all_duplicates, own)` is empty, where `own` is the PR identified in `I` and `all_duplicates` is the same list every schema 0.2 gate uses today: live and prepared overlaps, minus only the topical overlaps that an active, valid `overlap_dispositions` section waives under its own rules (#7), plus anything that section observed. Every other unrelated or prepared overlap still blocks. `draft_update` itself never waives an overlap or extends a disposition.
6. **Operative round only (DU-02).** The result echoes the record's hash. It is operative only if that hash equals the host's **current-round pointer** for (contract, mandate, PR) and the mandate is not `revoked` or `superseded`. Otherwise it is void for every gate: round open, push, recognition and completion. This is a host rule; the stateless CLI cannot see the pointer.

### `I(X)`: identity of the own draft at head `X`, with no evidence needed

1. The publication claim's schema holds and it matches the binding, as today, except that its `head_sha` is `A` and need not equal `X`.
2. The exact head/base history has exactly one PR, the claimed one. List and detail agree. It is open, draft and unmerged, authored by the bound actor, with an unchanged route and URL, created inside the mandate interval and not in the future (FR1-03).
3. Live `P == X`. Then `compare A...X` is `identical` or `ahead`, and `compare A...F` is `identical` or `ahead`.
4. Timeline: the paginated `repos/{repo}/issues/{n}/timeline` has no `head_ref_force_pushed`, `head_ref_deleted`, `head_ref_restored`, `closed`, `reopened`, `merged`, `ready_for_review` or `convert_to_draft` event.
5. **Final re-read (DU-07).** After the timeline and compare reads, the PR detail is read again and parsed with the full publication shape validation (`pr_identity._pr_facts(detail=True)`). The resulting **complete normalized facts** must equal those from the first read:
   - both repository names and IDs, the head and base refs, and the URL;
   - the PR number and ID, the author, the head SHA, the creation and merge facts, and the state and draft flag.

   The final raw detail must also still satisfy the semantic predicates: `state == "open"`, `draft is True`, `merged is False` (the raw boolean, which `_pr_facts` validates but does not project) and `merged_at is None`, exactly as `check_publication` checks them today (DU-07).

   The route is then rechecked against the original binding (`_route_matches`). A base retarget, head move or malformed detail visible to the final read blocks. Snapshots are still not atomic; a change after the final read needs re-verification.

### `T(E)`: fresh technical evidence at `E`

1. `core.check_evidence` passes unchanged, with `git_head == E`, a clean worktree, the reviewed `head_ref`, scope, and validations after `E`'s committer time.
2. **Update-only base rule (DU-04):** `evidence.base_commit == task.source.commit` exactly. A newer authenticated base, which is allowed for creation, blocks an update. The rule is about the current update evidence only: the CLI neither retains nor checks which base the creation evidence used. If creation used a newer base, that evidence cannot be reused; new evidence and an independent review covering `task.source.commit..E` satisfy the rule. Re-preparation is needed only if the update cannot be validated against the reviewed source commit (DUI-02).
3. **Update-only history rule:** `rev-list --merges --max-count=1 F..E` is empty, through the hardened `core.git_read`. It stops at the first merge, and a traversal error fails closed. A merge of the newer default branch, or of anything else, blocks even when its net paths are allowed. Non-merge commits are judged by the existing path scope and the independent review.
4. Every validation's `started_at` is at or after `draft_update.issued_at`.
5. The independent review is valid at `E`: bound to `E` and the contract, by a reviewer other than the implementer, and after the validations (existing rule).

The legacy no-record path keeps today's base and scope behaviour unchanged.

### The candidate head in the output (DU-08)

The `draft_update` report carries `candidate_head`: the exact 40-hex `E` that passed `T(E)` in that invocation. It is the `git_head` of the evidence that was validated, equal to the local `HEAD` captured once by exact lookup (`core.current_head`). It is non-null exactly when `status` is `push` or `recognized`.

The record binds only `F`, so `candidate_head` is the only output fact identifying what was validated. The host reserves and pushes **this** SHA:
- It takes it from a `verify` result produced by a run the host itself started and captured, never from a worker-relayed copy.
- It never re-derives the candidate by rereading the evidence file or the checkout `HEAD`, both of which the worker controls.

The no-record output stays byte-identical.

## Host lifecycle (normative issuer requirements for `draft_update`)

These extend "Status and action-time checks" in `docs/host-authorization.md`. They ship with slice 1, before any authority-bearing slice (DU-02).

1. **Status per `draft_update_sha256`:** `active`, `reserved(F→E)`, `consumed`, `revoked` or `superseded`. Expiry ends permission for new actions only.
2. **Current-round pointer.** Per (contract, mandate, PR) the host keeps exactly one pointer to the current round.
   - Only the record it points to is operative for any gate (`U.6`).
   - Opening a new round first marks the previous round `superseded` and moves the pointer. A `superseded` record is **archival**: kept for audit, operative for nothing. Completion of the previous head, including with an already-issued final sign-off, is no longer possible: the host marks any unconsumed sign-off for it void.
   - Revoking an unconsumed current round stops the worker's session for it. The host may then explicitly restore the pointer to the previous round, as a recorded host decision. That round's status moves from `superseded` back to `consumed`. Final sign-offs voided when it was superseded stay void; completion needs a new, later sign-off event.
   - A worker-supplied record never moves the pointer.
3. **Issuing a round.**
   - The host renders the approval view from its own copy of the contract, plus the live PR, plus `F` (read from the live PR at issuance), plus the reviewed feedback it chooses to show.
   - It states the delegation: scope, the PR and ref, **one push**, and the window.
   - It retains the view, the approval text and the record hash outside worker-writable roots.
4. **Consuming the push: an exclusive, durable reservation (DU-06).** A round's status moves `active` → `reserved(F→E)` → `consumed`, or `active` → `reserved(F→E)` → `revoked`.
   1. Under an exclusive host lock keyed to the round, protected against concurrent consumers and concurrent revoke or replacement, the host checks that the round is current, `active` and unexpired. It checks that a host-captured `verify --stage draft` result reports `push_update` with `candidate_head`, and takes `E` from that field. It then durably records `reserved(F→E)` before any remote operation. A second consumer finds the round `reserved` and stops.
   2. Immediately before submitting, the host re-proves the frozen pair `F → E` in the repository it pushes from, with the hardened reads: `E` exists, `merge-base --is-ancestor F E`, `E != F`, and no merge commits in `F..E`. It then submits one conditional update: `git push --force-with-lease=refs/heads/{head_ref}:{F} {remote} {E}:refs/heads/{head_ref}`.

      The lease only conditions the update on the remote tip being exactly `F`. It does not itself enforce fast-forward: Git's lease can override that restriction. That is why the separate ancestry proof of the same frozen `F` and `E` is required. A bare `--force` is never used.

      Because the proven transition is a fast-forward, GitHub is **expected** not to record a `head_ref_force_pushed` event; the acceptance trial observes this. The timeline denylist stays: if such an event appears, recognition blocks.
   3. Every actual submission, including a retry of the same reserved operation, needs all of these at that moment:
      - the round's original deadline has not passed;
      - the round is still the current-round pointer and not revoked;
      - the push prerequisites are refreshed.

      An attempt that failed before the deadline, with `P == F`, never becomes a successful submission after it. Reconciliation may still recognize an earlier attempt that did publish `E`, as history.
   4. Reconciliation, still under the lock:
      - **Success:** a live read shows `P == E`; mark the round `consumed` and retain `F`, `E` and the push time.
      - **Clear failure, live `P == F`:** the reservation stays `reserved(F→E)`. The host may retry only this exact operation, subject to step 3.
      - **Uncertain outcome** (timeout, lost response, crash after the remote update): fail closed and stay `reserved`. Reconcile by reading the live head: `P == E` means consumed; `P == F` means not pushed. Anything else revokes the round and goes to audit.

      A reservation never returns to `active`, and it never admits another candidate head.
5. **Recognition and completion** accept only the **current** round, and only once it is `consumed` with its retained `E` equal to the live head. A result echoing any other hash is void: `superseded`, `revoked`, or a current round still `active` or `reserved`.
6. **Final sign-off ordering.** The host issues final sign-off for head `E` only after all of these:
   - it observed a `verify` result with `draft_update.status: recognized` for exactly `E`, echoing the **current** round's hash, after that round was `consumed`;
   - the independent review at `E` is valid;
   - its own retained push time for `E`.

   The CLI additionally checks `final_signoff.issued_at > draft_update.issued_at`, plus the existing review ordering. The push time itself is host data.
7. **Audit.** The host retains the exact chain: the creation head `A`, then each consumed round's `F → E`. Each `F` must equal the previous tip, and the live head must equal the last retained `E`. A head the chain does not explain voids acceptance. The PR commit list is not used: it is capped at 250 commits and is not an authority chain.

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
- **Overlap dispositions (#7).** Active on the baseline: a valid, current `overlap_dispositions` section waives only the topical overlaps it binds, under its own rules, and every gate (including the update path) uses the resulting overlap list. The `draft_update` section adds no waiver, never widens a disposition, and does not change how dispositions are evaluated.
- **`pr-body`.** Unchanged.

## Replay and staleness

| Attack or race | Outcome |
| --- | --- |
| A second push under the same record (`P = E`, new `E2`) | The pre-push gate needs `P == F`, so no `push_update`. The host's reservation is already `consumed` and refuses. An out-of-band push fails the audit chain (rule 7). |
| Two consumers race with `E1 < E2` from the same `F` | The exclusive reservation admits one. The other finds `reserved` or `consumed`. The lease (`F`) makes a late second push fail even outside the lock. |
| The worker changes the evidence file or checkout `HEAD` to `E2` after a `push_update` for `E1` | The host reserves and pushes `candidate_head` (`E1`) from its own captured result and never rereads worker input. An unrelated `E2`, which a bare lease on `F` would accept, is never submitted. |
| A retry after the round's deadline | Refused (rule 4, step 3). A publication of `E` that already happened before the deadline is reconciled as history. |
| A crash or lost response after the remote update | The round stays `reserved(F→E)` and is reconciled from the live head. It never reopens for another candidate. |
| Reusing a record for another PR, contract or mandate | Bound IDs and hashes differ: invalid. |
| An old genuine round `U1` supplied after `U2` (rollback), with `U2` active, reserved or consumed | The CLI accepts `U1`'s bindings, but the echoed hash is not the current-round pointer, so the result is void for every gate (`U.6`, rule 5). `U1`'s unconsumed sign-off was voided when `U2` opened (rule 2). |
| A no-op round (`P == F == E`, old evidence) | At most round open. Never push, recognition or completion: an update needs `P != F`, and the validations must post-date the round. |
| Someone else pushes to the branch | `P` is neither `F` nor `E`, or the evidence doesn't match `P`: blocked. |
| A force push, ref delete or restore, close or reopen, ready-for-review | A forbidden timeline event blocks, even when the final head descends. |
| A retarget of the base and back | Only the current base identity is checked (`base_ref_changed` is on the issue-events endpoint, not the timeline). Historical retargeting is prevented and audited by the host; it does not change the tested tree. |
| A merge of the newer base, including one with only allowed paths | Blocked by the update-only base rule and the no-merges rule. |
| A false creation head `A` in the claim | It must be an ancestor of `F` and `P`. Rewriting is caught by the timeline. The host retains the true `A`. |
| A head move or base retarget during the reads | The full normalized final re-read and route recheck block it (`I.5`). Snapshots are not atomic, so re-verify after the final read. |

## Read bounds and parsing

- **Timeline.** It is read with the existing bounded pagination: 100 per page, at most 40 pages, 8 MiB per response, bounded retries. It fails closed on the limit, errors or a repeated identity.
  - Typed identity: an event with a positive integer `id` uses `id`.
  - A `committed` item uses `commit:` plus its 40-hex `sha`.
  - Any other item without either is malformed, and the read is incomplete.
  - Every item must be an object with a string `event`.
  - Event types not on the denylist are allowed, because GitHub adds types.

  The denylist plus host prevention is the stated guarantee. A successful listing is an observation, not an authenticated event log.
- **Compare.** Only full SHAs, in the stated order; only a `status` consistent with its commits and counters is interpreted. Requirement for any response cache, present or future: compare, PR, timeline and other mutable or authority-bearing reads are never served from a cache. The opt-in content cache in #27 serves only blob-verified file contents.
- **Coexistence.** Whole-context schema validation and the pairwise event-identity rules apply to every present section. An `overlap_dispositions` section is evaluated exactly as without a `draft_update` section; its waivers apply to the update path only through the shared overlap list (`U.5`).
- **Expiry.** The record and final sign-off are evaluated after every blocking read. The host re-checks the round's status at push time.

## Compatibility

- **Unchanged:** task and evidence schemas 0.1 and 0.2, host-context 0.1, schema 0.1 routes, and every result without a `draft_update` record. Golden JSON and GET traces are pinned for the no-record path.
- **Host-context 0.2:** one optional section, before release. Unknown sections and versions still fail closed. Mandate bytes and hash are independent of the wrapper.
- **Output schema `verify` (version 1, unreleased):** an optional `draft_update` report (`status`, `sha256`, `from_head`, `candidate_head`, `errors`) and two `next_action` values, `implement_update` and `push_update`.
- **Workflow:** the "No updates …" paragraph is replaced by the round loop and the host rules.

## Adversarial test plan

All tests use fixtures: fake PR, compare, timeline and detail responses, and temporary Git repositories. **State-table cases**, each asserting the state, `next_action` and stage exits:

1. `A = F = P = E` (old evidence) under a record: round open at most; never push, recognized or completion.
2. `A < F = P = E`: as 1.
3. `A = F = P`, `E > F`, with fresh evidence: push.
4. `P = E > F`, fresh: recognized.
5. `P = E = F` with a non-current record: blocked.
6. `P > E`, and `P` unrelated: blocked.

**Authority:**

7. The original mandate expired with a current round: open and push pass. With a non-current round: blocked before the push, recognized after it.
8. Revoked and superseded rounds: documented as void by host status. The CLI-visible bindings are tested.
9. Record schema: missing or extra fields, a bad SHA, an interval over 24 h or in the future, an id, nonce or reference reused against each other record, a 0.1 context with the section, a bad event hash.
10. Wrong binding: another contract, mandate, actor, repository, PR number or PR ID.

**Overlaps:**

11. The own PR alone passes. The own PR plus an unrelated PR blocks. A prepared duplicate blocks. An `overlap_dispositions` section affects the update path exactly as it affects the other gates: a valid, current waiver of a topical overlap removes only that overlap; an invalid or expired one waives nothing; a direct reference is never waived.

**Evidence:**

12. Evidence at `A` or `F`. A review bound to an older head. A review before the validations. A validation before `issued_at`. A validation before `E`'s commit.
13. `base_commit` newer than `source.commit` (authenticated) blocks only on the update path. A merge commit in `F..E` touching only allowed paths blocks. The no-record path is unchanged.

**History:**

14. Each forbidden timeline event alone. Pagination at the limit. A repeated identity. A malformed item. A `committed` item without a SHA.
15. Compare `diverged` or `behind`, for both `A...F` and `F...P`; compare errors; a malformed status.
16. Between the first and final detail reads: a head move; a base retarget to another branch with every other fact equal; a malformed final detail; an inconsistent final detail with `merged: true` while open, draft and `merged_at: null`. Each blocks.

**Sign-off:**

17. A sign-off for `A` after the update; a sign-off issued before the round; a valid sign-off at the recognized `E` completes.

**Host issuer** (reviewed when an issuer ships; documented in slice 1):

21. `U1` consumed, then `U2` active: supplying `U1` with its unexpired sign-off is void. The same after `U2` is consumed.
22. Parallel consumers with `E1 < E2`: exactly one push.
23. A crash after the remote update, and a lost response: the round stays `reserved` and reconciles from the live head, with no second candidate.
24. A lease failure when the remote tip is not `F`.
25. A `push_update` for `E1`, then the evidence file and local `HEAD` change to `E2` (a fast-forward of `E1`, and separately an unrelated commit) before consumption: the host pushes `E1` or nothing, never `E2`. A `push` or `recognized` report always has a non-null `candidate_head` equal to the validated evidence `git_head`; every other status has it null.
26. A reserved retry after the deadline is refused. An attempt that published before the deadline reconciles.

**Other:**

18. Unchanged prerequisites, policy, instructions and route each still block in every update state. Missing evidence blocks push and recognition but not round open.
19. Without a record: byte-identical JSON and GET traces versus the parent.
20. Mutants, each to be killed: drop `P != F`; accept `identical` for `F...P`; drop the merge rule; drop base equality; waive all `current_errors` instead of mandate expiry only; drop own-only overlap filtering; reduce the final re-read to head, ID, state and draft; drop the raw `merged is False` check; drop the route recheck; omit or misreport `candidate_head`; drop the sign-off ordering rule.

## Slices

1. **Inert schema plus host requirements.** The host-context 0.2 `draft_update` section, record checks (bindings, event, interval, pairwise identities), and `status: not_evaluated`. The output schema key. The **issuer requirements above** go into `docs/host-authorization.md`. No gate change.
2. **Recognition after a push.** The `I`, `T`, compare, timeline, full final re-read, base and merge rules. `publication.verified` at the updated head. Sign-off ordering. This slice is authority-bearing. It ships only together with the slice 1 host obligations (pointer, reservation, audit), and successful historical recognition grants no new publication capability.
3. **Pre-push readiness.** `implement_update` and `push_update` with the complete conjunctions, and the stage gates and text summaries.
4. **Workflow.** The `instructions.md` loop, and `authorization-request --draft-update` (an unsigned envelope, `null` human fields, an approval view rendered by the host). An acceptance trial with a real host-issued round.

## Review resolution

| Finding | Verified | Resolution |
| --- | --- | --- |
| DU-01: multiple pushes conflict with the pre-push gate | Confirmed. With `F = A`, a second push has `P = B != F`, so `push_update` fails, yet revision 1's recognition row accepted `P = E = C`. | D2 changed to **one host-consumed push per record**. The only authorized transition is `F` to `E` after `push_update`. A further round needs a new record from the recognized head. The replay table states the stateless limit and the host audit that voids an unauthorized second push. |
| DU-02: no host lifecycle for the record | Confirmed. `host-authorization.md` tracks status per mandate only. A rollback to an older genuine round was undetectable, and sign-off could precede the push. | Normative issuer rules: status per record hash (active, consumed, revoked, superseded), one current round, supersession only after consumption and recognition, single-use push, void results for revoked or superseded rounds, sign-off after observed recognition of `E`, and an audit of every consumed round. These ship in slice 1, before authority-bearing code. The CLI adds `final_signoff.issued_at > draft_update.issued_at`. |
| DU-03: a no-op was accepted as an update | Confirmed. `A = F = P = E` with old evidence passed every revision 1 predicate. | Recognition now needs `P == E`, `P != F` and `compare F...P == ahead`. `identical` is allowed only for `A...F` (in every state, including the first updated recognition where `A == F`), never for `F...P` in recognition. Validations must start after the round's `issued_at`. Cases 1–6 pin the boundary. |
| DU-04: the claimed base and merge rejection was not real | Confirmed against `core.check_evidence` (`core.py:878-916`): a newer authenticated base is accepted, and scope is path-only. | Update-only rules: `evidence.base_commit == task.source.commit` exactly, and no merge commits in `F..E` (hardened `rev-list --merges`). The claim that the path scope rejects such merges is removed. Legacy behaviour is unchanged. Test 13 covers a merge with only allowed paths. |
| DU-05: incomplete update-readiness conditions | Confirmed. The implementation gate (`lifecycle.py:228-252`) also needs a current mandate, `implement`, and no duplicates (the own PR counts). | Complete conjunctions `U`, `I(X)` and `T(E)`. Only the original mandate's expiry is waived. Historical validity and `create_draft` are required, and the record must be current. Own-PR-only exemption via `without_own`; every unrelated or prepared overlap still blocks; dispositions stay inert (superseded: they are active, see DU-09). Identity at `F` needs no evidence. Tests 7, 11 and 18 cover these. |
| Attack surface: event coverage, retargeting, timeline identities, compare, races | Accepted. | `ready_for_review` and `merged` were added to the denylist. Retargeting is narrowed to current base identity plus host prevention. Typed timeline identities and minimum shapes. Compare uses status only and is never cached. A second detail read after the added reads. Expiry is judged after blocking reads and again at push time. |
| Attack surface: `to_head` semantics | Accepted. | D3: no exact `to_head` approval. The approval view states the delegation (scope, PR and ref, one push, window). The exact published content is bound by evidence, independent review and final sign-off at `E`, the sign-off issued after the host observed `E`'s publication. This is not advertised as exact-content consent. |

### Round 2

| Finding | Verified | Resolution |
| --- | --- | --- |
| DU-02 (narrowed): `superseded` was both accepted and void | Confirmed. Revision 2's `U.6` voided `superseded`, but host rule 5 accepted `superseded` after consumption for completion. | One **current-round pointer** per (contract, mandate, PR). Only the pointed-to record is operative for any gate; `superseded` is archival only. Opening a new round voids the previous head's unconsumed sign-off. Pointer restore after revoking an unconsumed round is an explicit host decision. Rules 2, 5 and 6, `U.6` and the replay row now agree. Host tests 21 cover `U1` consumed with `U2` active and with `U2` consumed. |
| DU-06: check, push, then consume was not exclusive | Confirmed. Two consumers could each pass the `active` check and push `E1`, then `E2`, both fast-forwards. | An exclusive, durable reservation `active → reserved(F→E) → consumed / revoked` under a lock keyed to the round, recorded before the push. `--force-with-lease=…:{F}` makes the remote predecessor exactly `F`. Uncertain outcomes fail closed and reconcile from the live head. A reservation never returns to `active` or admits another head. Tests 22–24. |
| DU-07: the final re-read checked only four fields | Confirmed. A base retarget leaves head SHA, ID, state and draft equal. | `I.5` re-parses the final detail with the full `_pr_facts(detail=True)` validation, requires equality of all normalized facts, and rechecks the route against the binding. Test 16 adds the retarget and malformed-detail cases; mutant list updated. |
| Notes: state table, `A...F`, commits endpoint, merge check, cache wording, coexistence, slice 2 | Accepted. | Round open ignores evidence (old `P == F == E` gives at most round open). `A...F` may be `identical` in every state. The audit uses the retained exact `F → E` chain; the 250-commit `pulls/{n}/commits` is only a fail-closed cross-check. The merge check uses `--max-count=1`. No-cache is stated as a requirement for any cache. Whole-context validation and pairwise identities still apply. Slice 2 ships only with the slice 1 host obligations. |

### Round 3

| Finding | Verified | Resolution |
| --- | --- | --- |
| DU-08: the host could not bind its reservation to the validated head | Confirmed. The record binds only `F`, and the report had no field naming `E`, so a host would reread worker-controlled evidence or `HEAD`. A bare lease on `F` even accepts an unrelated `E2`. | The smaller fix: the report gains `candidate_head`, the exact `E` that passed `T(E)` in that run. It is non-null exactly for `push` and `recognized`. The host reserves and pushes that SHA from its own captured `verify` result, never a worker-relayed copy or a reread, and re-proves the frozen `F → E` before submitting. Tests 25 and the mutant list. No exact-`to_head` human event (D3 unchanged). |
| DU-07 (Low): the final read dropped the raw merged flag | Confirmed. `_pr_facts(detail=True)` validates `merged` but does not project it. | `I.5` also requires the final raw detail to satisfy `state == "open"`, `draft is True`, `merged is False` and `merged_at is None`, as `check_publication` does. Test 16 adds the inconsistent `merged: true` fixture. |
| Notes: lease wording, retries and expiry, round-open prose, status inventory, pointer restore, commit-list cross-check | Accepted. | The lease is described as a predecessor condition only; fast-forward comes from the separate ancestry proof; "no force-push event" is an expectation the acceptance trial observes, with the denylist kept. Every submission, including retries, needs the original deadline, the current pointer and non-revocation; late retries are refused (test 26). Round-open prose is narrowed to no evidence or `E == F`. `reserved(F→E)` is in the status list. Restoring the pointer moves the previous round back to `consumed`, and voided sign-offs stay void. The commit-list cross-check is removed. |

### Round 4

| Finding | Verified | Resolution |
| --- | --- | --- |
| DU-09 (Low): the design still called overlap dispositions inert | Confirmed: since `efe7e68` a valid, current `overlap_dispositions` section waives bound topical overlaps for every schema 0.2 gate. | `U.5`, Interplay, Coexistence and test 11 now say the update path uses the same post-disposition overlap list as every other gate, and that `draft_update` adds or widens no waiver. No behaviour change. |
