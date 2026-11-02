# Reviewed overlap dispositions (#7): design proposal

- Date: 2026-11-02
- Status: proposal, revision 3. Hostile review rounds 1 (RO-01 to RO-06) and 2
  (RO-07) are resolved in [Review resolution](#review-resolution). Slice 1
  (inert plumbing) is implemented on this branch.
- Base: `rsi/v03-land` at `44bf2d5` (unreleased v0.3.0 candidate: task/evidence
  schemas 0.1 and 0.2, host-context 0.1).
- Issue: [#7](https://github.com/nkovanen/agent-contrib/issues/7), product-map key B3.

## Summary

A human or trusted host may record, for one schema 0.2 contract, that a specific
**topical** overlap with a specific open PR is `unrelated`. The record goes in a
new optional host-context section, `overlap_dispositions`. It carries its own
event, nonce and interval, and is bound to the contract hash, the mandate hash and
the credential actor. Each entry pins:

- the PR's repository and PR IDs, number and author;
- its head repository and head SHA, state and draft flag;
- a hash of its title, body and refs, and `updated_at`;
- the exact match reason;
- the identity and hash of the immutable code comparison the human reviewed,
  including the base-branch tip it was computed against.

`verify` re-reads every disposed PR, reconciles each read with the open-PR scan,
and recomputes the match from the fresh copy. It waives the overlap only when all
of these hold:

- every bound observation is still equal;
- the match is still the same topical one;
- the PR is not authored by the bound credential actor;
- the record is unexpired after all blocking reads.

Anything else re-blocks: a direct issue reference, including one first seen in
the fresh read; a new or changed match; a change to any bound observation; an
incomplete scan or failed read; an expired or invalid record; or a different
contract or mandate. The guarantee is equality of these enumerated observations.
`updated_at` is an extra conservative check, not a complete history of past
events.

Schema 0.1 and host-context 0.1 are unchanged. Host-context gains an exact new
version `0.2`, which is 0.1 plus this optional section; unknown versions still
fail closed.

## Problem

Topical overlap is deliberately conservative. A PR blocks when it shares two or
more title words with the issue, or shares any checklist-shaped token. Live
dogfood examples:

- Issue #8 is blocked by PR #2 (`discover --limit`). The only shared token is
  `SHA-256`, matched as a "checklist ID" (friction F9 and F34).
- On busy repositories, unrelated PRs with common title words block most issues.

Nothing can resolve such a match:

- schema 0.1 blocks on live and prepared duplicates;
- schema 0.2 blocks implementation and draft creation on
  `live_duplicates + task.discovery.duplicate_prs` (`lifecycle.py:174-180`,
  `:217-218`);
- after publication, schema 0.2 exempts only the contribution's own exact-head
  draft (`without_own`).

Editing the contract cannot clear a live match, which is correct. Today the only
outcome is "choose another task".

What blocks today, and what this design changes:

| Match kind | Blocks today | Waivable here |
| --- | --- | --- |
| Direct reference (`#N`, `owner/repo#N`, issue URL, `GH-N`, branch number) | yes | **never** |
| Topical: two or more shared title words, or a shared checklist ID | yes | yes, per PR and per observed state |
| Incomplete or failed PR scan | yes | **never** |
| Prepared duplicate whose PR is no longer open | yes | no (re-prepare instead) |
| The contribution's own exact-head draft after publication | no (recognized) | n/a |

## Current facts the design depends on

- `index_prs` keeps only `number`, `url`, references, title words and checklist
  tokens (`core.py:370-401`). PR ID, head SHA, `updated_at`, state and base
  repository ID from the list response are dropped. So binding to PR state needs
  either a richer index or a fresh `GET repos/{source}/pulls/{n}`. This design
  uses the fresh read.
- `duplicate_prs` returns `{number, url, reason}`. A topical reason always starts
  with `Potential title/checklist overlap; review manually` and names the
  triggering words and IDs; a direct reason is exactly `Explicit reference to
  this issue` (`core.py:404-428`).
- Topical words come from the PR **title** only. Checklist tokens and direct
  references come from title, body and head ref (`core.py:389-400`).
- The contract binds `source.issue_sha256`, and `verify` refuses a changed issue.
  So the issue side of a match is fixed by the contract hash.
- Schema 0.2 host context is explicit stdin input: the closed host-context schema
  `0.1`, with sections `mandate` (required), `publication` and `final_signoff`.
  `core.bundled_schema('host-context')` accepts only version `0.1`
  (`core.py:612-614`).
- `inspect`, `discover`, `drift` and `pr-body` take no host context, by design
  (A1-12).

## Threat model

| # | Actor and attack | Required property |
| --- | --- | --- |
| T1 | **The worker launders a real conflict**: it writes or edits a disposition, or presents an "unrelated" summary to the human. | Only a human or trusted host issues dispositions, with the same event, nonce and hash discipline as the mandate. The host derives what the human sees from its own fresh PR read, never from a worker summary (RD-01 rule). `verify` echoes the record hash for audit. Same-credential forgery stays the documented non-goal. |
| T1b | **A hostile PR author writes a misleading description** (RO-01): a truthful API response whose title and body describe something unrelated while the code implements the issue, or a branch that changes while the human opens a diff link. | The human must review the **actual code**: an immutable comparison identified by full commit SHAs (merge base to bound head), retained by the host with the event. The record binds the independently resolved base-branch tip, the merge base, the head and the hash of the retained material. A base-tip change re-blocks, because an advancing base can change the patch while the head stays fixed (RO-07). Missing or truncated comparison material means the host must not issue. No automatic conflict analyzer is claimed. |
| T2 | **A hostile PR author changes the PR after review**: retitles it, edits the body to "fixes #12", pushes code, turns a draft ready, retargets the base or reopens it. | Bind and compare explicitly: head SHA, head repository ID, state, `draft`, base ref, a hash of title, body and refs, and the author. Recompute the match from the fresh read; a new direct reference is never waivable. `updated_at` equality is an **extra** conservative check. GitHub does not document that every event bumps it, and same-second ABA changes can leave it equal (RO-02). The guarantee is limited to the enumerated observations. |
| T3 | **A stale disposition**: the issue changes, the contract is re-prepared, or the mandate is re-issued. | Bind `contract_sha256` and `mandate_sha256`; the issue is already bound through the contract. |
| T4 | **Replay across tasks, repositories or PRs**. | Bind the repository ID, PR ID and number, the contract and mandate hashes, and the credential actor ID. Each entry covers exactly one PR. |
| T5 | **Waiver by omission**: an incomplete scan, an unread page, a PR that failed to read, or a disposed PR that left the scan but is direct in the detail read (RO-03). | A disposition never covers an unknown. Every disposed PR is read and reconciled with the scan. An incomplete scan, a failed detail read, or a contradiction between list and detail blocks. A direct or topical match first seen in the detail read becomes a blocker. |
| T6 | **Scope creep**: one disposition hides new or other matches. | A waiver applies only to entries whose recomputed reason equals the bound reason, for that PR. New PRs, and new reasons on the same PR, block. |
| T7 | **The disposition outlives human attention**, including expiring during slow reads (RO-05). | Its own interval, at most 24 hours. Expiry is judged with a fresh clock after all blocking reads, before any waiver-dependent gate, as is already done for final sign-off. Expiry re-blocks. Because it is a separate section, a host can re-issue it without touching the mandate. |
| T8 | **Read amplification by a hostile repository with many matches**. | At most 20 entries per record. Each disposed PR costs one logical PR GET, and each distinct base ref one base-tip GET, so at most 40 extra logical GETs, made only when a record is supplied. The transport retries a transient failure up to three times with 30-second timeouts, so the worst case adds roughly an hour. This is documented, and it is why expiry is rechecked after the reads. |
| T9 | **The worker relabels the agent's own earlier draft as unrelated** (RO-04). | Enforced, not assumed: a PR authored by the bound credential actor is **never** waivable. This also refuses legitimate earlier human PRs from that account, deliberately. Exact-head recognition (#3) and draft updates (#21) stay the only routes for the agent's own work. |

Schema 0.1 has no host-context channel, and this design adds none. Under 0.1 a
"disposition" could only be worker-editable contract data, which T1 forbids.

## Options

| Option | Summary | Pros | Cons |
| --- | --- | --- | --- |
| A | Add dispositions inside `mandate` | One human event; no new section | Re-issuing a mandate breaks recognition of an already published draft (the PR must be created inside the original mandate's interval, RD-07). PRs routinely change after publication: any comment changes `updated_at`. Completion could then never pass. |
| **B** | **New optional host-context section `overlap_dispositions`, bound to the contract and mandate hashes** | Re-issuable without touching the mandate; same issuer discipline as `final_signoff`; hashed separately | New host-context version; one GET per entry |
| C | Contract field (task schema 0.3) reviewed by the host | Visible in the contract | Worker-editable (T1); changes the contract hash, which forces a new mandate and has the same post-publication problem as A |
| D | Only tighten the heuristic, e.g. drop `SHA-256`-style tokens (F34) | Cheap; fewer false positives | Some false positives always remain; no reviewed resolution. A worthwhile **companion** fix, tracked separately. |
| E | Status quo: document "choose another task" | Nothing to build | The friction remains on busy repositories |

**Recommendation: B.** Ship D separately as a heuristic fix; it is not a
substitute.

## Specification

### Host-context schema 0.2

`agent_contribute/schemas/host-context/0.2.schema.json` is the 0.1 schema with
two changes:

- `schema_version` must equal `"0.2"`;
- it adds one optional property, `overlap_dispositions`.

`mandate`, `publication` and `final_signoff` are byte-identical to 0.1, so
`mandate_sha256` does not depend on the wrapper version. A host can add
dispositions later by re-wrapping the same issued mandate as 0.2.

```json
"overlap_dispositions": {
  "type": "object", "additionalProperties": false,
  "required": ["id", "nonce", "issued_at", "expires_at", "contract_sha256", "mandate_sha256",
               "credential_actor_id", "dispositions", "event"],
  "properties": {
    "id": {"type": "string", "minLength": 1, "maxLength": 200},
    "nonce": {"type": "string", "minLength": 24, "maxLength": 200},
    "issued_at": {"type": "string", "minLength": 1, "maxLength": 100},
    "expires_at": {"type": "string", "minLength": 1, "maxLength": 100},
    "contract_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    "mandate_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    "credential_actor_id": {"type": "integer", "minimum": 1},
    "dispositions": {
      "type": "array", "minItems": 1, "maxItems": 20,
      "items": {
        "type": "object", "additionalProperties": false,
        "required": ["repository_id", "pr_number", "pr_id", "author_id", "disposition",
                     "match_reason", "pr_state", "draft", "head_repository_id", "head_sha",
                     "updated_at", "content_sha256", "comparison", "rationale"],
        "properties": {
          "repository_id": {"type": "integer", "minimum": 1},
          "pr_number": {"type": "integer", "minimum": 1},
          "pr_id": {"type": "integer", "minimum": 1},
          "disposition": {"const": "unrelated"},
          "match_reason": {"type": "string", "minLength": 1, "maxLength": 2000},
          "author_id": {"type": "integer", "minimum": 1},
          "pr_state": {"const": "open"},
          "draft": {"type": "boolean"},
          "head_repository_id": {"type": "integer", "minimum": 1},
          "head_sha": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
          "updated_at": {"type": "string", "minLength": 1, "maxLength": 100},
          "content_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
          "comparison": {
            "type": "object", "additionalProperties": false,
            "required": ["base_tip_sha", "base_sha", "head_sha", "material_sha256"],
            "properties": {
              "base_tip_sha": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
              "base_sha": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
              "head_sha": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
              "material_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}
            }
          },
          "rationale": {"type": "string", "minLength": 1, "maxLength": 2000}
        }
      }
    },
    "event": {
      "type": "object", "additionalProperties": false,
      "required": ["kind", "reference", "text_sha256", "binding_sha256"],
      "properties": {
        "kind": {"const": "human"},
        "reference": {"type": "string", "minLength": 1, "maxLength": 100000},
        "text_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "binding_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}
      }
    }
  }
}
```

The event object is the same as `mandate.event`: `kind: human`, `reference`,
`text_sha256` and `binding_sha256`. The bundled validator has no `$ref`, so it
is written out in full.

Definitions:

- `content_sha256` is the canonical hash of `{"title": T, "body": B or "",
  "head_ref": H, "base_ref": R}` from the fresh `GET repos/{source}/pulls/{n}`.
  The host computes it from its own read.
- `match_reason` is the exact topical reason string `verify` produces today.
- `updated_at` is GitHub's string, compared exactly. The RFC 3339 parser
  validates its shape; values are not normalized. It is an extra conservative
  check, not an event counter.
- `comparison` identifies the code the human reviewed. It holds:
  - `base_tip_sha`: the base branch's tip, resolved **independently** at issuance
    with `GET repos/{source}/git/ref/heads/{base.ref}`. The PR object's
    `base.sha` is not used; it can differ from the current tip (RO-07).
  - `base_sha`: the merge base reported by
    `GET repos/{source}/compare/{base_tip_sha}...{head_sha}`
    (`merge_base_commit.sha`);
  - `head_sha`, which must equal the entry's `head_sha`;
  - `material_sha256`: the SHA-256 of the canonical JSON of the retained
    `files` array of that comparison, in response order. Each item keeps exactly
    `filename`, `previous_filename` (or `null`), `status`, `sha` and `patch` (or
    `null`). An auditor recomputes this digest from the retained bytes, never from
    a re-fetch.

  The CLI checks that `comparison.head_sha` equals the bound and live head, and
  that the base branch's current tip still equals `base_tip_sha`. An advancing
  base can change the merge base and the patch while the head stays fixed
  (`A -> B -> H`: `A...H` and `B...H` differ), so **any** base-tip change
  re-blocks, including harmless advances. The CLI cannot verify the retained
  material; that is host evidence for audit.
- `author_id` is the PR's `user.id` and `head_repository_id` its `head.repo.id`.
  A `null` head repository (deleted fork) cannot be bound and is not waivable.
- Event binding and record hash follow the existing recipe:
  `event.binding_sha256` is computed over the section without that field, and
  `overlap_dispositions_sha256` is the canonical hash of the complete section.

### Version handling

- `core.bundled_schema('host-context', version)` accepts exactly `{'0.1', '0.2'}`.
- Every caller selects the schema from the document's own `schema_version`:
  `authorization.check`, `lifecycle.human_signoff` and the final sign-off
  sub-schema lookup. A non-object document, a missing or unknown version, or a
  0.1 document containing `overlap_dispositions` is a schema error, as today.
- `instructions` reports `supported_host_context_versions: ["0.1", "0.2"]`.
- `authorization-request` still targets `0.1`; the mandate section is identical
  in both versions.
- The earlier route design's local-base idea, which was never specified or
  planned, would need a later version. It does not claim 0.2.

### Verification (schema 0.2 only)

The steps, in order:

1. **Section checks.** If the host context has `overlap_dispositions`, check:
   - the schema (above);
   - `event.binding_sha256`;
   - the interval: positive, at most 24 hours and not issued in the future (its
     expiry is decided in step 7);
   - `contract_sha256` equals the current contract hash;
   - `mandate_sha256` equals the supplied mandate's hash, and the mandate is
     `historical_valid`;
   - `credential_actor_id` equals the live credential actor;
   - `(repository_id, pr_number)` is unique across entries;
   - every `repository_id` equals `source.repository_id`;
   - no entry's `author_id` equals `credential_actor_id`;
   - each `comparison.head_sha` equals the entry's `head_sha`;
   - `id`, `nonce` and `event.reference` differ from the mandate's and from any
     `final_signoff`'s (a distinct human event).

   Any failure gives `overlap_dispositions.status: "invalid"` with errors, and
   **nothing is waived**. Mandate gates are not otherwise affected.
2. **Read every disposed PR.** For each distinct `(repository_id, pr_number)` in
   the record, whether or not the scan matched it, make one
   `GET repos/{source}/pulls/{n}` with strict shape checks (reusing the
   `pr_identity` field validators). A failed or malformed read adds the blocker
   `Overlap disposition read failed for PR #N`.
3. **Recompute** the finding from each detail:
   `duplicate_prs(source, current_issue, index_prs([detail]))`. The result is
   no match, one direct finding or one topical finding.
4. **Reconcile with the scan** (live and prepared entries for the same source
   PR number). Each case gives one of these outcomes:
   - **Direct in the detail** (even if absent from the list): the PR blocks with
     `Explicit reference to this issue (observed in disposition read)`. It is
     added to `blocking_duplicates`, and to `duplicates` with `observed_in:
     "disposition_read"`.
   - **Topical in the detail, absent from the list**, or **in the list but no
     match in the detail**: a list/detail contradiction. It blocks with
     `Overlap scan and disposition read disagree for PR #N`.
   - **Topical in both**: the PR is a waiver candidate.
   - **No match in both, and no prepared entry**: the entry is `unused`
     (informational). That is only established after this read.
5. **Waiver candidate checks.** All must hold:
   - the live discovery and its open-PR scan are `complete`;
   - every live and prepared entry for the PR has the same reason; it equals the
     detail's recomputed reason and `match_reason`, and is not the direct reason;
   - `id == pr_id`, `number == pr_number`, and
     `base.repo.id == repository_id == source.repository_id`;
   - the canonical `html_url`;
   - `user.id == author_id`, which is not the credential actor;
   - `state == "open"`, `draft` equal, `head.repo.id == head_repository_id`, and
     `head.sha == head_sha`;
   - the base branch's current tip equals `comparison.base_tip_sha`. It is
     resolved with one `GET repos/{source}/git/ref/heads/{base.ref}` per distinct
     base ref (deduplicated), never from the PR's `base.sha`. A failed or
     malformed read blocks;
   - `updated_at` equal;
   - the content hash equal.

   A failure leaves the PR blocking with its specific error, for example
   `Overlap disposition stale for PR #2: draft`.
6. **Remaining reads.** Evidence, publication and other reads continue as today.
7. **Expiry, after all blocking reads** (RO-05). Using a fresh clock, as for the
   final sign-off (`lifecycle.py:225-227`), decide whether the record is still
   unexpired. Only then move candidates into `waived_duplicates` and compute the
   gates. An expired record waives nothing and adds `Overlap disposition record
   expired`.

The waiver feeds the existing lists. Only the unwaived list drives:

- `Issue overlaps an open or unresolved prepared PR` (implementation and draft);
- `blocking_duplicates` and `Unresolved overlapping PRs remain` (post-publication
  and completion).

`result['duplicates']` still lists every live match. The PR is never hidden.

New `verify` output keys (schema 0.2 only). These are additions; existing keys
change only by gaining entries observed in a disposition read:

```json
"overlap_dispositions": {
  "status": "absent | evaluated | invalid",
  "trust": "host-asserted",
  "sha256": "<hash or null>",
  "errors": [],
  "waived": [{"repository": "...", "number": 2, "url": "...", "reason": "...",
              "pr_id": 3001, "head_sha": "...", "updated_at": "...",
              "untrusted_rationale": "<sanitized>"}],
  "unused": [5]
},
"waived_duplicates": [ ...the same waived entries... ]
```

`next_action`, the gates and exit codes follow the unwaived lists. If no section
is supplied, every result is byte-identical to today's.

**Text output** (RO-06). Whenever a waiver was applied, `--format text verify`
adds a line such as `Overlaps waived by host disposition (host-asserted): 1 -
PR #2; see JSON overlap_dispositions`. It also shows the disposition status and
its errors, so a green gate never hides the exception that made it green.

### Commands that take no host context

`inspect`, `discover`, `drift`, `audit` and `pr-body` are unchanged. They keep
listing every overlap, which is the conservative, visible default. A waiver is
reported only by `verify`, the one command that sees host records.

`pr-body` already omits schema 0.2 authority gates and says so (A1-12). Its
overlap list states the matches, not a blocking verdict. A PR description must
not claim a waiver that it cannot check. The host may quote `verify`'s `waived`
entries in the PR text itself.

This deliberately deviates from the issue's "report in inspect and the PR body".
Those commands cannot authenticate the record, so they show the overlap and
never a waiver.

### Workflow and host requirements

- **`instructions.md`, schema 0.2:** a topical overlap may be presented to the
  human for an `unrelated` disposition. Direct references, incomplete scans and
  closed prepared PRs are never waivable. The worker must never write the
  section.
- **`docs/host-authorization.md`, host issuer requirements:**
  - the host reads the PR itself and shows the human its title, body, head and
    base refs, state, draft flag, author and the match reason (rendered as data);
  - it shows the actual code (RO-01, RO-07):
    - it resolves the base branch tip itself (`git/ref/heads/{base.ref}`), never
      from the PR's `base.sha`;
    - it fetches `compare/{base_tip}...{head.sha}` for the bound head;
    - it presents the full file list and patches as retained material,
      identified by base tip, merge base and head SHAs.

    A mutable diff link is not enough. The host does not issue when the
    comparison is unavailable, saturated (300 files, GitHub's cap) or missing a
    patch for a non-binary file.
  - it retains that exact material with the event, and records its hash as
    `comparison.material_sha256`;
  - it computes every bound field from its own reads;
  - it refuses PRs authored by the credential actor;
  - the event text includes the nonce and the PR number;
  - the record is kept in the same status registry as mandates; a `revoked` or
    `superseded` record waives nothing;
  - re-issuing after a PR changes is a new human event.

  Mandatory host tests:
  - a forged summary;
  - a PR edited between review and issuance;
  - a truthful API response whose description misleads about its code;
  - a branch pushed while the human reviews, where the record must bind the
    reviewed head;
  - a truncated comparison, which must not issue;
  - a PR whose `base.sha` differs from the base branch tip: the host binds the
    tip it resolved itself.

  These requirements ship **with or before** the waiver evaluation (slice 3), never
  after it.
- `docs/cli.md`, `README.md` (current limits) and `docs/product-map.md` (B3 moves
  to partly implemented once shipped) are updated.

## Compatibility

| Input | Before | After |
| --- | --- | --- |
| Task 0.1, any route | unchanged; host context rejected | unchanged |
| Task 0.2 with host-context 0.1 | current decisions | byte-identical (golden-pinned) |
| Task 0.2 with host-context 0.2, no `overlap_dispositions` | unknown version, fail closed | same decisions as 0.1, plus `overlap_dispositions.status: "absent"` |
| Task 0.2 with host-context 0.2 and a section, after slice 1 only | n/a | parsed and hashed, `status: "not_evaluated"`; **nothing waived**; gates unchanged |
| Task 0.2 with host-context 0.2 and a valid section, after slice 3 | n/a | matching topical overlaps are waived; newly observed direct matches and contradictions block; all else unchanged |
| Host-context 0.1 containing `overlap_dispositions` | schema error | schema error |
| Unknown host-context version | fail closed | fail closed |
| Older CLI given host-context 0.2 | n/a | fails closed (unknown version) |

Task and evidence schemas are unchanged, and nothing is migrated.

## Adversarial test plan

Fixtures extend `IntegratedGitHub` with `pulls/{n}` details. A helper builds
dispositions the way a host would: from its own read, with correct event
binding.

1. **Happy path.** A topical match on PR #2 is disposed:
   - implementation is ready;
   - after publication, completion is no longer blocked by PR #2;
   - `duplicates` still lists #2, and `waived` shows it with provenance.
2. **Each bound field changing re-blocks**, each with its specific error:
   - title (also changes the reason), body, head ref, base ref;
   - head SHA, head repository ID (and a `null` head repository);
   - `draft` alone, with an **unchanged** `updated_at` (RO-02);
   - `updated_at` alone;
   - state closed;
   - author, `pr_id`, `repository_id`, `pr_number`;
   - a non-canonical `html_url`.

   **ABA:** a field changed and restored, with every field and `updated_at`
   equal again, is waived. This pins that the guarantee covers current observed
   equality, not history.
3. **Direct references are never waivable:**
   - a disposition for a PR whose body says `fixes #12`, `owner/repo#12`, the
     issue URL, `GH-12` or a branch `12-fix`;
   - a PR that becomes direct after review, with the bound reason still topical;
   - a disposition whose `match_reason` is set to the direct reason string (a
     schema-valid forgery).
4. **The match changes.** The issue-side words are fixed by the contract. A
   PR-side title change adds a second checklist ID: the reason differs and the
   entry re-blocks. The live and prepared reasons differ, which re-blocks.
5. **Scope.** A second, undisposed topical PR still blocks. A new PR opened after
   review still blocks. The disposition for #2 never affects #3.
5a. **Reconciliation** (RO-03):
   - not matched in the list, but direct in the detail: blocks, and the PR is
     listed in `duplicates` with `observed_in`;
   - not matched in the list, but topical in the detail: contradiction, blocks;
   - topical in the list, no match in the detail: contradiction, blocks;
   - a detail read failure for an `unused` candidate: blocks;
   - a PR in both live and prepared entries is read once (one GET).
5b. **Own work** (RO-04): a PR whose author is the credential actor, on a
   different branch and with no issue reference, is a schema-valid record. It is
   refused at section check (the record's `author_id`), and refused again if the
   record lies (the live `user.id` matches the actor).
5c. **Expiry during reads** (RO-05): a fake clock advances past `expires_at` during
   the detail GETs. Nothing is waived, and gates computed before and after agree.
6. **Unknowns:**
   - the open-PR list is incomplete, or a page failed;
   - the detail GET fails, returns malformed JSON or is missing `head.sha`;
   - the detail returns `null` body (hashed as `""`; pinned);
   - every case keeps blocking.
7. **Binding and replay.** Each of these makes the section `invalid` and waives
   nothing:
   - another contract's hash, or another mandate's hash;
   - a mandate that is not `historical_valid`;
   - a different credential actor;
   - `repository_id` of another repository;
   - a duplicate entry for the same PR;
   - the mandate's `id`, nonce or event reference reused;
   - a bad event binding;
   - an interval in the future, reversed, over 24 hours, or expired at check
     time.
8. **Section placement.** A 0.1 document with `overlap_dispositions` is a schema
   error. A 0.2 document without a mandate is a schema error. Unknown versions
   `"0.3"`, `0.2` (number) and `null` all fail. Task 0.1 with a 0.2 host context
   is rejected as today.
9. **Compatibility goldens.** Every existing host-context 0.1 fixture gives
   byte-identical `verify` JSON and exit codes. The same mandate wrapped as 0.2
   without the section gives identical gates and the same `mandate_sha256`.
9a. **Base tip** (RO-07):
    - the `A -> B -> H` example: the base branch advances from the bound tip A
      to B, while head H, `updated_at` and every other field stay unchanged.
      The PR blocks with `stale ... base tip`;
    - the PR detail's `base.sha` differs from the ref tip, but the ref tip equals
      the bound one: waived. This proves the tip is read from the ref;
    - `base.sha` equals the bound tip but the ref tip differs: blocks;
    - the base-ref read fails or is malformed: blocks;
    - two PRs on the same base ref make one base-tip GET.
10. **Reads.** Without the section, the read sequence is identical to today's.
    With N distinct disposed PRs on M distinct base refs, exactly N `pulls/{n}`
    GETs and M base-ref GETs are made,
    only after the list scan completed. With more than 20 entries the schema
    fails before any read.
10a. **Text output** (RO-06): with a waiver applied, `--format text verify` shows
    the waiver line and PR number; without one it is unchanged.
11. **Unused entries.** A disposition for a PR that no longer matches is listed in
    `unused`, waives nothing and adds no error. A closed PR that is still in the
    prepared list stays blocking.
12. **Commands without host context.** `pr-body`, `inspect` and `drift` output are
    byte-identical with or without a section (they never read it).
13. **Mutation testing** in a `/tmp` copy. Each mutant must be killed:
    - skip the direct-reason check;
    - skip any single bound-field comparison;
    - skip the match recompute;
    - accept an incomplete scan;
    - waive by number only, across repositories;
    - ignore expiry;
    - accept a mandate hash mismatch;
    - apply the waiver to the `duplicates` output list;
    - skip the detail read for `unused` entries;
    - drop the direct-in-detail promotion;
    - skip the author check;
    - check expiry before the reads;
    - omit the text waiver line;
    - use the 0.1 schema for 0.2 documents.

## Slices

Each slice is independently shippable and gets its own hostile review.

1. **Host-context 0.2 plumbing.** The schema file, exact version selection at
   every caller, `instructions` versions and compatibility goldens. A valid
   section is validated, hashed and reported with `status: "not_evaluated"`
   (never "valid"), but **waives nothing**. `instructions` and the docs say
   that waiver evaluation is not supported yet. This is safe on its own: it can
   only add errors.
2. **Host issuer requirements and workflow text**, shipped before or with
   slice 3. These are the code-review, retention and refusal rules and the
   mandatory host tests.
3. **Waiver evaluation.** Read all disposed PRs, reconcile, recompute, expiry
   after the reads, waiver lists, new output keys, the text line, and the full
   adversarial plan with mutants. Update `docs/cli.md`, README limits, the
   product map and the CHANGELOG.
4. **Deferred, only if hosts need it.** A read-only helper that emits a
   disposition request for each topical overlap: bindings pre-filled from fresh
   reads, human-only fields `null`, no summary, as in RD-01. Hosts must compute
   bindings themselves either way.
5. **Separate issue: the companion heuristic fix** (option D, F34). Ignore
   checklist tokens that are common technical terms (`SHA-256`, `UTF-8`,
   `HTTP-2` and similar), with goldens re-reviewed. This is independent of the
   disposition machinery.

## Out of scope

- Schema 0.1 dispositions: there is no host channel, and the issue requires one.
- Waiving direct references, incomplete scans, closed or merged PRs, or the
  agent's own non-exact-head drafts. Use #21 (draft updates) or close the PR.
- File-level conflict analysis: overlap remains a title/reference heuristic.
- Disposition kinds other than `unrelated`, such as "complementary" or "will
  rebase after".
- Persisting dispositions across contracts. A re-prepared contract needs a new
  human decision.
- Showing waivers in `inspect`, `discover` or `pr-body`, which cannot
  authenticate host records.

## Review resolution

Round 1 (`review-ro-sol.md`, against `5f7378f`): `BLOCK`, H=1 M=4 L=1. Each
finding was checked against the design text and code. None is disputed.

| ID | Severity | Verdict | Independent check | Change in revision 2 |
| --- | --- | --- | --- | --- |
| RO-01 | High | Confirmed | Revision 1 required the host only to render the PR metadata and link to `/files`. The description is author-controlled, and the link is a mutable snapshot. | T1b added. The host must review and retain an immutable comparison, identified by full SHAs, or refuse when it is truncated. The record binds the comparison (base tip added in revision 3). Mandatory host tests added. Requirements now ship before or with waiver evaluation. |
| RO-02 | Medium | Confirmed (binding gap); platform behavior not verified | The content hash omitted `draft`, and nothing documents that every event bumps `updated_at`, which has second precision. | `draft`, `author_id` and `head_repository_id` are bound and compared explicitly. `updated_at` is now an extra check. The promise is narrowed to equality of the enumerated observations. ABA and draft-only-change tests added. |
| RO-03 | Medium | Confirmed | Revision 1 fixed the candidate set from the list before the detail reads, and treated non-candidates as `unused` without reconciling them. | Every disposed PR is read (deduplicated) and reconciled. A direct finding seen only in the detail blocks and is listed. A list/detail contradiction blocks. `unused` is decided only after the read. A read failure blocks. Residual: a PR created after the scan is not covered, and reads are not atomic (documented). |
| RO-04 | Medium | Confirmed | No check compared the PR author with the credential. "Own drafts reference the issue" was an assumption. | A PR authored by the credential actor is never waivable. This is checked on the record's `author_id` and on the live `user.id`, and is documented to over-refuse legitimate earlier PRs from that account. |
| RO-05 | Medium (suspected) | Accepted | The ordered steps checked expiry once, before the detail reads. Final sign-off already uses a fresh clock after the blocking reads. | Expiry is decided with a fresh clock after all blocking reads, before any waiver-dependent gate. A fake-clock test is added. The worst-case retry duration is documented. |
| RO-06 | Low | Confirmed | `textfmt._verify` renders gates and errors only. | The text output names the waived PRs and the disposition status and errors. A formatter test and a mutant are added. |

The review's answers to the open questions are adopted:

- keep strict `updated_at` as an extra check, without overstating it;
- keep `unused` informational, but only after reconciliation;
- slice 1 reports `not_evaluated`, never `valid`;
- issuer requirements ship with or before evaluation.

### Round 2 (revision 3)

Round 2 against revision 2 (`4a130a5`) closed RO-01 to RO-06 and raised one new
finding. Slice 1 was judged safe to continue.

| ID | Severity | Verdict | Independent check | Change in revision 3 |
| --- | --- | --- | --- | --- |
| RO-07 | Medium | Confirmed | `git merge-base 44bf2d5 4a130a5` and `git merge-base 5f7378f 4a130a5` differ with the head fixed, so a moving base changes the merge base. Revision 2 claimed the opposite and bound no base tip. The PR object's `base.sha` is also not guaranteed to be the current tip. | Removed the false invariant. Each comparison binds `base_tip_sha`, resolved independently from `git/ref/heads/{base.ref}`, plus the merge base and head. Verification rereads the tip once per distinct base ref and re-blocks on any change. The retained material's encoding is now defined (canonical JSON of the `files` items). The issuer refuses saturated (300-file) or patchless comparisons. Read bound updated to at most 40 logical GETs. Tests 9a added. The schema field was added to slice 1 before freezing it (`c7f7a8c`). |

