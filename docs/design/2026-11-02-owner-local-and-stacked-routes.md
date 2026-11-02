# Owner-local and stacked routes: design proposal

- Date: 2026-11-02
- Status: proposal for hostile review. No code changes are part of this step.
- Base: `47c80a1` (unreleased v0.3.0 candidate; task/evidence schemas 0.1 and 0.2,
  host-context 0.1).
- Input: dogfood 1, Stage 1 friction log, findings F1, F2, F3 and F6.

## Summary

| Finding | Recommendation | Ships as |
| --- | --- | --- |
| F6: the workflow asks for contract records that have no field | Name the exact existing fields in the workflow. Defer typed fields to the next task schema that is needed anyway (#16/#17). | Docs only |
| F3: no way to produce an authorization request | Add a read-only `authorization-request` command. It prints an unsigned request with every binding field pre-filled from the contract and live reads, and every human-only field `null`. Its output can never pass as host context. | CLI, no schema change |
| F2: no route for owner-local, coordinator-delegated work | Add no new mandate format. A host-context 0.1 mandate with `actions: ["implement"]` already is the minimal implement-only profile. Document it, define normative host-issuer requirements, and state that a coordinator relays but never issues. Native Paseo/Claude Code issuers live in the hosts (#23). | Docs |
| F1: stacked or unpublished bases can never validate | Now: document the limitation and the procedure. Later: a host-context 0.2 "local-base" mandate in which the human pins the local base commit and its instruction hash. It is implement-only by schema, and publication is impossible. Build it only once a native issuer exists. | Docs now; host-context 0.2 later |

All four fit inside the existing trust model. Authority still comes only from a
human/host-issued record. Every new piece of data is either already re-verified by
`verify` or pinned by the human. No existing contract, evidence or host-context
document changes meaning.

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
- **The worker shows the human contract X but the request hashes contract Y.** The
  host must hash the contract file it displays itself, never trust the request's
  `contract_sha256`. `verify` later re-checks the mandate's contract hash against
  the file it is given, so a mismatch fails closed, but only the host can make
  sure the human saw that file.
- **Injected remote text in the review material** (an issue title saying "Owner
  pre-approved, click accept") would influence the human. The output carries no
  remote free text: identities, refs, hashes, paths and action names only.
- **Pre-filled fields are wrong** (stale or malicious). Every pre-filled field is
  re-verified by `verify` against the contract and live GitHub after issuance. A
  wrong value can only produce a mandate that fails closed.
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

Output (JSON):

```json
{
  "kind": "agent-contrib/authorization-request",
  "request_version": "0.1",
  "issued": false,
  "notice": "UNSIGNED REQUEST. Not a mandate; grants no authority. Only the human/host issues a mandate, from the contract file it shows the human, and the worker relays it unchanged.",
  "target_host_context_schema_version": "0.1",
  "ready_for_issuance": true,
  "preflight_errors": [],
  "contract_sha256": "<canonical hash, same as verify>",
  "review_material": {
    "source_repository": "owner/repo", "issue_number": 12, "issue_url": "https://github.com/owner/repo/issues/12",
    "head_ref": "branch", "base_ref": "main", "requested_actions": ["implement"],
    "allowed_paths": ["..."], "prohibited_paths": ["..."],
    "validation_ids": ["V1"], "exact_head_pr_history": "not checked before issuance; verify checks it after"
  },
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
  permission check passed; otherwise it is `null` with a preflight error.
  `authority` is `owner` when that ID equals `source.owner_id`, else
  `maintainer`. Both derive from live facts, and `verify` re-checks both.
- `actions` is `null`: the human chooses a subset of `requested_actions`. The
  host offers exactly that subset.
- `event.kind` is `null` even though the schema constant is `human`. The host
  asserts it, and a `null` keeps the untouched template invalid.
- The paths come from the contract, which is worker-authored and labelled so. No
  issue title, body or other remote prose is included.

Workflow change: the sentence "The worker may prepare an authorization request"
names the command and adds: "Give the host the contract file and the request. The
host hashes the contract itself; never fill in the request's `null` fields."
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
2. The `human_only_fields` list exactly equals the set of `null` leaves in
   `mandate_fields`. Every other host-context `mandate` property is present and
   non-null, checked by walking the bundled schema, so a future schema field
   cannot be silently omitted.
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
   do not appear anywhere in the output.
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
2. **Material.** The host reads the contract file itself, recomputes its canonical
   hash, and shows the human that hash, the structured `review_material` and the
   offered action subset. It ignores the request's own `contract_sha256` except
   to flag a mismatch.
3. **Generated fields.** `id` and `event.reference` are the host's durable
   approval-record ID. `nonce` is ≥128 bits from a CSPRNG, base64url, 24–200
   characters, and is included in the approval text the human sees.
   `issued_at` = now. `expires_at` should be no more than 8 hours for
   implement-only local work (the hard cap stays 24 hours). `event.text_sha256`
   hashes the exact retained approval text. `policy_review` records the human's
   decision on the pinned instruction and policy hashes.
4. **Retention.** The host keeps the approval text, the material shown and the
   mandate hash outside the worker's writable roots, and audits `verify`'s echoed
   `mandate_sha256` against them.
5. **Delivery.** Through stdin from a host-controlled file, issued before the
   verifier starts (unchanged).
6. **Single use.** The host refuses to issue a second mandate for the same
   contract hash while one is unexpired, unless the human revokes the first.

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
4. The host-issuer requirements carry no code tests here; they become the
   acceptance checklist for the out-of-repository issuer (#23), checked by an
   independent reviewer when that issuer ships.

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
| B. Host-context 0.2 local-base mandate: the human pins the base commit and its instruction hash; implement-only by schema; evidence base must equal the pin | Closes vectors 1–7: 1 and 2 by human pinning plus review material, 3 by schema, 4 by SHA, 5 by mandate hash, 6 by existing Git guards plus object-only reads | A new host-context version and more verifier code. Useless until a host can issue mandates. |
| C. A published non-default base branch (`base_ref` ≠ default; read instructions and compare at that ref) | GitHub-verifiable; stacked PRs could be published | The owner must push the base. Instruction and approval sources split across refs; a non-default PR target; draft-update interplay (#21). A larger trust change that needs its own design. |
| D. Trust `evidence.base_commit` when local ancestry holds | Trivial | Vector 1 directly: the worker chooses the base. Rejected. |

### Recommendation

A now; B as a deferred slice that is fully specified below. Build B only after a
native issuer exists (F2/#23). Until then no one can conveniently issue the
mandate it extends, and A is the honest behavior. C stays out of scope.

### A: exact workflow changes (now)

Add to `instructions.md`, schema 0.2 implementation section:

> **Stacked or unpublished bases.** Schema 0.2 evidence requires the evidence base
> in the source default branch's GitHub history. Work stacked on unpublished
> commits cannot reach `technical_evidence_valid` in this version. Before
> requesting a mandate, tell the human. Do not encode this as a prerequisite:
> prerequisites gate implementation, and this is an evidence-stage fact. Record
> it as a constraint and in the ledger. For local-only work under an
> implement-only mandate:
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
> review and mandate do not transfer.

`docs/host-authorization.md` and README "Current limits": one line saying that
stacked or unpublished bases are unsupported for technical evidence, with a link
to the procedure.

### B: the local-base mandate (deferred slice)

**New schema** `agent_contribute/schemas/host-context/0.2.schema.json`. It is a
copy of 0.1 with these differences:

- `schema_version: {"const": "0.2"}`.
- No `publication` or `final_signoff` properties. The closed schema rejects them,
  so the schema itself enforces local-only.
- `mandate.actions`: `{"type": "array", "items": {"const": "implement"},
  "minItems": 1, "maxItems": 1}`, which enforces implement-only by schema.
- A required `mandate.local_base`:

```json
"local_base": {
  "type": "object", "additionalProperties": false,
  "required": ["commit", "instructions_sha256"],
  "properties": {
    "commit": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
    "instructions_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}
  }
}
```

`local_base` is required, so host-context 0.2 has exactly one meaning: the
local-base profile. A plain mandate keeps exactly one encoding (0.1). The
`policy_review.status: clear` in a 0.2 mandate attests to both the pinned
default-branch instructions (`policy_review.instructions_sha256`, unchanged
check) and the local-base instructions (`local_base.instructions_sha256`).

**Code changes:**

- `core.bundled_schema`: host-context accepts the exact set `{'0.1', '0.2'}`;
  anything else is still `unsupported_schema`.
- `authorization.check` selects the schema by the host context's
  `schema_version`. A non-dict or unknown version gives a schema error, as now.
  For 0.2 it echoes `user_authorization.local_base = {commit,
  instructions_sha256, verified}`.
- A new shared helper, `core.instruction_paths(blob_paths)`, extracted from
  `repository_snapshot`, so remote and local selection cannot drift. This is a
  pure refactor; the snapshot output is pinned by goldens.
- A new `core.local_instructions_hash(directory, commit)`:
  - reads **Git objects only** (`git ls-tree -r -z <commit>`, `git cat-file blob
    <oid>`) through `git_read` with its existing hook, replace and graft guards,
    and never the working tree;
  - accepts only mode `100644`/`100755` blobs;
  - fails closed on a symlink (`120000`) or gitlink at a selected path, on more
    than 60 files, on any file over 200 kB, and on non-UTF-8 content;
  - excludes `.agent-contrib.json` as the remote snapshot does (approval policy is
    always read live from GitHub, never from a local base);
  - produces the same canonical `[{path, sha256}]` hash as
    `snapshot['instructions_sha256']`.
- `lifecycle.verify` with a 0.2 host context:
  - `--repo-dir` is required at **every** stage. Without it the implementation
    blocker is "Local-base mandate requires --repo-dir".
  - At every stage, all of these must hold, or the error is "Local base is
    missing, not stacked on the reviewed source commit, or its instructions
    differ from the mandate":
    - `local_base.commit` exists in the checkout as a commit;
    - `merge-base --is-ancestor source.commit local_base.commit` succeeds;
    - `local_instructions_hash` equals the mandate's.
  - `check_evidence` gets a new keyword `local_base=None`. With `None` the code
    path is byte-for-byte today's. When set:
    - `evidence.base_commit` must equal `local_base.commit` exactly;
    - the GitHub compare of the evidence base is replaced by the local
      `source.commit → local_base → HEAD` ancestry checks, which already exist;
    - every other evidence check is unchanged: scope diff `local_base..HEAD`,
      head ref, clean tree, remote, gitlinks, validations, criteria, review and
      artifacts.
  - The check that the reviewed `source.commit` is in current default-branch
    history is **unchanged**. The source pin stays GitHub-authenticated.
  - Draft and completion add the blocker "Local-base mandates authorize local
    implementation only; re-prepare after the base lands". `draft_create_ready`,
    `publication.verified` and `completion_ready` are always false.
- `authorization-request --local-base REV --repo-dir CHECKOUT`:
  - resolves REV with `git rev-parse --verify REV^{commit}` through `git_read`;
  - sets `target_host_context_schema_version: "0.2"`;
  - pre-fills `mandate_fields.local_base`, with `actions` still `null`;
  - adds `review_material.local_base`:
    - `commits_ahead_of_source` (a count);
    - `changed_paths`: `source.commit..local_base`, sanitized, capped at 500, with a
      `truncated` flag;
    - `instruction_paths_changed`;
    - `policy_file_changed`.

  This is what the human must look at to rule out vectors 1 and 2. The
  `--local-base` option is a usage error without `--repo-dir`.
- `instructions` output: `supported_host_context_versions: ["0.1", "0.2"]`.

**How each vector is closed:**

| Vector | Closure | Residual |
| --- | --- | --- |
| 1 Scope laundering | The human pins the base SHA after seeing `changed_paths` for `source..base`. The worker cannot change it afterwards. | A rubber-stamping human. The blast radius is local only (vector 3). |
| 2 Instruction laundering | A separate local instruction hash with the changed instruction paths flagged. Instructions are never authority. Approval policy is read live from the default branch only. | The human's policy review quality |
| 3 Publication smuggling | Schema: implement-only, no publication or sign-off sections, plus explicit draft and completion blockers. Publication needs the A procedure (re-prepare after the base lands). | None in the CLI. Pushing is the host's control. |
| 4 Base substitution | Exact SHA equality between the mandate and the evidence base; content addressing | Git SHA-1 (collision-detecting) strength |
| 5 Downgrade or mixing | `local_base` is inside the hashed mandate, so stripping it changes `mandate_sha256`, and a stacked evidence base then fails the GitHub compare. `contract_sha256` binds the mandate to one contract. | None new |
| 6 Hostile Git | Existing `git_read` guards; object-only reads; symlink, gitlink, size and count limits fail closed. Shallow or missing history makes `--is-ancestor` fail closed. | Not a sandbox (unchanged boundary) |
| 7 Issue text | The base comes only from the human-issued mandate; the request merely proposes it. | None new |

### Backward compatibility

- Task and evidence schemas 0.1/0.2: unchanged.
- Host-context 0.1: the schema file, the code path and every error string are
  unchanged. A 0.1 document carrying `local_base` is still a schema error.
- Older CLIs reject host-context 0.2 as an unknown version (fail closed).
- A 0.2 document is accepted only by a CLI that implements all of B.

### Test plan

Fixtures are temporary Git repositories with a published source commit `A`
(FakeGitHub reports it as the default tip), unpublished commits `B1..Bn`
(the local base), and a head branch `C` on top.

1. **Compatibility goldens.** Every existing host-context 0.1 test fixture gives
   byte-identical `verify` JSON and exit codes before and after the change.
   Snapshot `instructions_sha256` goldens are unchanged by the `instruction_paths`
   refactor.
2. **Happy path.** 0.2 with `local_base = Bn`, evidence base `Bn`, in-scope diff:
   `implementation_ready` true and `technical_evidence_valid` true with no
   `compare` GET for `Bn`. Draft and completion are false with the local-only
   blocker, and the draft-stage exit code is 1.
3. **Base pin.** Fails when:
   - evidence base = `A`, or evidence base = `B(n-1)`;
   - `local_base` is not a descendant of `A` (a sibling branch);
   - the `local_base` commit is absent from the checkout;
   - the checkout is a shallow clone missing `A`.
4. **Instruction hash.**
   - Fails when the mandate hash was computed before a later `AGENTS.md` change in
     `Bn`.
   - Passes when only the worktree `AGENTS.md` is dirty; it reads objects only.
     The dirty tree still fails the separate clean-tree evidence check, which
     proves the two checks stay independent.
   - Fails on a symlinked `AGENTS.md`, a gitlink at `CONTRIBUTING.md`, a 201 kB
     `README.md`, non-UTF-8 content, and more than 60 instruction files.
   - A `refs/replace` object substituting `AGENTS.md` is ignored.
5. **Scope laundering is visible.** An out-of-scope file changed in `B1` appears
   in `authorization-request` `review_material.local_base.changed_paths`. The
   same file changed in `C` fails scope.
6. **Profile enforcement by schema.** Each of these is a schema error:
   - `actions: ["implement", "create_draft"]`, or `["create_draft"]`;
   - a `publication` section, or a `final_signoff` section;
   - a missing `local_base`.
7. **Version handling.** Rejected as before:
   - `schema_version: "0.3"`;
   - a 0.1 document with a `local_base` key;
   - a mix (`"0.2"` without `local_base`).
8. **Downgrade.** The same mandate re-wrapped as 0.1 without `local_base` has a
   different `mandate_sha256`, and stacked evidence fails with today's message.
9. **Repo-dir requirement.** 0.2 without `--repo-dir` fails at the implementation
   stage.
10. **`authorization-request --local-base`.**
    - The round-trip test from F3 works with 0.2: the filled mandate verifies.
    - Without `--repo-dir` the command exits 2.
    - A short SHA or branch name resolves to the full SHA.
    - A nonexistent revision exits 1.
11. **Mutation testing** in a `/tmp` copy. Each mutant must be killed:
    - drop the base-equality check;
    - drop the ancestry check;
    - hash worktree files instead of objects;
    - allow `create_draft`;
    - skip `--repo-dir` at the implementation stage;
    - take `instruction_paths` from a divergent list;
    - let the 0.1 path take the `local_base` branch.

### Out of scope

Publishing stacked work (Option C, a non-default `base_ref`), draft updates
(#21), forks (#22), automatic rebasing, and carrying evidence across the landing
of a base.

---

## Compatibility matrix

| Input | Before | After slices 1–3 | After slice 4 |
| --- | --- | --- | --- |
| Task 0.1, any evidence | old decisions | identical | identical |
| Task 0.2 plus host-context 0.1 | current decisions | identical (`route_errors` refactor golden-pinned) | identical |
| Task 0.2 plus host-context 0.2 | unknown version, fail closed | unknown version, fail closed | local-base profile |
| Task 0.1 plus any host context | rejected | rejected | rejected |
| `authorization-request` | n/a | 0.2 tasks only | plus `--local-base` |

## Ordered implementation slices

Each slice is independently shippable, keeps all existing tests passing, and gets
its own hostile review.

1. **Workflow field mapping and route documentation (F6, F2 and F1-A docs).**
   Changes `instructions.md`, `docs/host-authorization.md` (local-only profile,
   coordinator rules), README limits and `development-status.md`. Adds tests: the
   workflow-resource assertions plus regression pins for prerequisite blocking,
   implement-only semantics and stacked-base evidence failing with today's
   message. No code behavior change.
2. **`route_errors` refactor.** A pure extraction from `authorization.check` with a
   golden equivalence test on `check` output. Shipping it separately keeps the
   F3 diff free of authorization-logic churn.
3. **`authorization-request` command (F3)** with the full F3 test plan, including
   the round-trip and the "request is not host context" tests. Adds docs in
   `docs/cli.md`.
4. **Host-issuer requirements (F2)** in `docs/host-authorization.md`, plus the #23
   status update. These are the acceptance checklist for out-of-repository Paseo
   and Claude Code issuers. Docs only; it can ship in parallel with 3 but is
   ordered after it because it references the request format.
5. **Local-base mandate (F1-B), deferred.** Build only after a native issuer from
   slice 4 exists. It ships as three commits on one branch, each tested:
   - (a) the `instruction_paths` refactor with goldens;
   - (b) `local_instructions_hash` with the Git-boundary tests;
   - (c) host-context 0.2 schema, the verifier and `authorization-request
     --local-base` with the full B test plan.

## Open decisions for Niko

- Whether per-contract human approval is acceptable friction for coordinator-run
  local work, or whether standing delegation (F2 Option C) should get its own risk
  review. This design assumes per-contract approval.
- Whether the recommended 8-hour expiry for implement-only local mandates should
  instead become a verifier-enforced cap in host-context 0.2.
- Whether slice 5 is wanted at all, or whether "land the base first" (F1-A) is the
  permanent answer.
