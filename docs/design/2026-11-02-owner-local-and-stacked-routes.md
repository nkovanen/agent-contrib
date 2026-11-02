# Owner-local and stacked routes: design proposal

- Date: 2026-11-02
- Status: proposal, revision 3. Hostile review round 1 (RD-01 to RD-06) and round 2
  (RD-07 to RD-09) are resolved in [Review resolution](#review-resolution).
- Base: `47c80a1` (unreleased v0.3.0 candidate; task/evidence schemas 0.1 and 0.2,
  host-context 0.1).
- Input: dogfood 1, Stage 1 friction log, findings F1, F2, F3 and F6.

## Summary

| Finding | Recommendation | Ships as |
| --- | --- | --- |
| F6: the workflow asks for contract records that have no field | Name the exact existing fields in the workflow. Defer typed fields to the next task schema that is needed anyway (#16/#17). | Docs only |
| F3: no way to produce an authorization request | Add a read-only `authorization-request` command. It prints an unsigned request with every binding field pre-filled from the contract and live reads, and every human-only field `null`. It contains no display summary: the host renders the complete contract from its own snapshot. Its output can never pass as host context. | CLI, no schema change |
| F2: no route for owner-local, coordinator-delegated work | Add no new mandate format. A host-context 0.1 mandate with `actions: ["implement"]` already is the minimal implement-only profile. Document it, define normative host-issuer requirements, and state that a coordinator relays but never issues. Native Paseo/Claude Code issuers live in the hosts (#23). | Docs |
| F1: stacked or unpublished bases can never validate | Document the limitation and the land-first procedure. A local-base mandate is **not specified**. It is recorded as a future direction with preconditions, starting with a host that can show the human the complete source-to-base diff and instruction contents. | Docs only |

All four fit inside the existing trust model. Authority still comes only from a
human/host-issued record. Every new field the CLI emits is a binding that
`verify` re-checks. Nothing the worker supplies is used as approval material. No
existing contract, evidence or host-context document changes meaning, and no new
schema version is proposed.

## Invariants this design must keep

1. A worker, a coordinator agent, issue text or repository content cannot create
   authority. Only a human/host-issued `mandate` (and later `final_signoff`) can.
2. Source approval, local execution authorization and publication authority stay
   separate. Implement-only authority never implies publication.
3. Missing, partial or unverifiable data fails closed. A report is never permission.
4. Exact schema versions. Schema 0.1 and 0.2 tasks/evidence and host-context 0.1
   documents keep identical decisions: the same gate booleans, `next_action`, exit
   codes and existing error strings. New information goes only in new keys, new
   commands or new schema versions.
5. The CLI stays read-only towards GitHub and never executes contract argv.

## Current behavior these designs depend on

These were checked against `47c80a1`:

- `implementation_ready` never looks at evidence or a local base
  (`lifecycle.py` `verify`). It needs a reviewed contract (all `prerequisites`
  `satisfied`, `lifecycle.py:68`), a valid current mandate with `implement`, and
  complete live reads with no overlap. It also needs empty exact-head PR history,
  which is read only after a mandate is valid (`lifecycle.py:215-221`).
- Base pinning happens only in evidence. `core.check_evidence` requires a GitHub
  `compare/{current_default_tip}...{evidence.base_commit}` status of
  `behind`/`identical`, then checks locally that `source.commit` is an ancestor of
  `base_commit`, which is an ancestor of `HEAD`. The scope diff is
  `base_commit..HEAD` (`core.py:680-705`). An unpublished base makes GitHub
  return 404 (`ProtocolError`), so the error is "Could not authenticate evidence
  base against source default-branch history", and `technical_evidence_valid`
  stays false. Using the published default-branch commit as the base puts every
  unpublished commit into the scope diff instead.
- `execution.base_ref` must equal the source default branch
  (`authorization.py:134`). `source.commit` and `source.instructions_sha256` come
  from the default-branch snapshot.
- Implement-only mandates already work: `mandate.actions` may be `["implement"]`,
  which makes `create_draft` and therefore `draft_create_ready` impossible.
- The host-context schema is closed, and `bundled_schema` accepts only host-context
  `0.1` (`core.py:612-614`).
- `verify` without host context already returns the canonical `contract_sha256`,
  the source identities and the live `credential_actor`/`permission`. The
  contract-only route checks (mode, refs, base = default branch, same-repository
  identities) run only after a host context is present (`authorization.py:124-137`).

---

## F6: AI-policy review and requirements-ledger references

### Problem

The workflow says to "record the [AI-policy] review in the contract"
(`instructions.md:26-28`) and to "reference the ledger in existing review notes"
(`instructions.md:86-88`). Task schemas 0.1 and 0.2 have no review or notes field,
and unknown fields fail closed. Agents improvise, and they improvise differently.
The dogfood worker used a `constraints` string plus a `satisfied` prerequisite,
and put a post-implementation obligation in `prerequisites`, which blocked
implementation permanently (F5).

### Threat model

- A worker can write anything into these records. They are self-attested under
  every option, typed or not, and only the independent reviewer and the human
  check them.
- Issue text or repository prose could tell the agent to record "AI policy:
  permitted". Only the agent's reading of `inspect --ai-policy` output may feed
  the record. Zero hits are never permission (unchanged).
- A typed field would not add verification. The CLI cannot judge whether excerpts
  were read correctly. At most it could check that the recorded commit equals
  `source.commit`.

### Options

| Option | Pros | Cons |
| --- | --- | --- |
| A. Map to existing fields in the workflow | No schema change. Works for 0.1 and 0.2 today. A refusal naturally blocks through `prerequisites`. | Convention only; `verify` does not check that the record is present. |
| B. Typed `reviews` object in task schema 0.3 | Machine-readable; `verify` could require presence and commit equality. | A new task schema version for little gain. All consumers change. Still self-attested. |
| C. Allow `x-*` extension fields | Flexible | Weakens fail-closed parsing; unbound semantics; downgrade surface. Rejected. |

### Recommendation

A now. Fold B into the next task schema version that is needed for other reasons
(#16 baselines or #17 required checks); it does not justify its own version.

### Exact workflow changes (`agent_contribute/instructions.md`)

Replace the sentence "record the review in the contract and disclose it in the PR
body" (lines 26-28) with:

> Record the result as the contract prerequisite with ID `ai-policy-review`.
> Use `satisfied` with evidence naming the source commit, scan coverage, excerpt
> count and your conclusion. Use `blocked` when the repository refuses AI
> contributions, and `pending` while coverage is incomplete or excerpts are
> unresolved. Disclose agent assistance in the PR body. Zero hits are not
> permission.

Replace "Reference the ledger in existing review notes; do not add undeclared
schema fields …" (lines 86-88) with:

> Map requirements into existing fields; never add undeclared fields:
> - conditions that must hold **before** implementation go in `prerequisites`.
>   Every prerequisite must be `satisfied` with evidence before
>   `implementation_ready`;
> - obligations due during or after implementation, such as precommit gates,
>   docs, compliance review and publication checks, go in `constraints`,
>   `validation` or `behavior_criteria`, never in `prerequisites`;
> - the ledger itself goes in one `constraints` entry starting `Requirements
>   ledger:`. It names the ledger by a portable name, not a host path or content
>   hash, because the ledger changes as rows are reconciled and a hash would
>   force contract rebinding;
> - the compliance conclusion goes in evidence `independent_review.notes`, with
>   the SHA-256 of the exact ledger version the reviewer checked.
>
> The human/host may also cite a ledger hash in `mandate.policy_review.notes`;
> the worker never writes that field.

The rest of the paragraph is unchanged. The same mapping is valid for schema 0.1:
both versions have `prerequisites`, `constraints` and `independent_review.notes`.

### Backward compatibility

No schema, code or verification change. Existing contracts keep their decisions.
The only behavior change is how agents fill new contracts.

### Test plan

1. A workflow-resource test asserts that `instructions` names
   `ai-policy-review`, `Requirements ledger:` and `independent_review.notes`, and
   no longer contains "record the review in the contract" or "existing review notes".
2. Regression pins for behavior that already exists, so the convention keeps its
   meaning:
   - a 0.2 contract with `ai-policy-review` `blocked` gives `implementation_ready:
     false` with "Prerequisites are not satisfied with evidence";
   - the same contract with `pending` gives the same result;
   - with `satisfied` and blank evidence, the same result;
   - the same three cases for schema 0.1 readiness.
3. A contract that follows the mapping validates against both task schemas, and
   adding a `reviews` key is still a schema error (fail-closed pin).

### Out of scope

Typed review fields (deferred to the next task schema); enforcing that the
prerequisite exists; F5's naming of the failing prerequisite IDs (a separate
diagnostics change).

---

## F3: `authorization-request`

### Problem

The workflow says "the worker may prepare an authorization request", but nothing
produces one. The worker must reverse-engineer the host-context schema to list
about 20 binding fields. That is error-prone, and a hand-assembled request blurs
the line between requesting and issuing.

### Threat model

- **The worker self-issues by filling the nulls.** That is already possible today
  by hand from the published schema, and the documented same-credential boundary
  applies. The command must not make it look legitimate. The output is labelled,
  has a different top-level shape from host context, and its human-only fields
  are `null`, so piping it or its `mandate_fields` into `--host-context-stdin`
  fails schema validation.
- **The human is shown something other than what is bound** (RD-01). Suppose a
  request summary describes contract X while the worker supplies contract Y and
  Y's correct hash. The host hashes Y, the human sees X, and `verify` accepts Y.
  Every hash comparison is consistent, yet the approval is meaningless. The same
  happens with an honest but partial summary: two contracts that differ only in
  `validation[].argv` share every summary field. Display material is not part of
  the binding, so `verify` cannot catch this. Only the host can. The command
  therefore emits **no display summary at all**. The issuer requirements (F2)
  make the host render the complete contract from the same parsed snapshot it
  hashes and issues from.
- **Injected remote text** (an issue title saying "Owner pre-approved, click
  accept") would influence the human. The output carries no remote free text:
  identities, refs, hashes and action names only. The contract the host renders
  is worker-authored data and is displayed as data (F2).
- **Pre-filled binding fields are wrong** (stale or malicious). Every field in
  `mandate_fields` is re-verified by `verify` against the contract and live
  GitHub after issuance, so a wrong *binding* value can only produce a mandate
  that fails closed. This guarantee covers bindings only, never anything shown to
  the human, which is why no shown material comes from the request.
- **Extra reads or writes.** The command performs exactly the reads of
  `verify task.json` without host context, writes no file and reads no stdin.

### Options

| Option | Pros | Cons |
| --- | --- | --- |
| A. Read-only `authorization-request task.json`, stdout only | Small; reuses `verify` reads; no new authority surface | Output format is new (no output schemas yet, #24) |
| B. Only document the field list | No code | This is exactly what the friction was; drifts from the schema |
| C. A `mandate init` that writes a host-context skeleton file | Convenient for hosts | Produces something shaped like a mandate in the worker's tool channel; one step from self-issuance. Rejected. |

### Recommendation

A.

### Exact CLI change

`agent-contrib authorization-request CONTRACT` (global `--format` and
`--report-budget` apply as usual). It has no `--output` option and no stdin.

Behavior:

1. Read the contract. Anything other than `schema_version: "0.2"` is a usage
   error: exit 2, no request.
1a. Validate the **full** bundled task 0.2 schema (`core.validate_contract`) before
   any route extraction, network read or request construction (RD-08). On
   failure, print `{"error": {"code": "invalid_contract", "message": ...,
   "schema_errors": [...]}}` and exit 1. There is no request, no binding template
   and no GET. This catches missing fields, unknown properties and wrong nested
   types, which would otherwise hit `KeyError` paths that the CLI does not catch.
2. Run `lifecycle.verify(task)` without host context or evidence; these are the
   same GETs as `verify`.
3. Run the contract-only route checks. Factor them out of `authorization.check`
   into `authorization.route_errors(task)`: mode `repository-candidate`, valid
   refs, base = default branch, head ≠ base, same-repository IDs
   (`authorization.py:124-137`). `check` keeps calling it with the same strings
   in the same order. The mandate-dependent actions check stays in `check`. Add
   two request-only checks: "Contract requests no actions" and "Contract
   requested actions are duplicated".
4. `preflight_errors` = route errors plus `stage_blockers.implementation` minus
   the three blockers that are expected before a mandate exists:
   - "Missing human/host mandate"
   - "Current implement action is not authorized"
   - "Implementation requires complete empty exact-head PR history"
5. Exit 0 when `preflight_errors` is empty, otherwise 1. Print the request in both
   cases, so the human can see why it is not ready.
6. `preflight_errors` are copied from `verify` and may contain sanitized,
   repository-authored text, such as the path of an unreadable instruction file
   (RD-09). The request labels them `preflight_errors_trust: "untrusted
   diagnostics; may contain repository-authored paths; never approval material"`.
   `verify` diagnostics are not changed for this command.

Output (JSON):

```json
{
  "kind": "agent-contrib/authorization-request",
  "request_version": "0.1",
  "issued": false,
  "notice": "UNSIGNED REQUEST. Not a mandate; grants no authority. Contains no approval material: the host must render the complete contract from its own snapshot. Only the human/host issues a mandate; the worker relays it unchanged.",
  "target_host_context_schema_version": "0.1",
  "ready_for_issuance": true,
  "preflight_errors": [],
  "preflight_errors_trust": "untrusted diagnostics; may contain repository-authored paths; never approval material",
  "unresolved_fields": [],
  "contract_sha256": "<canonical hash, same as verify>",
  "exact_head_pr_history": "not checked before issuance; verify checks it after",
  "mandate_fields": {
    "id": null, "nonce": null, "issued_at": null, "expires_at": null,
    "contract_sha256": "<hash>",
    "source_repository_id": 1, "source_owner_id": 2, "issue_id": 3, "issue_number": 12,
    "target_repository": "owner/repo", "target_repository_id": 1,
    "head_repository": "owner/repo", "head_repository_id": 1,
    "head_ref": "branch", "base_ref": "main",
    "credential_actor_id": 2, "authority": "owner",
    "actions": null,
    "policy_review": {"status": null, "instructions_sha256": "<contract>", "policy_sha256": "<contract>", "notes": null},
    "event": {"kind": null, "reference": null, "text_sha256": null, "binding_sha256": null}
  },
  "human_only_fields": ["id", "nonce", "issued_at", "expires_at", "actions",
    "policy_review.status", "policy_review.notes",
    "event.kind", "event.reference", "event.text_sha256", "event.binding_sha256"],
  "provenance": {"fetched_at": "...", "endpoints": ["..."]}
}
```

Field rules:

- `credential_actor_id` comes from live `/user`, and only when the live
  permission check passed. `authority` is `owner` when that ID equals
  `source.owner_id`, else `maintainer`. Both derive from live facts, and
  `verify` re-checks both.
- **Null-leaf invariants (RD-08).** The two invariants are:
  - **Ready request:** the `null` leaves of `mandate_fields` are exactly
    `human_only_fields`, and `unresolved_fields` is empty.
  - **Blocked request:** automatically derived fields that could not be
    established (`credential_actor_id` and `authority` after a failed identity or
    permission read) may also be `null`. They are listed in `unresolved_fields`,
    never in `human_only_fields`, and must be resolved by fresh trusted reads,
    never by a human or host filling them in. The `null` leaves are exactly
    `human_only_fields` plus `unresolved_fields`.
- `actions` is `null`: the human chooses a subset of `requested_actions`. The
  host offers exactly that subset.
- `event.kind` is `null` even though the schema constant is `human`. The host
  asserts it, and a `null` keeps the untouched template invalid.
- The request has no scope, path, objective, criteria or validation summary. The
  `contract_sha256` lets the host flag a mismatch with its own hash; it is never
  the hash the host binds.

Workflow change: the sentence "The worker may prepare an authorization request"
names the command and adds: "Give the host the exact contract file and the
request. The host renders and hashes the contract itself. Never write a summary
for the human in place of the contract, and never fill in the request's `null`
fields."
Add the command to `docs/cli.md`, and add an issuer section to
`docs/host-authorization.md` (see F2).

### Backward compatibility

A new command. `verify` output and decisions are unchanged. The `route_errors`
refactor is pinned by existing `authorization.check` tests plus a golden
comparison of `check` output across the refactor.

### Test plan

1. **Round-trip completeness, the key test.** Take a reviewed 0.2 contract and
   FakeGitHub, run `authorization-request`, fill only the `human_only_fields` as a
   test host would, compute the event binding, wrap it in `{"schema_version":
   "0.1", "mandate": …}`, and run `verify --stage implementation`: it must give
   `implementation_ready: true`. This proves that no binding field is missing or
   wrong.
2. Null-leaf invariants. In a ready request, the `null` leaves equal
   `human_only_fields`. In a blocked request (failed permission read), they equal
   `human_only_fields` plus `unresolved_fields`, which holds `credential_actor_id`
   and `authority`. In both, every host-context `mandate` property is present,
   checked by walking the bundled schema, so a future schema field cannot be
   silently omitted.
2a. Invalid contracts (RD-08): a missing `source`, an unknown root property, a
   wrong nested type (for example `execution.head_repository_id: "1"`) and
   `{"schema_version": "0.2"}` alone each give exit 1 and an `invalid_contract`
   error with schema errors. The output has no `mandate_fields`, and no GET is
   made.
3. Piping the whole request, or `{"schema_version": "0.1", "mandate":
   request["mandate_fields"]}`, to `verify --host-context-stdin` yields
   host-context schema errors and no authority.
4. A schema 0.1 contract exits 2 with no request. An unknown schema version fails
   closed.
5. Preflight with exit 1 and `ready_for_issuance: false` for each of:
   - a draft contract, unanswered questions, a `pending` prerequisite;
   - mode `pending`, empty `head_ref`, base ≠ default, head = base,
     `requested_actions: []`;
   - a changed repository or issue ID, a non-admin/maintain role, a bot actor;
   - an open overlapping PR, an incomplete live read.
6. Authority derivation: actor = owner gives `owner`, a maintainer gives
   `maintainer`, and a failed permission read gives `null` plus an error.
7. Reads: the `client.calls` sequence equals that of `verify task.json` with no
   host context. Only GETs, no stdin read, and no file created in the working
   directory.
8. An issue title, body and comment carrying injection text and control characters
   do not appear anywhere in the output. An unreadable instruction file with an
   adversarial path (RD-09) appears only inside `preflight_errors`, sanitized,
   with the untrusted-diagnostics label, and the request is not ready. The output has no key other than the
   documented ones; in particular it contains no scope, path, objective,
   criteria or validation material (RD-01 pin).
9. `contract_sha256` equals `verify`'s value and the documented recipe; a one-byte
   contract change changes it.
10. Mutation testing in a `/tmp` copy: drop a binding field, swap head/target IDs,
    pre-fill `nonce`, invert the authority derivation, report `ready` with errors,
    or omit an expected-blocker filter. Each must be killed.

### Out of scope

Output JSON Schemas (#24); checking exact-head PR history before issuance; any
signing; a `--output` file.

---

## F2: owner-local, coordinator-delegated work

### Problem

The repository owner wants a worker, dispatched through a coordinator agent, to
implement locally in the owner's own repository with no publication. The schema
0.2 route requires a human/host mandate. A coordinator instruction correctly is
not one. There is no host that issues mandates natively, so the honest outcome is
"blocked", every time.

The gap is **issuance**, not the format. A host-context 0.1 mandate with
`actions: ["implement"]` already expresses "implement this contract locally, publish
nothing". `create_draft` is absent, so `draft_create_ready` can never be true, and
the CLI has no write path.

### Threat model

- **The worker self-issues.** Any issuer the worker can invoke through its own
  tools (a CLI subcommand, an MCP tool, a plugin RPC that returns a mandate) is
  self-issuance. Therefore no issuer goes in this CLI, which is
  worker-reachable by design.
- **Coordinator compromise.** A coordinator agent reads issue text, worker output
  and repository prose, so prompt injection can steer it. If the coordinator could
  issue, untrusted issue text could escalate to authority through it. A
  coordinator relays the request to the human and the issued mandate back,
  unchanged. It never issues.
- **Agent-callable approval channels.** Paseo exposes agent-callable permission
  responses (`respond_to_permission`). An issuer built on host permission prompts
  must not accept approvals that arrive through any agent-callable API. Otherwise
  the coordinator approves its own worker.
- **The standing-delegation slide.** "Auto-approve implement-only for repository
  X" removes the human's view of the concrete scope and hash. That contradicts the
  "present the concrete scope, stop for approval" rule.
- **Same-credential forgery.** A hostile process running as the same user can
  write any file. This remains a documented non-goal: host-asserted, not
  cryptographic.
- **Overlong authority.** Local work sessions are short; a 24-hour mandate
  invites reuse beyond the reviewed task.
- **Display/binding split** (RD-01). The host binds contract Y but shows the human
  a worker-supplied summary of X, or an honest summary that omits validation argv.
  Hash checks cannot detect this, so the issuer must render what the human sees
  from the exact snapshot it binds.
- **Replay after revocation** (RD-05). The CLI is stateless by design: the same
  unexpired mandate verifies again and again (the reviewer's probe confirms
  this). If the human revokes mandate M1 and approves M2 for the same contract, a
  worker holding M1 can keep relaying it until M1 expires. Only the host can
  refuse it, and only at the point where it consumes authority.

### Options

| Option | Pros | Cons |
| --- | --- | --- |
| A. Implement-only profile of the existing 0.1 mandate, plus normative host-issuer requirements and coordinator relay rules (docs); issuers live in hosts (#23) | No new authority format; F3 removes the assembly cost; every binding is still verified | Needs host work before the dogfood loop is unblocked |
| B. A lighter "local delegation" record (no event, nonce or policy review) | Easier for hosts | A second, weaker authority format and a downgrade target. It saves little once F3 pre-fills everything. Rejected. |
| C. Standing delegation: the host auto-issues implement-only mandates under a human-configured rule | No per-task click | The human never sees the concrete contract. It changes the protocol's core consent rule. Needs Niko's explicit risk decision; not proposed. |
| D. Treat the owner credential plus a coordinator instruction as enough for implement-only work | Zero work | A credential is not consent, and a coordinator can be injected. Rejected. |

### Recommendation

A. Per-contract human approval stays; F3 cuts its cost to one host interaction.

### Exact changes (docs only)

`agent_contribute/instructions.md`, schema 0.2 authorization section. Add:

> **Local-only work.** When the user wants local implementation without
> publication, request only `implement`. An implement-only mandate authorizes
> commits on the reviewed `head_ref` in a local checkout. It does not authorize a
> push, PR, comment or any other GitHub write, and `draft_create_ready` stays
> false by design. Report the draft and completion blockers as expected, not as
> failures.
>
> **Coordinators.** A coordinator or orchestrator agent may forward the worker's
> `authorization-request` and the contract file to the human/host, and return the
> issued host context unchanged. It must not issue, edit, re-serialize or approve
> one, including by answering host permission prompts on the human's behalf. If
> no host can issue, stay pending and report the missing host capability.

`docs/host-authorization.md`: a new section, "Issuer requirements". These are
normative for any host issuer, including future Paseo and Claude Code integrations:

1. **Placement.** The issuer runs outside the worker's and the coordinator's tool
   channel. The worker can at most *request* issuance; the response comes only
   from a human gesture in host UI. No agent-callable API (MCP tool, plugin RPC,
   permission-response tool) can complete it.
2. **One snapshot for display, hash and binding** (RD-01). The host reads the
   contract bytes once and parses them with duplicate-key and nonfinite-number
   rejection, as `strict_json` does. From that single immutable snapshot it:
   - computes `contract_sha256`;
   - renders what the human sees;
   - derives the offered action subset (`execution.requested_actions`);
   - fills the mandate bindings.

   The human sees the **complete** contract through a renderer that treats it as
   data, with no Markdown or HTML interpretation and control characters made
   visible. That includes the objective, every behavior criterion, scope,
   constraints, prohibited changes, prerequisites with their evidence, and every
   validation `argv`. Worker or coordinator summaries, including any future
   request fields, are untrusted hints. They are never the approval view. If the
   host shows them at all, it rejects any that disagree with the snapshot. The
   request's `contract_sha256` is used only to flag a mismatch with the host's own
   hash, which aborts issuance.
3. **Generated fields.** `id` and `event.reference` are the host's durable
   approval-record ID. `nonce` is ≥128 bits from a CSPRNG, base64url, 24–200
   characters, and is included in the approval text the human sees.
   `issued_at` = now. `expires_at` should be no more than 8 hours for
   implement-only local work (the hard cap stays 24 hours). `event.text_sha256`
   hashes the exact retained approval text. `policy_review` records the human's
   decision on the pinned instruction and policy hashes.
4. **Retention.** The host keeps these outside the worker's writable roots:
   - the contract snapshot bytes;
   - the rendered approval view and the exact approval text;
   - the mandate hash.

   It audits `verify`'s echoed `contract_sha256` and `mandate_sha256` against
   them.
5. **Status registry and action-time checks** (RD-05, RD-07). The host keeps a
   status per `mandate_sha256`: `active`, `revoked` or `superseded`. Expiry is
   not a status; it is the mandate's own `expires_at`. Revocation removes a
   record's authority entirely; expiry ends only its permission for **new**
   actions. The host checks status **whenever it consumes authority, not only
   when it issues**:
   - **New actions** (implementation, the authorized push, draft creation)
     require `active` **and** unexpired. The verifier enforces expiry too: its
     implementation and draft gates need a current mandate.
   - **Historical recognition and completion** (an already published draft and
     final completion with a separate current `final_signoff`) require only that
     the original mandate is not `revoked` or `superseded`. An expired original
     mandate **may** be delivered and audited for this. It is the only record
     that can authenticate that the PR was created inside its interval, so the
     host never substitutes a fresh mandate for it; a mandate issued after
     publication fails `Pull request was created outside the publication mandate
     interval`. All existing live, evidence and sign-off checks still apply.
   - Before acting on, or forwarding to a coordinator, any `verify` result: a
     result echoing a `revoked` or `superseded` `mandate_sha256` is void,
     whatever the gates say. A result from an expired mandate is honored only for
     the recognition and completion facts above, never as new-action
     permission.

   A replacement mandate for the same contract is issued only after the previous
   one is marked `revoked` or `superseded`. Revoking an implement-only mandate
   also stops the worker's session for that contract (cancel the agent or remove
   its worktree access). The stateless CLI cannot stop a worker from reusing a
   copy it already holds, so this is the host's only effective lever.
6. **What is single-use.** Repeatable under an `active`, unexpired mandate:
   `verify` runs at any stage, local implementation and local validation.
   Repeatable under any non-revoked, non-superseded mandate, expired or not:
   `verify` runs for recognition and completion. Single-use per mandate, enforced
   by the host: draft creation (one PR) and consumption of a final sign-off.
   Replaying a consumed record, or a `revoked` or `superseded` record for any
   purpose, is refused.
7. **Delivery.** Through stdin from a host-controlled file, issued before the
   verifier starts (unchanged).

Per host, kept as notes because these are integration work outside this
repository (#23):

- Paseo: a trusted local plugin could own the request queue and the approval UI.
  Its approval path must reject agent-originated permission responses.
- Claude Code: until there is a native path, the human issues from a separate
  terminal using the documented hash recipe. Whether hooks can offer a
  human-only gesture must be verified against Claude Code's documentation when
  that integration is designed.

Update `docs/development-status.md` under #23 so that "issuer requirements are
specified; no native issuer ships".

### Backward compatibility

None needed. This is a usage profile of host-context 0.1 that `verify` already
accepts.

### Test plan

1. Regression pins for profile semantics that already exist:
   - an implement-only mandate gives `implementation_ready: true`,
     `draft_create_ready: false` and `next_action: implement`;
   - the draft-stage exit code is 1;
   - adding a `publication` claim does not make `draft_create_ready` true.
2. An implement-only mandate whose `actions` exceed `requested_actions` is still
   rejected; one equal to `requested_actions: ["implement"]` is accepted.
3. Workflow-resource test: the text forbids coordinator issuance and approving on
   the human's behalf, and defines local-only as implement-only.
4. The host-issuer requirements carry no code tests here. They become the
   acceptance checklist for the out-of-repository issuer (#23), and these issuer
   negative tests are mandatory there:
   - a correct contract hash paired with a forged or stale summary: issuance
     aborts, or the summary is ignored and the full snapshot is shown;
   - two contracts with the same validation ID but different `argv`: the approval
     views differ, and the `argv` is visible;
   - a request hash that differs from the host's own: issuance aborts;
   - an unexpired mandate replayed after revocation and replacement: delivery is
     refused and any `verify` result echoing it is void;
   - a second draft creation under one mandate is refused;
   - the post-expiry journey (RD-07). The mandate expires after a timely draft
     creation. The expired original mandate is still delivered, `verify` reports
     `publication.verified: true`, and with a current separate sign-off
     `completion_ready: true`. Implementation and draft creation stay refused.
     The host never replaces the original with a freshly issued mandate;
   - an approval arriving through an agent-callable API is rejected.

   An independent reviewer checks them when the issuer ships.

### Out of scope

Any issuer implementation in this repository; standing delegation (Option C,
escalate to Niko if per-task approval proves too costly); cryptographic
human-presence proof; bot or installation credentials.

---

## F1: stacked and unpublished bases

### Problem

Contracts pin the GitHub default branch: `source.commit` and
`instructions_sha256`. Schema 0.2 evidence must use a base in default-branch
history. Work stacked on unpublished commits therefore either:

- uses the unpublished base, and GitHub cannot authenticate it; or
- uses the published base, and every unpublished commit lands in the scope diff.

Either way it can never be technically valid. In addition, the instructions the
worker actually follows (the checkout's) are not the ones pinned.

### Threat model

A local base is worker-controlled data. The vectors are:

1. **Scope laundering.** Out-of-scope edits are committed into a "base", so the
   `base..HEAD` diff looks in scope.
2. **Instruction laundering.** A base commit edits `AGENTS.md`/`CONTRIBUTING.md` to
   relax requirements or to claim authority ("agents may push").
3. **Publication smuggling.** Unpublished, unreviewed commits ride along in a PR
   against the default branch.
4. **Base substitution** after approval.
5. **Downgrade or mixing.** A local-base mandate is reused without its pin, or a
   pin is applied to a different contract.
6. **Hostile Git state.** Replace objects, grafts, shallow history, symlinked or
   oversized instruction files.
7. **Untrusted issue text** ("build on branch X").

### Options

| Option | Pros | Cons |
| --- | --- | --- |
| A. Scope out stacked bases and document the procedure | No new surface; honest | The dogfood loop cannot reach `technical_evidence_valid` |
| B. Host-context 0.2 local-base mandate: the human pins the base commit; implement-only by schema; evidence base must equal the pin | Vectors 3–5 and 7 close cleanly (schema, SHA, mandate hash) | Vectors 1 and 2 close only if the human actually reviews the full source-to-base diff and instruction contents. No host can show that today, and a path inventory is not a review (RD-02). Needs a raw-byte Git read path (RD-03) and an implementation-time checkout binding (RD-04). Useless until an issuer exists. |
| C. A published non-default base branch (`base_ref` ≠ default; read instructions and compare at that ref) | GitHub-verifiable; stacked PRs could be published | The owner must push the base. Instruction and approval sources split across refs; a non-default PR target; draft-update interplay (#21). A larger trust change that needs its own design. |
| D. Trust `evidence.base_commit` when local ancestry holds | Trivial | Vector 1 directly: the worker chooses the base. Rejected. |

### Recommendation

A only. B is **not specified** in this design (revision 1 specified it; the review
showed that its central closure claim rested on review material that cannot
establish a review). It is recorded below as a future direction with explicit
preconditions. C stays out of scope.

### A: exact workflow changes (now)

Add to `instructions.md`, schema 0.2 implementation section:

> **Stacked or unpublished bases.** Schema 0.2 evidence requires the evidence base
> in the source default branch's GitHub history. Work stacked on unpublished
> commits cannot reach `technical_evidence_valid` in this version. Before
> requesting a mandate, tell the human. Do not encode this as a prerequisite:
> prerequisites gate implementation, and this is an evidence-stage fact. Record
> it as a constraint naming the stacked base by its full SHA, and in the ledger.
> The human then sees the base as part of the complete contract they approve.
> That constraint is not verifier-enforced. Start the branch from exactly that
> commit. For local-only work under an implement-only mandate:
> - use `scope-check --repo-dir checkout --base <full stacked-base SHA>` for
>   early scope feedback;
> - record the evidence honestly;
> - report `technical_evidence_valid: false` with its actual error;
> - never claim it.
>
> The checkout's instructions at the stacked base also apply. Ledger them with
> their own revision, as the ledger section already requires for differing
> revisions.
>
> To publish or validate later: wait until the base lands on the default branch,
> run `prepare` again (new `source.commit` and instruction hashes), carry the
> reviewed fields over by hand, review, and obtain a new mandate. Rebase the head
> onto a default-branch commit that contains the base, re-run every validation,
> regenerate the evidence, and obtain a new independent review. Old evidence,
> review and mandate do not transfer. This holds whatever the landing method;
> after a squash or rebase landing the old commit IDs no longer exist upstream.

`docs/host-authorization.md` and README "Current limits": one line saying that
stacked or unpublished bases are unsupported for technical evidence, with a link
to the procedure.

### Future direction: a local-base mandate (not specified)

A later design may let the human pin an unpublished base in a mandate. It must
not be specified or built until all of these hold. They come from the review of
revision 1:

1. **A real base review** (RD-02). A trusted host retrieves the complete
   `source.commit..base` diff and the full applicable instruction contents from
   the exact pinned Git objects, and presents them for an explicit base-review
   decision. If a limit truncates the material, issuance stops until the
   remainder is reviewed and that continuation is recorded. The host retains what
   was reviewed. Path counts and lists are navigation aids only. A benign base and
   a base that disables a check inside the same file have identical path
   inventories.
2. **A raw-byte object read** (RD-03). `core.git_read` decodes text-mode output and
   `strip()`s it (`core.py:631-643`), which alters final newlines, leading
   whitespace and CRLF. Instruction hashing needs a separate raw-byte path:
   - with the same environment, hook, replace and graft protections;
   - with blob size checked (`cat-file -s`) before the bounded read;
   - with UTF-8 validated without normalization.

   Existing text-mode callers stay unchanged. It needs local/remote equality
   tests for final newlines, leading whitespace and CRLF.
3. **Checkout binding at the implementation gate** (RD-04). Before
   `implementation_ready`, and independently of evidence, the verifier checks:
   - the checkout's GitHub remote and the active branch equal the bound repository
     and `head_ref`;
   - the pinned base is an ancestor of `HEAD`;
   - divergent or dirty instruction files leave implementation unresolved.

   The workflow tells the worker to start from the pinned base. It needs
   sibling-HEAD, wrong-branch and wrong-remote counterexample tests.
4. **Host revocation and status enforcement** (RD-05), as in the F2 issuer
   requirements. Otherwise a revoked base B1 can be replayed after the human
   approves B2 for the same contract.
5. **Rules already established in revision 1 that still apply:**
   - implement-only and no publication or sign-off sections, enforced by schema;
   - exact evidence base equality;
   - a new exact host-context version that leaves 0.1 untouched;
   - approval policy is never read from a local base.

Until then, stacked work follows A: land the base, then prepare again.

### Out of scope

Any local-base mandate (see the preconditions above), publishing stacked work
(Option C, a non-default `base_ref`), draft updates (#21), forks (#22), automatic
rebasing, and carrying evidence across the landing of a base.

---

## Compatibility matrix

No slice in this design changes a schema. Host-context 0.2 stays an unknown
version throughout, and fails closed (RD-06).

| Input | Before | After slices 1–4 |
| --- | --- | --- |
| Task 0.1, any evidence | old decisions | identical |
| Task 0.2 plus host-context 0.1 | current decisions | identical (`route_errors` refactor golden-pinned) |
| Task 0.2 plus host-context 0.2 or any other version | unknown version, fail closed | unknown version, fail closed |
| Task 0.1 plus any host context | rejected | rejected |
| `authorization-request` | n/a | 0.2 tasks only; host-context 0.1 bindings only |

## Ordered implementation slices

Each slice is independently shippable, keeps all existing tests passing, and gets
its own hostile review. "Tonight" marks slices that depend on no pending host
feature.

1. **Workflow field mapping and route documentation (F6, F2 local-only profile and
   coordinator rules, F1-A).**
   - Changes `instructions.md`, `docs/host-authorization.md`, README limits and
     `development-status.md`.
   - The host-authorization text restates that the human sees the complete
     contract, never a summary (RD-01).
   - Tests: workflow-resource assertions, plus regression pins for prerequisite
     blocking, implement-only semantics and stacked-base evidence failing with
     today's message.
   - No code behavior change. **Safe tonight.**
2. **`route_errors` refactor.** A pure extraction from `authorization.check` with a
   golden equivalence test on `check` output. **Safe tonight**; it can be the
   first commit of slice 3.
3. **`authorization-request` command (F3).**
   - Read-only, stdout only, no display summary.
   - Ships with the full F3 test plan: the round-trip, the "request is not host
     context" test, and the RD-01 no-summary pin. Adds docs in `docs/cli.md`.
   - **Safe tonight.** It needs no host feature: a human issuing by hand from a
     separate terminal can use it today.
4. **Host-issuer requirements (F2)** in `docs/host-authorization.md`:
   - one-snapshot display, hash and binding;
   - the status registry and action-time checks;
   - single-use rules;
   - the mandatory issuer negative tests;
   - the #23 status update.

   Docs only; it is ordered after 3 because it references the request format.
   **Safe tonight as documentation.** The issuers it governs are host work outside
   this repository.

Not planned: the local-base mandate. Reopen it as a new design only when the
F1 preconditions hold, starting with a host that can present the full
source-to-base diff (RD-02).

## Open decisions for Niko

- Whether per-contract human approval is acceptable friction for coordinator-run
  local work, or whether standing delegation (F2 Option C) should get its own risk
  review. This design assumes per-contract approval.
- Whether "land the base first" (F1-A) is the permanent answer for stacked work,
  or whether a host diff-review capability should be planned so the local-base
  direction can be reopened.

## Review resolution

Review: `review-rd-sol.md` (GPT-6.1-Sol, high), against revision 1 (`7468f0c`):
`BLOCK`, C=0 H=1 M=4 L=1. Each finding was checked independently against the
code and the revision-1 text. All six are confirmed; none is disputed.

| ID | Severity | Verdict | Independent check | Change in revision 2 |
| --- | --- | --- | --- | --- |
| RD-01 | High | Confirmed | The revision-1 F2 "Material" item told the host to show the request's `review_material`, which was neither bound nor complete (validation IDs only). The reviewer's probe shows two contracts differing only in `argv` with identical summaries, the changed one reaching `implementation_ready: true`. This matches the text and lifecycle code. | `review_material` removed from the request. Issuer requirement 2 now demands one parsed snapshot for hash, display and bindings, a complete data-rendered contract including every `argv`, summaries treated as untrusted hints, and abort on hash mismatch. Mandatory issuer negative tests added. The F3 threat model is corrected: the fail-closed guarantee covers bindings only. |
| RD-02 | Medium | Confirmed | A path inventory cannot distinguish a benign edit from a disabled check in the same file. The revision-1 closure table claimed otherwise. | The F1-B specification is removed. F1 recommends A only. A full diff and instruction review by a trusted host is now precondition 1 for any future local-base design. |
| RD-03 | Medium | Confirmed | `core.git_read` uses `text=True` and returns `stdout.strip()` for non-`-z` calls (`core.py:640-643`), so `cat-file blob` output cannot reproduce the remote byte hash. | Recorded as precondition 2: a separate raw-byte, size-checked read path; text-mode callers unchanged; newline, whitespace and CRLF equality tests. |
| RD-04 | Medium | Confirmed | `check_evidence` (remote, branch and ancestry checks) runs only when evidence is supplied (`lifecycle.py:205-211`), and the revision-1 implementation-gate checks did not tie the base to `HEAD`, the branch or the remote. | Recorded as precondition 3. For F1-A, the stacked base is now named by full SHA in a constraint that the human sees in the full contract, with an explicit note that it is not verifier-enforced. |
| RD-05 | Medium | Confirmed | `authorization.check` has no revocation or consumption input, and the same record authorizes on every call, as the probe shows. Revision 1 governed only issuance. | New issuer requirements 5–6: status per mandate hash, checked at delivery, at host actions and when acting on a `verify` result; replacement only after revocation; revocation stops the worker session; single-use versus repeatable operations listed; a replay negative test. The CLI stays stateless. |
| RD-06 | Low | Confirmed | The matrix's "After slice 4" column showed 0.2 support that only slice 5 would have added. | Moot after the F1-B removal. The matrix now has one "After slices 1–4" column, with host-context 0.2 rejected throughout. |

The review's other notes are preserved:

- F1-A forbids carrying stale evidence and now names squash/rebase landings.
- F6 remains a self-attested convention and is never presented as
  verifier-enforced.
- The acknowledged same-credential forgery non-goal is unchanged.

### Round 2 (revision 3)

Round 2 against revision 2 (`34fe062`): RD-01 to RD-06 were closed. Three new
findings came back as `BLOCK`, C=0 H=0 M=2 L=1. All three are confirmed; none is
disputed.

| ID | Severity | Verdict | Independent check | Change in revision 3 |
| --- | --- | --- | --- | --- |
| RD-07 | Medium | Confirmed | `lifecycle.verify` deliberately recognizes a draft created inside an expired mandate's interval. `pr_identity` rejects a PR created outside the bound interval, so a fresh mandate cannot replace the original, and the existing test `test_real_expired_publication_is_observed_without_new_action` pins that behavior. Revision 2's active-only rule voided this journey. | Expiry is no longer a status. New actions need `active` and unexpired. Recognition and completion need only not-revoked and not-superseded, and the expired original may be delivered for them. A fresh mandate never replaces it. Mandatory host test for the post-expiry journey added. Revocation checks are kept. |
| RD-08 | Medium | Confirmed | `lifecycle.verify` returns early with an empty `stage_blockers` on schema errors, and route checks index fields directly. A literal flow gives `KeyError`, and the CLI wrapper catches only `ProtocolError`, `OSError`, `UnicodeError`, `ValueError` and `RecursionError`. A failed permission read leaves `credential_actor_id` as an extra `null` leaf. | Step 1a: full schema validation first, then an `invalid_contract` error with no template and no GETs. Ready and blocked null-leaf invariants are defined, with an `unresolved_fields` list that is never human-fillable. Tests for invalid contracts and the blocked invariant added. |
| RD-09 | Low | Confirmed | Snapshot errors embed `safe_text(path)` for unreadable instruction files (`core.py:318-320`). `verify` forwards them into implementation blockers. | Diagnostics are explicitly permitted as sanitized untrusted text, labelled `preflight_errors_trust` and kept out of the approval view. `verify` is unchanged. Test with an adversarially named unreadable instruction added. |

