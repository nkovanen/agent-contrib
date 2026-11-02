# Reviewed overlap dispositions (#7): design proposal

- Date: 2026-11-02
- Status: proposal for hostile review. No code is part of this step.
- Base: `rsi/v03-land` at `44bf2d5` (unreleased v0.3.0 candidate: task/evidence
  schemas 0.1 and 0.2, host-context 0.1).
- Issue: [#7](https://github.com/nkovanen/agent-contrib/issues/7), product-map key B3.

## Summary

A human or trusted host may record, for one schema 0.2 contract, that a specific
**topical** overlap with a specific open PR is `unrelated`. The record goes in a
new optional host-context section, `overlap_dispositions`. It carries its own
event, nonce and interval, and is bound to the contract hash, the mandate hash and
the credential actor. Each entry pins the PR's repository and PR IDs, number, head
SHA, `updated_at`, a hash of its title, body and refs, and the exact match reason.

`verify` re-reads each disposed PR and recomputes the match from that fresh copy.
It waives the overlap only if every bound fact still holds and the match is still
the same topical one. Anything else re-blocks: a direct issue reference, a new or
changed match, any PR edit, a push or state change, an incomplete scan, an expired
or invalid record, or a different contract or mandate.

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
| T2 | **A hostile PR author changes the PR after review**: retitles it, edits the body to "fixes #12", pushes code, force-pushes back to the same SHA, reopens it, or turns a draft ready. | Bind head SHA, `updated_at`, state, and a hash of title, body, head ref and base ref. Recompute the match from the fresh read. A new direct reference is never waivable. Any edit or push changes `updated_at` or the SHA and re-blocks. |
| T3 | **A stale disposition**: the issue changes, the contract is re-prepared, or the mandate is re-issued. | Bind `contract_sha256` and `mandate_sha256`; the issue is already bound through the contract. |
| T4 | **Replay across tasks, repositories or PRs**. | Bind the repository ID, PR ID and number, the contract and mandate hashes, and the credential actor ID. Each entry covers exactly one PR. |
| T5 | **Waiver by omission**: an incomplete scan, an unread page, or a PR that failed to read. | A disposition never covers an unknown. An incomplete live scan or any failed detail read leaves the entry blocking. |
| T6 | **Scope creep**: one disposition hides new or other matches. | A waiver applies only to entries whose recomputed reason equals the bound reason, for that PR. New PRs, and new reasons on the same PR, block. |
| T7 | **The disposition outlives human attention**. | Its own interval, at most 24 hours, and checked whenever it is applied. Expiry re-blocks instead of failing silently. Because it is a separate section, a host can re-issue it without touching the mandate. |
| T8 | **Read amplification by a hostile repository with many matches**. | At most 20 entries per record, and one GET per entry, only when a record is supplied. |
| T9 | **The worker relabels the agent's own earlier draft as unrelated**. | Own drafts normally reference the issue directly, so they are not waivable. Exact-head recognition (#3) and draft updates (#21) stay the only routes. |

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
        "required": ["repository_id", "pr_number", "pr_id", "disposition", "match_reason",
                     "pr_state", "head_sha", "updated_at", "content_sha256", "rationale"],
        "properties": {
          "repository_id": {"type": "integer", "minimum": 1},
          "pr_number": {"type": "integer", "minimum": 1},
          "pr_id": {"type": "integer", "minimum": 1},
          "disposition": {"const": "unrelated"},
          "match_reason": {"type": "string", "minLength": 1, "maxLength": 2000},
          "pr_state": {"const": "open"},
          "head_sha": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
          "updated_at": {"type": "string", "minLength": 1, "maxLength": 100},
          "content_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
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
  validates its shape; values are not normalized.
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
   - the interval: positive, at most 24 hours, not issued in the future, and
     unexpired **now**;
   - `contract_sha256` equals the current contract hash;
   - `mandate_sha256` equals the supplied mandate's hash, and the mandate is
     `historical_valid`;
   - `credential_actor_id` equals the live credential actor;
   - `(repository_id, pr_number)` is unique across entries;
   - every `repository_id` equals `source.repository_id`;
   - `id`, `nonce` and `event.reference` differ from the mandate's and from any
     `final_signoff`'s (a distinct human event).

   Any failure gives `overlap_dispositions.status: "invalid"` with errors, and
   **nothing is waived**. Mandate gates are not otherwise affected.
2. **Candidate entries.** These are the live duplicates plus the prepared
   duplicates whose `repository` is the source and whose `number` has a
   disposition entry. Everything else stays blocking unchanged.
3. **Preconditions per candidate.** All must hold:
   - the live discovery is `complete`, and so is the open-PR scan;
   - the candidate's reason does not equal `Explicit reference to this issue`,
     and starts with the topical prefix;
   - every live and prepared entry for that PR number has the same reason, and
     it equals `match_reason`.
4. **Fresh read.** Make one `GET repos/{source}/pulls/{n}` per disposed PR, with
   strict shape checks (reusing `pr_identity` field validators). Require all of:
   - `id == pr_id`, `number == pr_number`, and
     `base.repo.id == repository_id == source.repository_id`;
   - the canonical `html_url`;
   - `state == "open"`, `head.sha == head_sha` and `updated_at == updated_at`;
   - the recomputed content hash equals `content_sha256`.
5. **Recompute the match** from that same object:
   `duplicate_prs(source, current_issue, index_prs([detail]))`. This must give
   exactly one finding: topical, with a reason equal to `match_reason`. A direct
   reference found now, such as an edited body, makes the entry non-waivable.
6. **Result.** A candidate that passes is moved to `waived_duplicates`. A
   candidate that fails stays blocking, and its specific error is added, for
   example `Overlap disposition stale for PR #2: updated_at`. Disposition entries
   that match no current candidate are listed in `unused`; they waive nothing
   and are not an error.

The waiver feeds the existing lists. Only the unwaived list drives:

- `Issue overlaps an open or unresolved prepared PR` (implementation and draft);
- `blocking_duplicates` and `Unresolved overlapping PRs remain` (post-publication
  and completion).

`result['duplicates']` still lists every live match. The PR is never hidden.

New `verify` output keys (schema 0.2 only; additions, no existing key changes):

```json
"overlap_dispositions": {
  "status": "absent | valid | invalid",
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
    base refs, state and the match reason (rendered as data);
  - it links the human to the PR diff;
  - it computes `content_sha256`, `head_sha` and `updated_at` from that read;
  - the event text includes the nonce and the PR number;
  - the record is kept in the same status registry as mandates; a `revoked` or
    `superseded` record waives nothing;
  - re-issuing after a PR changes is a new human event.

  Mandatory host tests: a forged summary, and a PR edited between review and
  issuance.
- `docs/cli.md`, `README.md` (current limits) and `docs/product-map.md` (B3 moves
  to partly implemented once shipped) are updated.

## Compatibility

| Input | Before | After |
| --- | --- | --- |
| Task 0.1, any route | unchanged; host context rejected | unchanged |
| Task 0.2 with host-context 0.1 | current decisions | byte-identical (golden-pinned) |
| Task 0.2 with host-context 0.2, no `overlap_dispositions` | unknown version, fail closed | same decisions as 0.1, plus `overlap_dispositions.status: "absent"` |
| Task 0.2 with host-context 0.2 and a valid section | n/a | the matching topical overlaps are waived; all else unchanged |
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
2. **Each bound field changing re-blocks**, each with its specific error: title
   (also changes the reason), body, head ref, base ref, head SHA, `updated_at`
   only (for example a comment), state closed, draft-to-ready (via
   `updated_at`), `pr_id`, `repository_id`, `pr_number`, and `html_url`
   non-canonical.
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
10. **Reads.** Without the section, the read sequence is identical to today's.
    With N entries, exactly N extra `pulls/{n}` GETs are made, and only after
    the list scan completed. With more than 20 entries the schema fails before
    any read.
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
    - use the 0.1 schema for 0.2 documents.

## Slices

Each slice is independently shippable and gets its own hostile review.

1. **Host-context 0.2 plumbing.** The schema file, exact version selection at
   every caller, `instructions` versions and compatibility goldens. A valid
   section is validated, hashed and reported (`status`, `sha256`), but
   **waives nothing**. This is safe on its own: it can only add errors.
2. **Waiver evaluation.** The fresh PR reads, recompute, waiver lists, the new
   output keys and the full adversarial plan with mutants.
3. **Docs.** Workflow text, host issuer requirements (disposition issuance and
   tests), `docs/cli.md`, README limits, product map and CHANGELOG.
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

## Open questions for review

- Is binding `updated_at` (re-block on any comment) too strict for long-lived
  drafts? The alternative is binding only the content hash and head SHA, at the
  cost of not noticing label or state churn. The design picks the strict option;
  re-issuing a separate section is cheap.
- Should `unused` entries make the section `invalid`, to force hosts to keep
  records tight, or remain informational as proposed?
