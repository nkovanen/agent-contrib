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

Work stacked on unpublished commits cannot produce valid schema 0.2 evidence,
because the evidence base must be in the source default branch's history. Land
the base first, then prepare, authorize, validate and review again; see the
installed workflow.

## Three separately sourced records

The strict [host-context schema](../agent_contribute/schemas/host-context/0.1.schema.json)
is an object with `schema_version: "0.1"` and a required `mandate`. Optional
sections are omitted until available; `null` is not an absent section.

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
