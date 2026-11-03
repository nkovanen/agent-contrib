# Human authorization and host handoff

Schema 0.2 supports one candidate task in the same source, head and target
repository. The base must be the source's default branch. A mandate does not
make the issue repository-approved. The CLI checks GitHub facts and consistency;
it cannot authenticate the person typing a message.

There is no automatic mandate issuer for Claude Code, Codex or Paseo in this
release. A human or trusted host must issue and retain the record outside the
contribution worker's control. The worker may relay it unchanged. Stdin, a JSON
file, a hash and an owner token are not proof of human consent. Do not present
this handoff as a security boundary against a hostile same-credential process.

## Stop at the real approval boundary

Before implementation, the worker presents:

- the issue, complete proposed scope, acceptance criteria and prohibited changes;
- the reviewed task JSON and its canonical SHA-256;
- the source/target/head repositories and numeric IDs, head ref and default base;
- the requested actions (`implement`, and optionally `create_draft`), validation
  commands, publication destination and independent review requirement;
- repository policy/instruction findings and their hashes, unresolved questions
  and any overlapping work.

The host shows the human the complete reviewed contract, rendered as data from
the same file it hashes, including every validation command, never a summary
written by the worker or a coordinator. The human approves that concrete scope
or requests changes. A previous request
to investigate, a coordinator message, an issue body, a self-authored contract or
successful tests cannot substitute for that decision. The worker stops if the
host cannot supply an actual record. The host keeps what the human was shown,
the exact approval text, an event reference and the issued hashes for later audit.

The current publishing credential must identify a personal GitHub account. Fresh
GETs check `/user`, repository/owner and issue identities, and the collaborator's
exact `admin` or `maintain` role. `authority: owner` additionally requires the
credential actor ID to equal the repository owner ID. Organization maintainers
use `maintainer`. Bots, delegated identities, custom roles, missing permissions
and mismatched identities fail closed. Enterprise-managed login forms containing
underscores are currently unsupported. Use canonical repository spelling from
discovery; case-variant schema 0.2 preparation can be refused conservatively. This verifies the credential, not the
human who supplied it.

## Local-only work

A mandate with `actions: ["implement"]` is the local-only profile: it authorizes
commits on the reviewed head ref in a local checkout and nothing on GitHub.
Draft readiness stays false by design. A coordinator agent may forward the
request and contract to the human/host and relay the issued record unchanged; it
never issues, edits or approves one, including through host permission prompts.

An unpublished commit cannot be the evidence base for schema 0.2 evidence,
because the base must be in the source default branch's history. With a
published base, the whole unpublished stack is part of the checked diff and must
belong to the approved contribution. To exclude a separate stacked dependency,
land it first, then prepare, authorize, validate and review again; see the
installed workflow.

## Three separately sourced records

