# Updating a recognized draft after review (#21): design proposal

- Date: 2026-11-02
- Status: proposal, revision 1, not reviewed. Design only; no code in this change.
- Base: `rsi/v03-land` at `e454848` (unreleased v0.3.0 candidate: task and evidence schemas 0.1 and 0.2, host-context 0.1 and 0.2).
- Issue: [#21](https://github.com/nkovanen/agent-contrib/issues/21), product-map key F3. Depends on #3. Uses #20 (`feedback`).

## Summary

After a schema 0.2 draft PR is recognized, the human may authorize one round of
fixes with a new, separately issued host-context record, `draft_update`. The
record is bound to the contract, the mandate, the recognized PR and the head it
starts from (`from_head`). The record authorizes two things: local fixes on the
reviewed `head_ref`, and fast-forward pushes from `from_head` by the host.

`verify` recognizes the updated draft only when all of these hold:

- the PR is the same own draft;
- its head is a strict descendant of `from_head`, and `from_head` is a descendant of the creation head;
- the PR timeline shows no force-push, branch deletion or restore, close or reopen;
- fresh technical evidence and a fresh independent review exist for exactly the new head.

Old evidence, review and sign-off never carry over; each is already bound to `git_head`. The task schema, schema 0.1 and host-context 0.1 are unchanged. The CLI still writes nothing to GitHub.

## Problem: what the code does today

A schema 0.2 draft is recognized only at the head it was created with. After review, any push makes the contribution unrecognizable:

- **Claim head.** `pr_identity.check_publication` requires the worker's publication claim `head_sha` to equal the validated evidence head (`pr_identity.py:189-190`).
- **Live head.** It requires the live PR head to equal that same head (`:202-203`).
- **Creation time.** The PR's `created_at` must lie inside the mandate interval (`:204-205`).
- **History.** Exactly one PR may exist in the exact head/base history for `head_ref` (`:162-176`, `:191-192`).
- **Recognition.** `lifecycle.verify` exempts only that recognized own PR from overlap blocking (`without_own`, `lifecycle.py:165-169`, `:258-260`). Its `next_action` is one of `resolve_blockers`, `implement`, `create_draft` or `none` (`:295-300`; output enum in `schemas/output/1/verify.schema.json`).
- **Implementation stage.** After publication, the implementation stage is permanently blocked: it requires an empty exact-head history (`:249-251`).
- **Mandate.** It authorizes only `implement` and `create_draft` (host-context `mandate.actions` enum, maxItems 2; task `execution.requested_actions` likewise). Expiry blocks new actions (`authorization.py:166-170`).
- **Final sign-off.** It binds `git_head`, the review hash, the contract and the mandate. It must follow PR creation and the review (`lifecycle.py:86-107`).
- **Workflow.** The installed workflow says "No updates, ancestor-only exemption, force-push adoption or reopening are supported", and makes preventing updates the host's job (`instructions.md:356-367`).

So after `feedback 'owner/repo#N' --expected-head A` (#20) reports requested changes, the only paths today are to abandon the draft or to break the protocol.

## Options considered

| Option | Change | Why not chosen |
| --- | --- | --- |
| Add `update_draft` to `mandate.actions` (the issue's literal proposal) | Task schema 0.2 `requested_actions` enum and maxItems; mandate enum | The original mandate is at most 24 h, so reviews often arrive after it expires. A new mandate cannot be used either: the claim binds `mandate_sha256`, and `created_at` must lie in the mandate interval, so a fresh mandate stops recognizing the existing PR. It is also a task schema change. |
| New host-context version 0.3 | New exact version | Larger than needed. 0.2 is unreleased and already the precedent for an optional section (`overlap_dispositions`). |
| **Optional `draft_update` section in host-context 0.2** | One optional section; verify, output and text additions | **Chosen.** It is a later human event that is independent of the mandate's expiry, like `final_signoff`. It also leaves task schema 0.2 untouched. |
| Bind the exact `to_head` in the record (the human approves the pushed SHA) | Record issued after the fix is reviewed | Strictly stronger, but it needs two human events per round (one to start fixes, one to push). It is also not symmetric with creation, which validates the published head after the fact. It is kept as a possible tightening (D3). |

Decision for the maintainer (D1): extend host-context 0.2 before the v0.3.0 release (recommended), or freeze 0.2 and add 0.3.

## The `draft_update` record

The record is human/host-issued, optional, and absent by default. Its fields:

| Field | Binding |
| --- | --- |
| `id`, `nonce`, `issued_at`, `expires_at` | As for `final_signoff`. The interval must be positive, at most 24 h and not in the future. `id`, `nonce` and `event.reference` must differ from the mandate, final sign-off and overlap dispositions (the same rule as `lifecycle.py:139-142`). |
| `contract_sha256`, `mandate_sha256` | The exact contract, and the unchanged original mandate. |
| `credential_actor_id` | Must equal the mandate actor and the live `GET user` ID. |
| `repository_id`, `pr_number`, `pr_id` | Must equal the publication claim and the live PR. |
| `from_head` | A 40-hex SHA: the head the human saw when authorizing fixes. It must equal the live PR head before the push, and be its ancestor after. |
| `event` | `kind`, `reference`, `text_sha256` and `binding_sha256`, computed like every other event (`authorization.event_hash`). |

The publication claim keeps its creation `head_sha` (call it `A`). It still names the first published head and stays untrusted association data. The mandate, its interval and `created_at`-in-interval rule are unchanged. Exactly one `draft_update` record is carried at a time: the current round. Earlier rounds are host audit records (see Limits).

## Verification

Every check below is a GET, and every failed or partial read blocks. Let `P` be the live PR head, `E` the evidence head and `F` the record's `from_head`.

1. **Same draft.** These existing checks apply unchanged:
   - exactly one PR in the exact head/base history;
   - list and detail agree;
   - open, draft and unmerged;
   - the author is the bound actor;
   - the route and URL are unchanged;
   - creation inside the mandate interval.

   The only change is that the claim-head equality checks (`pr_identity.py:189-190`, `:202-203`) are replaced, when a valid record is present, by:
   - `P == E`, or, before the push, `P == F`;
   - `F` is `A` or a descendant of `A`;
   - `P` is a descendant of `F`.
2. **Fast-forward only.**
   - `GET repos/{repo}/compare/{A}...{F}` and `.../compare/{F}...{P}` must be `identical` or `ahead`. `diverged` or `behind` blocks.
   - Before a push, the local relation `F` to `E` is checked with `merge-base F E == F` through the hardened `core.git_read`.
3. **No rewrite or reopen.**
   - The paginated `GET repos/{repo}/issues/{n}/timeline` must contain no `head_ref_force_pushed`, `head_ref_deleted`, `head_ref_restored`, `closed`, `reopened` or `convert_to_draft` event.
   - `convert_to_draft` means the PR was once marked ready.
   - Any of these events blocks, even when the final head is a descendant: force-push adoption is out of scope.
4. **Fresh evidence and review at the new head.** This reuses `core.check_evidence` and `independent_review` unchanged:
   - `git_head == E`;
   - every validation starts at or after `E`'s committer time;
   - the review is bound to `E` and the contract and follows the validations;
   - the evidence base stays the reviewed source commit.

   Old evidence cannot pass because it names `A` or `F`.
5. **Overlaps.** Unchanged: only the recognized own PR (same ID, number and URL) is exempt.

### States and gates

The verify result gains an optional `draft_update` report: `status`, `sha256`, `from_head`, `errors`. Two `next_action` values are added. Draft-stage exit 0 keeps its meaning: "the next draft action is safe, or nothing is needed".

| State | Facts | Result |
| --- | --- | --- |
| No record | as today | byte-identical to today |
| Record valid and current; `P == F`; recognized at `F` with evidence at `F` (or none yet) | | `draft_update.status: implement`, `next_action: implement_update`. The implementation stage passes, replacing the post-publication block at `lifecycle.py:249-251`. |
| Record valid and current; `P == F`; valid evidence and review at `E`; `E` a strict local descendant of `F` | | `status: push`, `next_action: push_update`, draft-stage exit 0. The host pushes `E` fast-forward only (no `--force`). |
| Record valid (current or historical); `P == E`; steps 1–5 hold | | `status: recognized`, `publication.verified: true`, `next_action: none`. |
| `P` differs from both `E` and `F`; diverged compare; forbidden timeline event; wrong PR; stale evidence; invalid record | | `status: blocked` or `invalid` with errors; never verified. |

**Expiry.** The record must be current for `implement_update` and `push_update`, which are new actions. After the push it may have expired, as the mandate may after creation. The push time itself is not observable through the REST API, so the host retains it (see Limits).

## Interplay

- **`feedback` (#20).** This is the expected loop:
  1. `feedback 'owner/repo#N' --expected-head A` reports change requests.
  2. The human reads them with the PR and diff, and issues `draft_update` with `from_head = A`.
  3. The worker fixes, validates and gets an independent review at `E`.
  4. `verify --stage draft` gives `push_update`; the host pushes; `verify` reports `recognized`.
  5. `feedback --expected-head E` starts the next round.

  Review text stays untrusted and never widens scope. A scope change still needs a new contract, and so a new PR. Binding a feedback snapshot hash into the record was considered and dropped (YAGNI): the human event already references what they saw.
- **Final sign-off.** It still binds `git_head` (now `E`), the review hash at `E`, the contract and the mandate. It must additionally follow `draft_update.issued_at` when a record is present. A sign-off for `A` or `F` is stale automatically. Completion still requires a verified draft at exactly the signed head.
- **Overlap dispositions (#7).** These are independent records. The identity-distinctness rule extends to `draft_update`.
- **`pr-body`.** Unchanged: it takes no host context and never reports authority.

## Replay and staleness

| Attack or race | Outcome |
| --- | --- |
| Reuse the record for another PR, contract or mandate | Bound IDs and hashes differ: invalid. |
| Reuse it after the head moved, to authorize another round | Before a push, `F` must equal `P`; a new round needs a new record with `from_head = P`. |
| Several fast-forward pushes within one record's interval | Allowed. Each is recognized only with fresh evidence and review at the exact live head. Single use per record is a host policy (D2). |
| Someone else pushes to the branch | `P` is neither `E` nor `F`, or fails `merge-base`, or the evidence doesn't match `P`: blocked. |
| Force push, rebase or a delete/restore of the ref, even back to a descendant | The timeline event blocks. |
| A false creation head `A` in the claim | `A` must be an ancestor of `F` and `P`. Rewriting is caught by the timeline. The host retains the true creation head (unchanged duty). |
| A merge of the newer base into the branch | It is a fast-forward, but the evidence scope check against the reviewed `base_commit` sees base changes as out of scope, so it blocks. Updating to a new base is unsupported (re-prepare). |
| A race between reads | Snapshots are not atomic, so re-verify (unchanged). |

## Compatibility

- **Unchanged:** task and evidence schemas 0.1 and 0.2, host-context 0.1, schema 0.1 routes and every result without a `draft_update` section.
- **Host-context 0.2:** gains one optional section, before release (D1). Unknown sections and versions still fail closed.
- **Output schema `verify` (version 1, unreleased):** gains the optional `draft_update` object and two `next_action` values. A consumer pinned to the current enum fails closed on the new values.
- **Workflow:** the "No updates …" paragraph is replaced by the update loop. Hosts must still refuse force pushes.

## Limits (documented, not solved)

- The push time is not observable through the REST API. The verifier checks record currency at `push_update` time, and the host retains the push event and head, as it already does for creation.
- Only the current round's record is carried. Earlier rounds' records and heads are host audit data. The verifier checks the current head's ancestry from `A` and the timeline, not every past authorization.
- The timeline is the evidence for "no force push". A hidden or unreadable timeline blocks.
- The PR must stay a draft. Ready-for-review, base retargeting, reopening and the fork route are out of scope.

## Adversarial test plan

All tests use fixtures: fake PR, compare and timeline responses, and temporary Git repositories.

1. **No record:** every existing lifecycle test passes, with byte-identical output (golden).
2. **Record schema:** missing or extra fields, bad SHA, an interval over 24 h or in the future, a reused id, nonce or reference, a 0.1 context carrying the section, and a bad event hash.
3. **Wrong binding:** another contract, mandate, actor, repository, PR number or PR ID.
4. **Non-fast-forward:** `E` not a descendant of `F` locally; compare `diverged` or `behind` for `A...F` or `F...P`; compare errors or a malformed status.
5. **Rewrite:** each forbidden timeline event alone; a timeline that fails to paginate; a duplicate event ID.
6. **Stale evidence:** evidence at `A` or `F` with `P == E`; review bound to an older head; review before validations; a validation started before `E`'s commit.
7. **Head moved by someone else:** `P` a descendant of `F` but not `E`; `P` unrelated.
8. **Expiry:** an expired record blocks `implement_update` and `push_update`, but still recognizes a completed push.
9. **Replay:** a record whose `from_head` is behind the live head before a push.
10. **Sign-off:** a sign-off for `A` after the update; a sign-off issued before `draft_update.issued_at`; a valid sign-off at `E` completes.
11. **History and route:** a second PR on the same head ref; a changed base ref; a ready (non-draft) PR; a merged or closed PR.
12. **Mutants (each must be killed):** dropping the timeline check; accepting `diverged`; skipping `F` currency; reusing the old claim-head equality; dropping the sign-off ordering rule.

## Slices

1. **Inert schema.** Host-context 0.2 `draft_update` plus the record checks (bindings, event, interval, distinct identity), reported as `status: not_evaluated`. Output schema key. No gate change. This mirrors overlap-dispositions slice 1.
2. **Recognition after a push.** Compare and timeline reads, the `P == E` path with ancestry from `A` and `F`, `publication.verified` at the updated head, and sign-off ordering.
3. **Pre-push readiness.** `implement_update` and `push_update`, the local `merge-base` check, stage gates, and text summaries.
4. **Workflow.** `instructions.md` loop, `authorization-request --draft-update` (pre-filled bindings, `null` human fields), docs, and an acceptance trial with a real human/host-issued record.

## Decisions

- **D1:** extend host-context 0.2 (recommended) or add 0.3.
- **D2:** several fast-forward pushes per record within its interval (recommended), or single use enforced only by the host.
- **D3:** keep `from_head` only (recommended), or also bind the exact `to_head` with a second human event per round.
