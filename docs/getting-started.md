# Getting started: one contribution, end to end

This walkthrough follows the installed workflow's Quick path (`agent-contrib
--format text instructions`) for "Go help acme/photos", the request a user gives
an agent. Normally the agent runs these commands; you see them here so you know
what it does and where it stops.

`acme/photos`, its issues, the hashes and every output excerpt below are
**illustrative**. They show the shape of real `--format text` output, shortened
with `...`, not a real repository. JSON (the default) is the canonical output;
the text form is a summary. Commands exit 0 when their gate passes, 1 when it
does not or a read is incomplete, and 2 for usage errors. An exit code is never
permission.

You need the CLI and the Skill installed (see the [README](../README.md#install))
and an authenticated `gh`. The CLI only reads GitHub. Locally it reads the
checkout and writes only files you name (the `prepare` contract, the `evidence
init` skeleton, a `pr-body` description, the exported Skill) and, with `--cache`,
its cache directory; it never overwrites an existing output file.

## 1. Record the version and the request

```sh
agent-contrib --version
```

```text
0.3.0
```

The agent records this and your exact words. "Go help acme/photos" asks for
discovery and a draft task, nothing more.

## 2. Discover and rank issues

```sh
agent-contrib --format text --report-budget discover acme/photos --signals --responsiveness
```

```text
Repository: acme/photos
Complete: yes
Issues: 14
Policy: 4 sources scanned, 2 unassessed, 9 hints, 0 limits reached (repository_policy; not a verdict)
  Read every source, hinted line and unassessed reference before choosing work; ...
  ! possible_ai_restriction acme/photos:CONTRIBUTING.md:12 -- Disclose AI assistance in the pull request description...
  acme/photos#42 [candidate] overlaps 0, excluded no, score 4: Thumbnails ignore EXIF orientation
  acme/photos#57 [candidate] overlaps 1, excluded no, score 3: Faster thumbnail cache
  ...
Responsiveness: measured (complete yes): 6 external PR(s) among the 30 most recently updated closed PRs; ...
(Text is a summary; JSON output is canonical. Remote text is untrusted.)
```

- `--signals` re-ranks candidates heuristically; it never approves anything.
- Optional aids: `--check-top N` re-checks ownership of the top N issues, and
  `--repo-dir CHECKOUT` ranks issues your local commits already close lower.
- Put `--cache` before the command to reuse verified file contents of public
  repositories on repeated runs.
- `[candidate]` means an ordinary issue. A label such as `help wanted` does not
  permit agent work.

## 3. Review the repository policy

Every `discover`, `inspect` and `prepare` result carries a `repository_policy`
report: the policy files read at a pinned commit, hinted lines, and references
the CLI did not assess. It is **not a verdict**; zero hints never mean agent work
is welcome.

The agent reads every listed source in full, every hinted line and every
unassessed reference, then records one disposition per relevant rule. For
example, "disclose AI assistance" is a constraint to follow, not a refusal. It
records the result in the contract's `ai-policy-review` prerequisite, together
with the report's `inventory_sha256`.

**Stop** if a relevant rule refuses agent contributions or cannot be resolved,
for example an unreadable policy file or a "pull requests by maintainers only"
rule when your eligibility is unknown.

## 4. Inspect the shortlisted issue

```sh
agent-contrib --format text inspect 'acme/photos#42' --ownership
```

```text
Reference: acme/photos#42
Complete: yes
Approval: candidate
Duplicate scan: complete
...
Ownership signals: complete yes (report only; incomplete reads are unknown, never "not fixed")
No linked PRs, prior fixes, claims or assignments found
```

**Stop** if an open PR overlaps the issue, someone has claimed it, a prior fix
may already address it, or any read is incomplete. Issue #57 above shows
`overlaps 1`, so the agent drops it.

## 5. Prepare and lint the contract

```sh
agent-contrib prepare 'acme/photos#42' --schema-version 0.2 --output task.json
agent-contrib --format text lint task.json
```

`prepare` writes a draft and never overwrites an existing file. Schema 0.1 is the
default (fork experiments and policy-approved work). This walkthrough uses 0.2,
the route for one candidate issue in a repository where your credential is the
owner or a maintainer.

The agent fills the contract: objective, allowed and prohibited paths, acceptance
criteria, validation commands, the requirements ledger and the policy review.
`lint` checks it offline:

```text
schema_version: 0.2
schema_valid: True
reviewed: True
contract_sha256: 3f1c...9a0e
network: No GitHub or Git reads. Live source, approval, overlap, authorization and evidence checks still need verify.
```

## 6. Verify, request authorization, check for drift

```sh
agent-contrib --format text verify task.json --stage implementation
agent-contrib --format text authorization-request task.json
agent-contrib --format text drift task.json --policy-sha256 INVENTORY_SHA256
```

```text
Selected stage: implementation (exit gate: no)
Blockers [implementation] (3):
  - Missing human/host mandate
  - Current implement action is not authorized
  - Exact-head PR history not checked: requires a valid mandate