The strict [host-context schema](../agent_contribute/schemas/host-context/0.1.schema.json)
is an object with `schema_version: "0.1"` and a required `mandate`. Optional
sections are omitted until available; `null` is not an absent section.
[Host-context 0.2](../agent_contribute/schemas/host-context/0.2.schema.json) has
the same sections, byte for byte, so a mandate's hash does not depend on the
wrapper. It adds an optional, host-issued `overlap_dispositions` record (#7).
It can waive only a topical overlap whose bound observations still hold (see
[overlap dispositions](#overlap-dispositions-host-context-02)). It also adds an
optional `draft_update` record (#21). This version only parses and
binding-checks that record and authorizes nothing with it (see
[draft update rounds](#draft-update-rounds-host-context-02)). Any other
version, or a 0.1 document carrying either section, fails closed.

| Section | Issuer and purpose |
| --- | --- |
| `mandate` | Human/host. Binds the contract, numeric repository/owner/issue/credential IDs, refs, exact actions, reviewed policies and actual approval event. |
| `publication` | Worker claim. Identifies a PR, head SHA and contract/mandate hashes. It grants no authority; GitHub identity and current state are checked live. |
| `final_signoff` | Human/host, after tests, independent review and publication. Binds the final head, contract, original mandate and independent-review record. |

Each human/host record has its own ID, random nonce, issue/expiry times and event.
A nonce must be 24–200 characters; use an unpredictable value from the host.
Retain the exact event text privately and hash its UTF-8 bytes without trimming
or newline conversion. Include the nonce in the material the human approves;
a guessable reply such as “yes” alone is not an adequate audit record.
`event.kind: human` is an assertion, not detection of message origin.

The mandate's `policy_review` is also human/host-issued. It records whether the
pinned repository instructions allow this work. The instruction digest comes
from the contract; the policy digest covers both policy content and its observed
state, including known absence. An absent policy or a valid policy without an
approval label leaves the issue a candidate and may use this route. An unreadable
or malformed policy blocks it. The CLI cannot interpret every prose prohibition;
the human/host must review those rules. Issue-open and exclusion-label checks are
also enforced by the verifier.

Times use RFC3339 with seconds, a known offset (`Z` or `±HH:MM`) and optional
1–6 fractional digits. An event interval must be positive, no more than 24 hours,
and not issued in the future. New actions require an unexpired mandate. An
existing authorized draft can still be recognized after expiry if its GitHub
creation timestamp was inside the interval and all current identity, evidence
and policy checks pass. Same-second timestamp precision can cause a safe refusal.

The initial mandate is not final sign-off. The later record needs a different
ID, nonce and event reference, the exact final head and the hash of
`evidence.independent_review`. Final sign-off must follow review and publication
and be current when completion is checked. Human sign-off is absent from evidence
schema 0.2; evidence alone cannot supply it.

## Host issuer requirements

These are normative for any host that issues mandates, including future Paseo
and Claude Code integrations. No issuer ships with this CLI: anything the worker
can invoke through its tools would be self-issuance.

1. **Placement.** Issuance completes only through a human gesture in host UI,
   outside the worker's and any coordinator's tool channel. No agent-callable
   API, such as an MCP tool, plugin RPC or permission-response tool, can complete
   it. The worker may only request issuance, for example with
   `agent-contrib authorization-request`.
2. **One snapshot.** The host reads the contract bytes once, parses them strictly
   (duplicate keys and nonfinite numbers rejected), and from that one parsed
   snapshot computes the contract hash, renders the complete contract as data
   (every criterion, scope entry, constraint, prerequisite and validation
   command, with control characters made visible), derives the offered actions
   and fills the bindings. Worker or coordinator summaries are untrusted hints,
   never the approval view. A request hash that differs from the host's own
   aborts issuance.
3. **Generated fields.** `id` and `event.reference` are the host's durable
   approval-record ID. `nonce` comes from a CSPRNG (at least 128 bits) and
   appears in the approval text. `issued_at` is now. Prefer `expires_at` no
   more than 8 hours ahead for implement-only work (the hard cap is 24 hours).
   `event.text_sha256` hashes the exact retained approval text.
   `policy_review` records the human's decision on the pinned hashes.
4. **Retention.** Keep the contract bytes, the rendered approval view, the
   approval text and the mandate hash outside the worker's writable roots, and
   audit the echoed `contract_sha256` and `mandate_sha256` against them.
5. **Status and action-time checks.** Keep a status per `mandate_sha256`:
   `active`, `revoked` or `superseded`. Expiry is not a status; it is the
   record's own `expires_at`, which ends permission for new actions only. Check
   status whenever authority is consumed, not only at issuance:
   - New actions (implementation, the authorized push, draft creation) need an
     `active`, unexpired mandate.
   - Recognizing a draft created inside the mandate interval, and completion with
     a separate current final sign-off, need only a mandate that is not
     `revoked` or `superseded`. An expired original may be delivered for this.
     It is the only record that can show the PR was created inside its interval,
     so the host never substitutes a fresh mandate for it.
   - A `verify` result echoing a `revoked` or `superseded` mandate hash is void,
     whatever the gates say. A result from an expired mandate counts only for
     recognition and completion.
   - Issue a replacement for the same contract only after marking the previous
     record `revoked` or `superseded`. Revoking an implement-only mandate also
     stops the worker's session for that contract; the stateless CLI cannot stop
     a worker from reusing a copy it already holds.
6. **What repeats.** Repeatable under an `active`, unexpired mandate: `verify`
   at any stage, local implementation and validation. Repeatable under any
   non-revoked, non-superseded mandate: recognition and completion checks.
   Single-use per mandate, enforced by the host: draft creation and consumption
   of a final sign-off.
7. **Delivery.** Through stdin from a host-controlled file, issued before the
   verifier starts.

Mandatory issuer tests, checked by an independent reviewer when an issuer ships:
a correct contract hash paired with a forged or stale summary; two contracts with
the same validation ID and different commands; a request hash mismatch; replay of
an unexpired mandate after revocation and replacement; a second draft creation;
an approval arriving through an agent-callable API; and the post-expiry journey,
where a timely draft created under the original mandate is still recognized and
completed with a current sign-off while new actions stay refused.

## Draft update rounds (host-context 0.2)

A `draft_update` record (#21) opens one update round for a recognized draft. It
is bound to the contract, the unchanged original mandate, the credential actor,
the repository, the claimed PR's number and ID, and `from_head`: the live head
the human saw. It has its own ID, nonce, interval (at most 24 hours) and event
binding. Its ID, nonce and event reference must differ from those of the
mandate, the final sign-off and any overlap dispositions.

**This version is inert.** `verify` reports the record as
`draft_update.status: not_evaluated` (bindings valid) or `invalid`. It never
changes a gate, blocker, `next_action`, exit status or GitHub read, and
`candidate_head` is always `null`. Hosts must not issue rounds as publication
authority until a version evaluates them.

Hosts that will issue rounds follow these requirements, from the
[design](design/2026-11-02-draft-updates.md#host-lifecycle-normative-issuer-requirements-for-draft_update):

1. **Status** per record hash: `active`, `reserved(F→E)`, `consumed`,
   `revoked` or `superseded`. Expiry ends permission for new actions only.
2. **One current-round pointer** per (contract, mandate, PR). Only the record it
   points to is operative for any gate. A `superseded` record is archival only.
   Opening a round supersedes the previous one and voids any unconsumed final
   sign-off for the previous head. Only the host moves the pointer.
3. **One push per round, under an exclusive durable reservation.**
   - Before any remote operation, record `reserved(F→E)` under a lock keyed to
     the round. `E` is the `candidate_head` of a `verify` result the host
     produced itself; it is never reread from worker-controlled files.
   - Re-prove `F → E` (ancestor, distinct, no merge commits).
   - Push exactly `E` with a lease on `F`.
   - Fail closed on uncertain outcomes and reconcile from the live head. A
     reservation never returns to `active` or admits another head.
   - Every submission, including a retry, needs the original deadline, the
     current pointer and non-revocation.
4. **Final sign-off** follows an observed recognition of exactly `E` under the
   current, consumed round.
5. **Audit** against the retained exact chain `A`, then each consumed round's
   `F → E`. The live head must equal the last retained `E`.

## Overlap dispositions (host-context 0.2)

A host may issue an `overlap_dispositions` record (#7) saying that a specific
**topical** overlap between this contract's issue and one open PR is
`unrelated`. The record never covers an explicit reference to the issue, an
incomplete open-PR scan, a closed PR, or the agent's own work. It is a separate
human event with its own ID, nonce, interval (at most 24 hours) and event
binding, bound to the contract hash, the mandate hash and the credential actor.
Requirements 1, 3, 4, 5 and 7 above apply to it unchanged; it is repeatable
while it is not revoked or superseded.

Before issuing, the host:

1. Reads the PR itself (`GET repos/{source}/pulls/{n}`) and renders its title,
   body, head and base refs, state, draft flag, author and the match reason as
   data. It never uses a worker or coordinator summary.
2. Resolves the base-branch tip independently with
   `GET repos/{source}/git/ref/heads/{base.ref}`, never the PR's `base.sha`,
   which can lag the tip. This is `base_tip_sha`.
3. Fetches `compare/{base_tip_sha}...{head_sha}` for the PR's current head and
   shows the human the complete file list and every patch. The merge base is
   the response's `merge_base_commit.sha`. A mutable diff link is not enough.
4. Retains the exact material it showed: the canonical JSON of the comparison's `files`
   items, in response order, each with exactly `filename`, `previous_filename`,
   `status`, `sha` and `patch` (or `null`). It records the SHA-256 of those
   bytes as `material_sha256`, then retains the approval text and the record
   hash outside the worker's writable roots.
5. Computes every bound field from its own reads, sets
   `comparison.head_sha` to the bound head, and records the human's rationale.

The host refuses to issue when:

- the comparison is unavailable, or reports 300 files (GitHub's cap);
- any changed file has no reviewable textual patch: binary files of every kind,
  patches GitHub omits as too large, and source GitHub classifies as binary;
- the PR is authored by the credential actor (this also refuses that account's
  earlier human PRs);
- the PR contains an explicit reference to the issue, or the human saw only an
  incomplete open-PR scan.

Re-issuing after any change to the PR or the base-branch tip is a new human
event. `verify` re-reads every disposed PR and each base-branch tip, and waives
an overlap only when every bound observation is still equal. Its result echoes
the record hash for audit.

Mandatory issuer tests:

- a correct contract hash paired with a forged or stale summary;
- a PR edited between review and issuance;
- a truthful API response whose description misleads about its code;
- a branch pushed while the human reviews (the record binds the reviewed head);
- a saturated or truncated comparison (must not issue);
- a PR whose `base.sha` differs from the base-branch tip (the host binds the tip
  it resolved);
- a binary executable or WebAssembly module (must not issue);
- a source file GitHub reports without a patch (must not issue);
- a mixed PR with reviewable text and one patchless file (must not issue);
- replay of a revoked or superseded disposition;
- an approval arriving through an agent-callable API.

## Reproduce hashes independently

Use the same recipe for a task, a complete mandate, a complete final sign-off,
and the independent-review object. Whitespace in JSON is immaterial; strings,
numbers and arrays are not normalized. Reject duplicate object keys and nonfinite
numbers before hashing. The human/host should calculate and keep the digests
independently of the worker.

```python
import copy
import hashlib
import json


def canonical_sha256(value):
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False,
                         allow_nan=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def event_binding_sha256(record):
    bound = copy.deepcopy(record)
    bound["event"].pop("binding_sha256", None)
    return canonical_sha256(bound)
```

For an already human/host-issued section, first calculate its event binding with
only `event.binding_sha256` omitted. Store that digest in the issued section,
then calculate the complete section's canonical hash. This recipe binds an
actual decision; it is not a command for the worker to invent one.

The result's `mandate_sha256` covers **only the complete mandate section**, never
the whole host context. Adding a publication claim or final sign-off must leave
it unchanged. `final_signoff_sha256` covers the complete later section. Compare
both echoed hashes and event references with the human/host's retained records.
A matching worker-written copy alone proves nothing about who issued it.

## Deliver and verify

After issuance, the host supplies the document explicitly. For example, from a
host-controlled location, outside the checkout:

```sh
agent-contrib verify task.json --stage implementation \
  --host-context-stdin < /host-controlled/context.json
```

Issue the record before starting the verifier: a pipeline that waits for a human
to decide will exceed the five-second input deadline.

The path above is illustrative, not an automatic discovery convention. The CLI
accepts a bounded UTF-8 JSON stream, not a path option. No input is read implicitly.
Record the actual exit code and all returned gates; an exit code is not a new
permission grant. Library callers have the same explicit host-asserted boundary.

After implementation, commit and run validations on the exact clean HEAD, then
obtain independent review. With evidence:

```sh
agent-contrib verify task.json --evidence evidence.json --repo-dir checkout \
  --stage draft --host-context-stdin < /host-controlled/context.json
```

Draft creation requires both `implement` and `create_draft`, current authority,
valid evidence/review, complete reads, no overlap and no exact-head PR history.
The host performs the authorized push and one draft creation; the CLI has no
write operation. Afterward the worker may add the `publication` claim, keeping
the mandate unchanged. Repeat verification at the exact tested head. Only that
PR's repository, number and URL are removed from post-publication overlaps.
Every unrelated match still blocks. A verified draft returns `next_action: none`;
it does not authorize a second PR.

Final completion uses the same inputs with `--stage completion` after the human
issues the later sign-off. Draft readiness can pass while completion stays false.
Do not update or reopen a recognized PR through this route; a moved head fails
against the original evidence and publication claim.
Current open/draft state is checked, but historical close-and-reopen events are
not fully reconstructed. GitHub reads are separate snapshots, so reverify after
publication and treat races as unresolved. Mandate single use and the actual
human event are host responsibilities, not guarantees from a stateless CLI.

Verification compares the PR's current head with the evidence currently supplied;
the CLI keeps no record of the head at publication. If a branch is updated and
evidence, review and the publication claim are regenerated, it cannot distinguish
that sequence from an original publication. Preventing updates is the host's
responsibility, and an updated run does not satisfy v0.3 acceptance. Retain the
head SHA from the host's creation event and compare it with the live PR head and
`GET repos/{repo}/pulls/{n}/commits` during the acceptance audit.

Schema 0.1 remains the default and keeps its original behavior, including its
own-draft overlap blocker. It rejects host context and explicit lifecycle stages.
Use a newly reviewed schema 0.2 task for this route; never silently migrate an old
contract or reinterpret its authorization prose.
