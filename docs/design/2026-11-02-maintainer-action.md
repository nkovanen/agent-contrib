# Passive verification GitHub Action for maintainers (#11): design proposal

- Date: 2026-11-02
- Status: proposal, revision 2. Hostile review round 1 (MA-01 to MA-06) is
  resolved in [Review resolution](#review-resolution). Slice 1 is implemented
  on `rsi/maintainer-action`; later slices are not.
- Base: `76632f8` (unreleased v0.3.0 candidate; task/evidence schemas 0.1 and
  0.2, host-context 0.1, output schemas 1).
- Input: issue #11 (product map C4).

## Summary

A maintainer adds one workflow to their repository. On each agent PR it checks,
without running any PR code, whether the PR's contract and evidence describe
this exact PR: its route, head commit, tree, base and diff scope. The result is
written as a job summary. The action is report-only. It never comments, labels,
approves, merges or writes anything to GitHub. A job's success or failure says
nothing about consistency; only the summary's explicit result does.

Recommendation:

- A composite action in this repository (`actions/verify/`), pinned by commit
  SHA, running the package source from that SHA with the runner's `python3`.
  There is no installation step and no PyPI.
- Trigger `pull_request` only, never `pull_request_target`, with no secrets.
- The contract and evidence come from two fenced JSON blocks in the PR body,
  never from committed files.
- **Slice 1 makes no GitHub API reads.** It uses only the event payload and the
  checked-out PR head, so its only permission is `contents: read`. Live checks
  are slice 2: source freshness, overlap with other PRs, repository approval and
  numeric source identity. Until then they are listed as not evaluated. Slice 2
  has its own preconditions (MA-01, MA-03, MA-05).
- Output: a job summary built from a fixed bullet-list template. No untrusted
  text goes to the job log, and there are no PR comments, annotations, step
  outputs or `fail-on` option in slice 1.

## What a maintainer gets (slice 1)

For a PR whose body carries an Agent Contrib contract, the summary has these
sections. Every check is `match`, `mismatch` or `not evaluated`, with a reason.

**Documents**
- The contract parses and matches its bundled task schema (0.1 or 0.2).
- The evidence parses and matches the evidence schema of the same version.
  Missing evidence is reported as not evaluated, never as consistent.

**PR route binding (event payload against contract), MA-02**
- The PR's base repository is the workflow repository (`GITHUB_REPOSITORY`).
- `source.repository` equals the base repository. Names are compared
  case-insensitively.
- Schema 0.2:
  - `execution.target_repository` and `target_repository_id` equal the base
    repository's name and numeric ID.
  - `execution.base_ref` equals `base.ref`.
  - `execution.head_repository`, `head_repository_id` and `head_ref` equal the
    PR's `head.repo` full name, numeric ID and `head.ref`.
- Schema 0.1:
  - `execution.mode` must be `upstream-contribution`. A `fork-experiment`
    contract authorizes no PR into another repository, so a PR from it is a
    route mismatch.
  - `execution.target_repository` must equal the base repository.
  - Schema 0.1 has no head repository, head ref or base ref fields. These are
    reported as "not bound by schema 0.1", not as matches.
- A missing or deleted head repository (`head.repo` null), or any missing
  payload field, is not evaluated. It is never inferred from the local
  checkout's origin.

**Evidence binding (evidence against PR head and contract)**
- `evidence.git_head` equals the payload's `head.sha` and the checkout's
  `HEAD`.
- `evidence.git_tree` equals the tree of that commit.
- `evidence.contract_sha256` equals the canonical hash of the contract block.
- `evidence.base_commit` is an ancestor of the head, and `source.commit` is an
  ancestor of `evidence.base_commit`. A commit missing from the checkout's
  history is not evaluated, not a mismatch.
- `evidence.worktree_clean` is reported as the recorded self-attested value.

**Scope**
- `scope-check` logic from the existing library, run on the checkout with
  `--base evidence.base_commit`. It reports `within_scope` and up to 50
  violations.

**Not evaluated in this version (always listed)**
- Live source freshness: issue, instructions, default branch and policy.
- Overlap with other open PRs.
- Repository approval status.
- Numeric source identity (repository, owner and issue IDs).
- Authorization stages (mandate, credential, permission).
- Whether recorded validations ran.
- Review and sign-off truth.
- Artifact hashes.
- Merge compatibility with the base branch: the action checks the PR head, not
  the merge commit.

**Result.** The result is one of:

- "No inconsistency found in the checks above": every check in the first four
  sections is `match`.
- "N inconsistencies found".
- "Not checked: reason": the event payload is malformed, the blocks are
  missing, ambiguous or unparsable, the checkout is not the PR head, or the
  action hit an internal error.

A check that is not evaluated never counts toward "No inconsistency found".
The result is always `not-checked` when evidence is missing, so a contract
alone can never produce the "No inconsistency found" verdict.

## What it must never claim

The summary header and docs carry these fixed statements:

1. **Evidence is self-attested.** A match means the evidence record describes
   this exact route, commit, tree, base and contract. It does not mean the
   recorded tests, review or sign-off happened.
2. **Verification is not review.** The action is not a code review, an
   approval, an AI-policy compliance check or authorization to merge.
3. **Job status carries no consistency meaning (MA-06).** The step exits 0
   whatever it finds. A failed job means the action itself could not run, for
   example because Python is missing. Even the summary's result is advisory for
   a PR that changes `.github/` (see T1).
4. **No identity claims.** Author, implementer and reviewer names in the
   evidence are not verified.

## Where the contract and evidence come from

| Option | Trust and feasibility | Verdict |
| --- | --- | --- |
| A. Committed files in the PR | Evidence binds `git_head` and `git_tree`; a file committed in the commit it describes cannot contain that commit's SHA, and a later commit moves HEAD. Both files would also widen the diff and scope. | Rejected |
| B. Fenced JSON blocks in the PR body | Author-controlled, like any contract or evidence. Not part of the commit. Bounded by GitHub's 65,536-character body limit. | **Recommended** |
| C. Linked gist or artifact pinned by hash | A second fetch path. Gists are mutable; artifacts can come from untrusted runs (artifact poisoning). | Deferred |
| D. A status or check from the contributor's own CI | Contributor-controlled and forgeable. | Rejected |

The blocks gain no trust from where they live. The action's value is checking
that the claims are consistent with the PR. Slice 1 takes the body, head SHA
and route from the same event payload (`$GITHUB_EVENT_PATH`) that selected the
checked-out commit, so they form one snapshot. An `edited` event delivers the
new body. A report is never reused for a later body.

### Block format and parser rules

````text
```agent-contrib-task
{ ...the reviewed task contract JSON... }
```

```agent-contrib-evidence
{ ...the evidence JSON... }
```
````

- CRLF line endings are normalized first.
- An opening fence is a line that is exactly three backticks plus the info
  string, starting in column 0, with trailing spaces or tabs allowed. The block
  closes at the next line consisting only of three backticks.
- At most one task and one evidence opening line may appear anywhere in the
  raw body, including inside HTML comments and longer fences. A second one is
  `ambiguous`, and nothing is checked. A hidden copy cannot sit behind a
  visible one.
- Each block is capped at 32 KiB, and the whole body at 65,536 characters.
- Blocks are parsed with the CLI's strict JSON reader, which rejects duplicate
  keys, NaN/Infinity and lone surrogates.
- An unterminated fence, an oversized block or invalid JSON is not checked and
  gets a fixed message with no excerpt.

## Threat model

### Assets and attacker

The attacker controls the PR: its code, files, branch name, title, body and,
for fork PRs, the fork. They may be a first-time or returning contributor. The
assets are:

- the integrity of the summary a maintainer reads;
- the base repository: contents, settings, caches, releases and token;
- any secrets;
- the API quota (slice 2).

### T1. Trigger: `pull_request`, never `pull_request_target`

| | `pull_request` | `pull_request_target` |
| --- | --- | --- |
| Workflow definition | From the PR merge ref: **PR-controlled** when the PR edits `.github/workflows` | From the base branch: trusted |
| Token for fork PRs | Read-only | Base-repository token |
| Secrets | None for fork PRs | Available to the workflow |
| Cache scope | The PR ref | The base branch: writes poison caches that privileged default-branch workflows restore |
| PR code | Not checked out by default | Checking it out is the "pwn request" pattern |

The action needs no privileges. `pull_request_target` would put a base token
and base-scope cache access into the job that checks out attacker files and
parses attacker JSON. Any parser or Git bug would then run privileged. Under
`pull_request` the same bug meets a read-only token and nothing to steal.

**Residual risk.** A PR that edits the workflow file, or its `uses:` pin,
controls what runs and can make the summary say anything. No setting makes the
current PR's own summary trusted evidence. These settings limit the damage
(MA-04):

- **Merge protection**: a ruleset or branch protection on the default branch
  with:
  - "Require a pull request before merging";
  - "Require review from Code Owners";
  - a `CODEOWNERS` entry covering both `/.github/` and `/.github/CODEOWNERS`,
    owned by maintainers;
  - an empty or minimal bypass list, since admins and bypass actors skip the
    rule.

  Declaring code owners alone only requests a review; it does not block a
  merge. This protects the base branch from an unreviewed workflow change. It
  does not stop the PR's modified workflow from running and printing a
  misleading summary before review.
- **Workflow-run approval** is a separate setting from merge approval. "Require
  approval for all external contributors" holds every outside run until a
  maintainer approves it. The first-time-contributor default is bypassed by
  anyone who has had a PR merged before. Approving a run executes the PR's
  version of the workflow, so check whether the PR touches `.github/` first.
- **Readers.** Treat a summary on a PR that changes `.github/**` as
  meaningless, and never merge on this report alone.
- **Required workflow from another repository.** An organization ruleset that
  requires a workflow from a separate protected repository at a pinned SHA
  removes PR control of the definition. Required workflows ignore `types:`
  filters and use only default activity types, which exclude `edited`. A
  body-only edit would then not re-run, so the summary could be stale. Untested
  here and not recommended yet.

`workflow_run` two-stage designs exist for writes after an unprivileged run.
We need no writes, and the second stage would consume untrusted artifacts. Not
used.

### T2. Token and permissions

Slice 1 example workflow:

```yaml
permissions:
  contents: read
```

`actions/checkout` needs only this. Slice 1 makes no API calls and never
passes a token to the action. There is no `secrets.*`, `id-token` or `write`
scope. `actions/checkout` runs with `persist-credentials: false`, so no token
is left in the checkout's `.git/config`. Slice 2 adds `pull-requests: read`
and `issues: read` only when it starts reading.

### T3. Never execute PR code

- **Python cannot import from the checkout.** The step runs
  `python3 -I "$GITHUB_ACTION_PATH/report.py"`, and the script changes its
  working directory to `$RUNNER_TEMP`. `-I` removes `PYTHONPATH`, the user site
  directory and the script and current directories from `sys.path`; this was
  checked on 3.10 and 3.12 with a planted `json.py`, and the reviewer also
  planted a poisoned `agent_contribute`. `report.py` inserts only the action's
  own repository root, then imports `agent_contribute`.
- **Git reads stay hardened.** They go through the library's existing
  `git_read`: no global or system config, no hooks, no fsmonitor, no replace
  objects or grafts. All arguments are argv with `shell=False`.
- **Checkout options.** `actions/checkout` uses `submodules: false` and
  `lfs: false`, both linted.
- **The checkout path.** It must resolve to a directory under
  `$GITHUB_WORKSPACE` without `..`, and must be the Git worktree root. Its
  `HEAD` must equal the payload's `head.sha`. A merge SHA or other commit is not
  checked.
- **No builds.** No package manager, build, test or contract argv runs.
- **Scope of the claim.** This is import-path and Git-config hardening, not an
  OS sandbox. A Python or Git parser bug on attacker data remains a risk, and a
  read-only job with nothing to steal bounds it. GitHub-hosted runners only:
  self-hosted runners must not run fork-PR workflows.

### T4. Script and workflow-command injection

Untrusted strings: PR title, body, branch names, repository names, commit
messages, file paths and all JSON values.

- No `${{ ... }}` appears inside any `run:` block of `action.yml` or the
  example workflow. A static test enforces it. The single `run:` line takes
  its one input through `env:`.
- The script reads PR facts from the event payload file as JSON, never from
  expressions or argv.
- Nothing is written to `$GITHUB_ENV`, `$GITHUB_PATH` or `$GITHUB_OUTPUT`.
  Slice 1 has no outputs at all.
- **Logs.** The script prints only fixed lines, such as "Agent Contrib report
  written to the job summary", plus the result enum. Untrusted text never
  reaches stdout or stderr. Neither the `::command` form (line start) nor the
  legacy `##[command]` form (anywhere in a line) can be injected.
  - Git subprocess output is captured, never inherited.
  - Python's default traceback is replaced by a fixed message, because a
    traceback could echo attacker-controlled values.
  - Slice 2, if it ever prints JSON to the log, must wrap it in fresh
    `::stop-commands::` tokens, restore them in `finally`, and test both
    command syntaxes.

### T5. Misleading summary text

`$GITHUB_STEP_SUMMARY` renders GitHub-flavoured Markdown. Rules:

- The summary is a fixed template of headings and bullet lists. It has no
  tables, so pipes cannot break structure.
- Labels, states, booleans, enums, integers and hex hashes come from parsed
  data and are re-validated before rendering. Hex values must match
  `^[0-9a-f]{40}$` or `^[0-9a-f]{64}$`, or they are not shown.
- Other values, such as repository names, refs, paths and our schema-error
  strings, can carry attacker text. Each is cleaned with the existing one-line
  sanitizer (`textfmt.line`: removes control and format characters including
  bidi overrides, and collapses whitespace). Backticks become `'`, length is
  capped at 200 characters, and the result is rendered as an inline code span,
  which renders no links, images, HTML or mentions.
- Contract prose, issue text, PR title and body are never rendered.
- Each section shows at most 50 items, then "N more not shown". The summary is
  capped at 64 KiB, under GitHub's 1 MiB per-step limit.
- Result wording is fixed (see above). It never says passed, approved,
  verified or safe.

### T6. Artifacts and caches

No artifacts are uploaded or downloaded, and `actions/cache` is never used. No
PR code runs, so nothing writes caches.

### T7. Supply chain

- **Action pin.** Maintainers pin
  `uses: nkovanen/agent-contrib/actions/verify@<40-hex SHA>`. GitHub resolves a
  SHA from any fork in the repository network ("impostor commits"), and a
  `/commits/SHA` read under the upstream URL does not establish provenance.
  The docs tell maintainers to compare the SHA with the canonical repository's
  release tag ref:
  - `gh api repos/nkovanen/agent-contrib/git/ref/tags/vX.Y.Z`;
  - for an annotated tag, dereference it with `git/tags/<sha>`;
  - review the code, then keep the pin.

  A later tag move does not change an existing pin. Dependabot's
  `github-actions` ecosystem can propose reviewed bumps.
- **No installation.** Zero runtime dependencies: no pip, no PyPI, no
  `setup-python`. The runner image supplies `python3` (checked to be 3.10 or
  newer) and `git`.
- **Other actions.** Only `actions/checkout`, pinned by SHA with a version
  comment. The lint rejects unpinned `uses:`.

### T8. Rate limits

Slice 1 makes no API calls. For slice 2 (MA-05), the 100-remaining start
threshold is not a spending limit. One bounded `verify` can make 144 or more
reads: 40 PR pages, 40 label pages, 60 instruction files, metadata, plus 0.2
identity and history reads. The CLI's one- and two-second retries are not
valid rate-limit handling. Slice 2 therefore needs:

- a CLI-side read cap for CI runs, so a run stops with "Not checked: read cap
  reached";
- no retry on 403/429 rate-limit responses, so the run stops as not checked
  rather than waiting;
- a documented worst case per PR, multiplied by concurrent PRs, against the
  repository's 1,000-per-hour Actions token quota;
- a real PR and label pagination fixture.

### T9. Stale state

- Facts come from one payload. If the checkout `HEAD` is not the payload
  `head.sha`, the run is not checked.
- Evidence for an older commit is a mismatch. This includes after "Update
  branch".
- A deleted fork is not evaluated.
- A PR without the blocks is skipped by the workflow's `if:` guard: no job
  runs, so there is no summary. This is documented. The guard is evaluated by
  the runner, not by a shell.

## Slice 2 preconditions (live checks)

- **Self-overlap (MA-01).** The existing scanner counts the PR under review as
  an overlap, in both 0.1 and 0.2.
  - A report-only adapter removes exactly one entry: the one whose number and
    URL equal the payload PR's, in the base repository, and only after the
    route binding matched.
  - All other duplicates stay visible. The adapter never fabricates a mandate,
    never uses the own-PR publication exemption, and never suppresses the
    generic overlap error string. It recomputes "other overlapping PRs" from the
    list.
  - Test fixtures:
    - a published PR referencing its own issue;
    - a same-title but different PR, which must stay;
    - the same number in another repository, which must stay.
- **Source identity independent of credential (MA-03).** An Actions token
  cannot read `GET /user`, and `verify` 0.2 then skips the numeric source
  identity comparison while `source_errors` stays empty. Slice 2 either calls
  the read-only identity reads on their own (repository and issue IDs against
  the contract) or lists identity as not evaluated. An empty `source_errors`
  is never read as a pass. Fixture: unavailable `/user` with wrong contract
  IDs.
- **Bounded reads (MA-05):** see T8.
- **No string classification over full `verify` output.** Slice 2 reads only
  narrow, named facts, or labels a fact not evaluated.

## Options for packaging

| Option | Trade-off | Verdict |
| --- | --- | --- |
| Composite action plus Python script in this repository | No dependencies, reuses the library, testable offline | **Recommended** |
| Docker action | Pulls an image at run time; slower | Rejected |
| JavaScript action | Needs Node and bundling; logic in a second language | Rejected |
| Copy-paste workflow installing from PyPI | Copies drift; needs G3 publishing and hash-pinned installs | Fallback after G3 |

## Slice 1 file set

```text
actions/verify/action.yml                composite action: input checkout-path; one run step
actions/verify/report.py                 payload, blocks, bindings, checkout checks, summary
docs/examples/agent-contrib-verify.yml   example maintainer workflow
tests/test_action_report.py              offline tests of report.py
tests/test_workflow_lint.py              static checks of the two YAML files
```

Also an `MANIFEST.in` entry so the sdist carries `actions/` and the example
for its tests, and the matching `tools/check_install.py` sdist list. No CLI,
schema or library change. Maintainer docs (`docs/maintainers.md`,
`SECURITY.md`) follow once slice 4's live smoke has run.

## Test plan (slice 1, offline)

1. **Parser.**
   - Zero, one or two blocks; CRLF line endings.
   - Indented fences, trailing whitespace and near-miss info strings.
   - Unterminated fences.
   - Blocks inside HTML comments and inside longer fences, which count toward
     ambiguity.
   - A 32 KiB block and one byte over; a body over 65,536 characters.
   - Duplicate keys, NaN and lone surrogates.
2. **Payload.**
   - Missing, null or wrongly typed fields for each fact.
   - A deleted head repository.
   - A non-PR event.
3. **Route binding, with a counterexample for each rule.**
   - Schema 0.2: wrong head repository name or ID, head ref, base ref, target
     name or ID, or source repository.
   - Schema 0.1: a `fork-experiment` contract, the wrong target, and the
     "not bound" rows.
4. **Checkout, using temporary Git repositories as the existing tests do.**
   - Consistent evidence.
   - A wrong head, tree or contract hash.
   - A base that is not an ancestor, and a base missing from history (not
     evaluated).
   - A scope violation.
   - A checkout path outside the workspace, a subdirectory, or a `HEAD` that is
     not the payload SHA.
5. **Result mapping.**
   - All match gives "No inconsistency found".
   - Any mismatch gives a count.
   - Missing evidence, a parse failure, a bad payload or an internal error
     each give "Not checked". Internal errors are injected by making a check
     raise.
   - The step exits 0 in every case.
6. **Summary rendering.** An injection corpus goes into every slot taken from
   attacker data:
   - Markdown links and images, raw HTML, headings, pipes and backticks;
   - `@mentions`, bidi overrides, zero-width characters and newlines;
   - `::add-mask::` and `##[error]`;
   - 10,000-character strings.

   Assertions: every line matches the template's line shapes; each untrusted
   value is one code span with no backtick or newline; the 64 KiB cap holds;
   prose never appears.
7. **Log silence.** Run the script's `main` on the corpus and capture
   stdout/stderr. They contain only the fixed lines and none of the
   attacker-controlled bytes. Exceptions don't leak a traceback.
8. **Workflow lint.** Line-based; the test first asserts the files stay in a
   small block-style YAML subset. Rules:
   - no `${{` inside any `run:` value;
   - triggers: `pull_request` only;
   - `permissions` is exactly `contents: read`;
   - no `secrets.`, `write`, `GITHUB_ENV`, `GITHUB_PATH`, `GITHUB_OUTPUT` or
     `actions/cache`;
   - every `uses:` pinned to 40 hex characters;
   - checkout has `persist-credentials: false`, `submodules: false`,
     `lfs: false` and `ref: ${{ github.event.pull_request.head.sha }}`.

   Each rule has a seeded bad variant that the lint must reject. `actionlint`
   and `zizmor` remain manual release-review tools; the hand-written lint
   covers only these two owned files.

## Slices

1. **Offline report.** Done: payload, parser, route
   and evidence binding, checkout and scope checks, summary renderer,
   `action.yml`, example workflow, tests 1 to 8.
2. **Live checks**, under the preconditions above.
3. **Maintainer and security docs.**
4. **Live smoke on a scratch repository** (user-authorized). It covers a
   consistent fork PR, a moved head, a PR that edits the workflow, and the
   ruleset experiment.
5. **Optional, after 4:** `fail-on: inconsistent` and a public `result` output.

Deferred: PR comments or custom check runs, gist/artifact evidence, AI-policy
excerpts, `pr-body` emitting the blocks, shallow fetches.

## Review resolution

| Finding | Verified | Resolution in revision 2 |
| --- | --- | --- |
| MA-01 (M) the PR is its own overlap | Reproduced: 0.1 and 0.2 report PR #30 against its own issue | Overlap is not evaluated in slice 1. Slice 2 precondition: a report-only exclusion of exactly the payload PR (number, URL, base repository, after route binding), other PRs kept, no mandate or exemption use, with fixtures. |
| MA-02 (M) the route was not bound | Reproduced: different head repository and base ref passed every listed binding | Full route binding against the payload: base repository and target (name and ID), base ref, head repository (name and ID), head ref for 0.2. Separate 0.1 rules (mode, target, "not bound" rows). Missing fields are not evaluated. |
| MA-03 (M) source identity was silently skipped | Reproduced: unavailable `/user` left wrong IDs with empty `source_errors` | Identity is not evaluated in slice 1. Slice 2 precondition: independent identity reads, or "not evaluated"; never infer a pass from an empty list. |
| MA-04 (M) CODEOWNERS alone does not require review | Accepted (GitHub docs) | Exact merge-protection settings, CODEOWNERS owning itself, bypass caveat, run approval separate from merge approval, all-external approval, and the required-workflow `edited` limitation. |
| MA-05 (M) the rate guard did not bound reads | Reproduced: 144 reads after a 100-remaining guard | Slice 1 makes no API reads. Slice 2 needs a read cap, no short rate-limit retries, a documented worst case and a pagination fixture. |
| MA-06 (L) a green job implied consistency | Accepted | Job status carries no meaning; the step always exits 0. "No inconsistency found" needs every check to match. Missing evidence, errors and unavailable checks are "not checked". `fail-on` and outputs are deferred to slice 5. |
| Reviewer notes | Accepted | No untrusted log output (removes the `::` and `##[` classes); bullet lists instead of tables; checkout-path confinement; HEAD must equal payload SHA; merge compatibility listed as not evaluated; no-block PRs are skipped with no summary; slice-1 cut as proposed. |