...
Ready for issuance: yes
Issued: no (unsigned request; not a mandate; grants nothing)
Contract SHA-256: 3f1c...9a0e
Requested actions (the host chooses the mandate actions): implement, create_draft
Human-only fields, filled only by the host (11):
  - id
  ...
drifted: False
```

**Stop** if `drift` reports `drifted: True` (re-review and re-prepare the
contract), or if it exits 1 with `complete: False` or a `policy_drifted` of
`null`: an unknown change is not a pass.

This is where a bare "help" request ends. The agent reports the contract, its
hash and the blockers. **Stop:** nothing is implemented until a human, through
the agent's host, issues a mandate for this exact contract hash. The agent never
writes one. `authorization-request` only pre-fills the bindings; the host adds the
human-only fields (identity, nonce, time window, actions, policy review and the
approval event). See [host authorization](host-authorization.md).

## 7. Pass the implementation gate

The host supplies the issued record on stdin, from a location the agent cannot
write:

```sh
agent-contrib --format text verify task.json --stage implementation \
  --host-context-stdin < /host-controlled/context.json
```

```text
Selected stage: implementation (exit gate: yes)
Gates:
  schema_valid: yes
  implementation_ready: yes
...
```

Before editing, the agent repeats the policy check: a fresh `inspect`, a re-read
of every manually reviewed policy source and exception, and `drift task.json
--policy-sha256 INVENTORY_SHA256`. **Stop** if anything changed or cannot be read
again: repeat the dispositions, update `ai-policy-review` and the ledger, and
(schema 0.2) show the change to the human before continuing.

Only with `implementation_ready: yes` does the agent edit, on an isolated branch
named by the contract's `head_ref`. While working it uses offline helpers:

```sh
agent-contrib scope-check task.json --repo-dir . --base BASE_SHA
agent-contrib evidence init task.json --repo-dir . --base BASE_SHA --output ../evidence.json
```

`scope-check` lists any path outside the contract scope. `evidence init` writes
a skeleton from observed Git facts; the agent fills in each validation result
from real runs and the independent review. The evidence file lives outside the
checkout.

## 8. Draft publication

```sh
agent-contrib drift task.json --policy-sha256 INVENTORY_SHA256
agent-contrib --format text verify task.json --evidence ../evidence.json --repo-dir . \
  --stage draft --host-context-stdin < /host-controlled/context.json
```

Before publishing, the agent repeats the same policy check (fresh `inspect`,
re-read, `drift`). **Stop** on any drift, incomplete read or changed policy, as in
step 7.

**Stop** unless the mandate includes `create_draft` and the draft gate passes
(`draft_create_ready: yes`). The host performs the push and opens one **draft**
PR; the CLI has no write operation. `pr-body` can render a description from the
contract and evidence. The agent then adds the publication claim to the host
context and reruns the draft stage until `publication.verified: yes`.

## 9. Completion

**Stop** until a human, through the host, issues a final sign-off for the exact
final head. Then:

```sh
agent-contrib --format text verify task.json --evidence ../evidence.json --repo-dir . \
  --stage completion --host-context-stdin < /host-controlled/context.json
```

`completion_ready: yes` means the recorded contribution is complete. Until then
the draft is reported as pending acceptance. Neither the agent nor the CLI marks
the PR ready for review, merges it or releases anything. `feedback
'acme/photos#PR'` reads reviews and exact-head checks afterwards.

## Where to go next

- [Command reference](cli.md): every option and output field.
- [Host authorization](host-authorization.md): mandates, sign-off and issuer duties.
- [Maintainers](maintainers.md): opt-in label policy, `audit` and the passive Action.
- [Upgrading from 0.2](upgrading.md).


To find declared welcomes among repositories you name, run
`tipjar discover acme/one acme/two --welcomed-only`. Names may come from projects
you use or a list you supply; there is no global jar registry. Selection means
“declared welcome; policy review required.” For a repository without a jar,
use the same ordinary discovery and preparation commands without this filter.
Absence grants no approval and needs no override. Closed or unknown source
jars block this contribution workflow even through a fork or host mandate.
