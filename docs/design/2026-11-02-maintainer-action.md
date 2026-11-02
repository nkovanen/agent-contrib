# Passive verification GitHub Action for maintainers (#11): design proposal

- Date: 2026-11-02
- Status: proposal, revision 1. Nothing here is implemented.
- Base: `d9285be` (unreleased v0.3.0 candidate; task/evidence schemas 0.1 and
  0.2, host-context 0.1, output schemas 1).
- Input: issue #11 (product map C4).

## Summary

A maintainer adds one workflow to their repository. On each agent PR it runs
the pinned Agent Contrib verifier against the PR head and writes a job
summary: whether the PR's contract and evidence are consistent with the
checkout and with live GitHub state, whether the change stays in scope, whether
open PRs overlap and what the repository policy says. It is report-only: it
never comments, labels, approves, merges or writes anything to GitHub, and it
never runs code from the PR.

Recommendation:

- A composite action in this repository (`actions/verify/`), pinned by commit
  SHA. It runs the package source from that SHA with the runner's `python3`.
  Nothing is downloaded from PyPI and there is no network access beyond the
  GitHub REST API reads `gh` already makes.
- Trigger `pull_request` only, never `pull_request_target`. Read-only token
  scopes, no secrets.
- The contract and evidence come from two fenced JSON blocks in the PR body.
  They are never committed files.
- Output: a job summary built from a closed template, plus the full JSON
  result in the job log. No PR comments, annotations or check-run text.
- The job always succeeds by default. `fail-on: inconsistent` lets a
  maintainer turn found inconsistencies into a failed job; a passing job is
  never a claim.

## What a maintainer gets

For a PR whose body carries an Agent Contrib contract:

| Section | Source | Shown as |
| --- | --- | --- |
| Binding | PR head SHA vs `evidence.git_head`; contract hash vs `evidence.contract_sha256`; contract `execution.head_ref` vs PR head branch | match / mismatch per item |
| Contract | `verify`: `schema_valid`, `contract_sha256`, source freshness errors (issue, instructions, branch, policy) | booleans, hash, our fixed error strings |
| Evidence consistency | `verify --evidence --repo-dir`: `evidence_valid` (0.1) or `technical_evidence_valid` (0.2), `evidence_errors` | boolean, fixed error strings |
| Scope | `scope-check --base evidence.base_commit`: `within_scope`, violations | boolean, violation count, paths as inline code |
| Overlap | `verify`: `duplicates` | count and PR numbers |
| Policy | `verify`: approval `status` (`approved`, `candidate`, `unknown`) | enum |
| Not evaluated in CI | fixed list (see below) | fixed text |

Every field comes from the CLI's JSON output, which is validated against the
packaged output schemas (#24) before rendering. A result that fails its schema
is reported as a tool error, never rendered partially.

**Not evaluated in CI, always stated.** These are not shown as failures:

- Whether the validations were really run: the action never executes contract
  argv or project code.
- Independent review and human sign-off content. They are self-attested or
  host-asserted records.
- Schema 0.2 authorization stages (mandate, credential, permission). The host
  context never reaches CI, and `GET /user` is not available to an Actions
  installation token.

For a PR without the blocks, the summary says "No Agent Contrib contract in
the PR body; nothing was checked" and the job succeeds. An `if:` guard in the
example workflow skips such PRs before the job starts.

## What it must never claim

The summary header and docs carry these fixed statements:

1. **Evidence is self-attested.** "Consistent" means the evidence record
   describes this exact commit, tree, base and contract. It does not mean the
   recorded tests, review or sign-off happened.
2. **Verification is not review.** The action is not a code review, an
   approval, an AI-policy compliance check or authorization to merge.
3. **A passing job is not a claim.** It means only that this workflow, as it
   was defined for this run, found no inconsistency. For a PR that changes
   `.github/` the workflow definition itself is PR-controlled (see T1).
4. **Repository approval is policy data, not consent.** `approved` reflects a
   designated label and the default-branch policy, exactly as `verify`
   reports it locally.
5. **No identity claims.** The PR author, implementer and reviewer names in
   the evidence are not verified.

## Where the contract and evidence come from

| Option | Trust and feasibility | Verdict |
| --- | --- | --- |
| A. Committed files in the PR (for example `.agent-contrib/task.json`, `evidence.json`) | Evidence binds `git_head` and `git_tree`; a file committed in the commit it describes cannot contain that commit's SHA. Committing it in a later commit makes HEAD differ from `git_head`. Both files also enter the diff, so they would have to be inside the contract scope. | Rejected |
| B. Fenced JSON blocks in the PR body | Author-controlled, like any contract or evidence. Not part of the commit, so there is no binding or scope paradox. Editable after the fact, which `edited` events re-check. Size bounded by GitHub's 65,536-character body limit. | **Recommended** |
| C. Linked gist or artifact pinned by hash | Adds a second fetch path and URL parsing. Gists are mutable; artifacts expire and can come from untrusted workflow runs (artifact poisoning). | Deferred (YAGNI) |
| D. A status or check result from the contributor's own CI | Contributor-controlled and forgeable. | Rejected |

Option B gives no extra trust, and needs none: the contract and evidence are
the contributor's claims wherever they live. The action's value is checking
that those claims are consistent with the PR head, the live source and the
scope. The body is read once, through the API, in the same response that
supplies the PR head SHA, so the blocks and the SHA come from one snapshot.

### Block format and parser rules

````text
```agent-contrib-task
{ ...the reviewed task contract JSON... }
```

```agent-contrib-evidence
{ ...the evidence JSON... }
```
````

- A fence opens on a line that is exactly the backticks and the info string
  (trailing spaces allowed), in column 0. It closes on the next line consisting
  only of three backticks. CRLF line endings are normalized first.
- Exactly one task block is required. At most one evidence block is allowed.
  More than one of either, anywhere in the raw body, is `ambiguous` and nothing
  is checked. This includes blocks inside HTML comments or longer fences: a
  hidden copy cannot sit behind a visible one.
- Each block is capped at 32 KiB and parsed with the CLI's strict JSON reader:
  duplicate keys, NaN/Infinity and lone surrogates are rejected.
- An unterminated fence, an oversized block or invalid JSON is reported as a
  parse error with our fixed message and no excerpt.
- The parsed documents are written to a fresh private directory under
  `$RUNNER_TEMP`, outside the checkout, and passed to the CLI as file paths.

Contributors can paste the blocks themselves. A later, optional slice can let
`pr-body` emit them.

## Threat model

### Assets and attacker

The attacker controls the PR: its code, files, branch name, title and body,
and for fork PRs, the fork. Possibly they are a first-time contributor. The
assets are:

- the integrity of the summary a maintainer reads;
- the base repository: its contents, settings, caches, releases and token;
- any secrets;
- the maintainer's API rate limit.

### T1. Trigger: `pull_request`, never `pull_request_target`

| | `pull_request` | `pull_request_target` |
| --- | --- | --- |
| Workflow definition | From the PR merge ref: **PR-controlled** when the PR edits `.github/workflows` | From the base branch: trusted |
| Token for fork PRs | Read-only | Base-repository token, write by default unless restricted |
| Secrets | None for fork PRs | Available to the workflow |
| Cache scope | The PR ref | The base branch, so writes poison caches that privileged workflows on the default branch restore |
| PR code | Not checked out by default | Checking it out is the known "pwn request" pattern |

The action needs only reads, so it gains nothing from privileges.
`pull_request_target` would put a trusted token and base-scope cache access
in the same job that checks out attacker-controlled files and parses
attacker-controlled JSON. Any parser, Git or tool bug would then run with
privileges. With `pull_request` the same bug runs in a job with a read-only
token and nothing worth stealing.

The cost is T1's residual risk: a PR that edits the workflow file, or the
`uses:` line that pins this action, controls what runs and can make the job
report anything. The mitigations, all documented for maintainers:

- A PR that changes `.github/**` gets no meaningful result from this check.
  Review such PRs as workflow changes. CODEOWNERS on `.github/` makes that
  review required.
- Keep "Require approval for first-time contributors" (the GitHub default for
  public repositories) or stricter, so fork workflows wait for a maintainer.
  Approving a run executes the PR's version of the workflow, so check whether
  the PR touches `.github/` before approving.
- Never make a passing run of this job the basis for merging. It is report-only
  by design.
- Where an organization can require a workflow from a separate, protected
  repository at a pinned ref (repository rulesets), the definition is no longer
  PR-controlled. We have not tested this. Slice 4 records the result if a
  maintainer can try it.

`workflow_run` two-stage designs exist to get write access (comments, custom
check runs) after an unprivileged run. We need no writes, and the second stage
would consume artifacts from the untrusted run (artifact poisoning). Not used.

### T2. Token and permissions

The example workflow declares exactly:

```yaml
permissions:
  contents: read
  pull-requests: read
  issues: read
```

These are the read scopes the existing reads need: the PR, issues and
timeline, repository contents and trees. Fork-PR tokens are read-only
regardless. No `id-token`, `checks`, `statuses` or any `write` scope, and no
`secrets.*` reference anywhere.

- The action passes `github.token` to `gh` only through the `GH_TOKEN`
  environment of its single step.
- `actions/checkout` runs with `persist-credentials: false`, so the token is
  never written into the PR checkout's `.git/config`.
- The CLI never echoes `gh` stderr (an existing rule).
- The action cannot enforce its caller's `permissions:` block. The lint (test
  plan) checks the example, and the docs tell maintainers to copy it.

### T3. Never execute PR code

The action reads the checkout as data:

- **Python cannot load files from the checkout.** The script runs as
  `python3 -I "$GITHUB_ACTION_PATH/report.py"` with its working directory set
  to `$RUNNER_TEMP`. `-I` drops `PYTHONPATH`, the user site directory and the
  script and current directories from `sys.path`; this was checked on 3.10
  and 3.12 with a planted `json.py` in both. `report.py` adds only the action's
  own repository root, then imports `agent_contribute`. It runs each CLI command
  as `[sys.executable, '-I', '-c', BOOTSTRAP, *argv]` with `shell=False`.
  `BOOTSTRAP` is a fixed string that inserts the same root and calls
  `agent_contribute.cli.main`. A `json.py` or `agent_contribute/` planted in the
  PR therefore cannot be imported.
- **Git reads stay hardened.** They use the CLI's existing environment: no
  global or system config, no hooks, no fsmonitor, no replace objects or
  grafts. `.gitattributes` filters and diff drivers need config that a checkout
  cannot supply.
- **Checkout options.** `actions/checkout` uses `submodules: false` and
  `lfs: false` (the defaults, stated explicitly and linted).
- **Branch fixup for schema 0.2.** Evidence 0.2 requires the checkout branch
  to equal `execution.head_ref`. The script first requires that value to equal
  the PR's API `head.ref` and to pass `git check-ref-format --branch`. It then
  runs `git switch --create <ref> <sha>` through the same hardened argv
  runner. A mismatch is reported; nothing is guessed.
- **Artifact paths.** Evidence artifact paths stay confined by the existing
  `verify` rule: the resolved path must lie inside the checkout and be a
  regular file. A symlink to `/etc/...` is rejected.
- **No build steps.** No package manager, build or test step ever runs on the
  checkout. Contract `validation` argv is never executed (an existing CLI
  invariant).

### T4. Script injection

Untrusted strings: PR title and body, branch names, head repository name,
commit messages, labels, file paths in the checkout and all JSON values.

- No `${{ ... }}` expression appears inside any `run:` block in `action.yml`
  or the example workflow. Values reach the script only through `env:` and
  are read with `os.environ`. Even safe-looking integers like the PR number go
  through `env:`, so the lint rule stays simple and absolute.
- The script takes the PR number and head SHA from the event payload file
  (`$GITHUB_EVENT_PATH`, parsed as JSON), never from expressions.
- Composite `inputs.*` go through `env:` too, and the script checks them
  against an allowlist (`fail-on` ∈ {`never`, `inconsistent`}; `checkout-path`
  is a relative path without `..`).
- The script never writes to `$GITHUB_ENV`, `$GITHUB_PATH` or `$GITHUB_OUTPUT`
  with any value derived from untrusted input. A newline in such a value could
  set `BASH_ENV`, `LD_PRELOAD` or `NODE_OPTIONS` for later steps. The only
  output is `result`, a closed enum (`consistent`, `inconsistent`,
  `not-applicable`, `error`).
- **Workflow commands in logs.** Before printing the CLI's JSON to stdout, the
  script emits `::stop-commands::<random 32-hex token>` and resumes afterwards.
  The JSON is printed with `ensure_ascii=True`, so no string value can start a
  new line, and every line starts with whitespace, `{` or `}`. A `::set-env` or
  `::add-mask::` in untrusted text is therefore never interpreted. The script
  emits no `::warning`/`::error` annotations.

### T5. Misleading summary text

`$GITHUB_STEP_SUMMARY` renders GitHub-flavoured Markdown. Untrusted text
could add links, tracking images, HTML, fake "all gates passed" headings,
table breaks or bidi-reordered text. Rules:

- The summary is built from a fixed template. Headings, labels, booleans,
  enums, integers, hex hashes, `owner/repo` names that pass the repository
  pattern, and numbers come from the schema-validated JSON.
- Free text never appears except our CLI's diagnostic strings and the paths
  inside them. Those can carry repository-authored paths. Each is cleaned with
  the existing one-line sanitizer (`textfmt.line`: removes control and format
  characters, including bidi overrides, and collapses whitespace). Backticks
  become `'`, length is capped at 300 characters, and the result is rendered
  as an inline code span. Code spans render no links, images, HTML or
  mentions.
- Contract prose (objective, criteria text, questions), issue text, PR title
  and body are never rendered. Criteria and validation IDs already match
  safe schema patterns and may be listed.
- At most 50 diagnostics per section are shown, then "N more in the job log".
  The whole summary is capped at 64 KiB; GitHub's limit is 1 MiB per step.
- The verdict line uses only our wording: "No inconsistency found", "N
  inconsistencies found" or "Not checked: reason". It never says passed,
  approved, verified or safe.

### T6. Artifacts and caches

The action uploads and downloads no artifacts and uses no `actions/cache`. No
PR code runs, so nothing in the job writes a cache. Under `pull_request`, any
cache write would be scoped to the PR ref anyway. This is a second reason T1
rejects `pull_request_target`.

### T7. Supply chain

- **Action pin.** Maintainers pin
  `uses: nkovanen/agent-contrib/actions/verify@<40-hex SHA>`. GitHub resolves a
  SHA from any fork in the repository's network ("impostor commits"). The docs
  tell maintainers to check that the SHA is the one a release tag points to,
  for example with `gh api repos/nkovanen/agent-contrib/git/ref/tags/vX.Y.Z`.
  For an annotated tag, dereference the tag object with `git/tags/<sha>`. Each
  release note also states the commit SHA. Dependabot's `github-actions`
  ecosystem can then propose SHA bumps for review.
- **Tool installation: none.** The action runs the package source at that SHA.
  It has zero runtime dependencies. There is no `pip install`, no PyPI, no
  `setup-python` and no build backend download. The runner image supplies
  `python3` (3.10 or later, checked at start), `git` and `gh`. Self-hosted
  runners must provide them.
- **Network.** Only the GitHub REST GETs the CLI already makes through `gh`.
- **Other actions.** The only one is `actions/checkout`, in the maintainer's
  workflow, pinned by SHA with a version comment (as in this repository's own
  CI). The lint rejects unpinned `uses:`.
- **Runners.** GitHub-hosted runners only. Self-hosted runners must not run
  fork-PR workflows; that is a documented recommendation, not something the
  action can enforce.

### T8. Rate limits and cost

- `verify` makes about 10 to 75 REST reads: metadata, commit, PR and label
  pages, tree, up to 60 instruction files, issue, plus schema 0.2 identity and
  publication reads. The action adds one PR read. An Actions token has 1,000
  requests per hour per repository.
- `concurrency: agent-contrib-${{ github.event.pull_request.number }}` with
  `cancel-in-progress: true` keeps one run per PR. The expression is in a YAML
  field, not a `run:` block.
- The script passes `--report-budget --min-remaining 100`. Below that budget
  the summary says "Not checked: API budget low". This is neutral, not a
  failure.
- `timeout-minutes: 10` on the job.
- `fetch-depth: 0` is needed because the base-commit ancestry checks walk
  history. That costs clone time on large repositories. A later slice can
  fetch only the base and head commits if this proves slow.

### T9. Stale and racing state

- The script reads the PR (body, head SHA, head ref) once.
- If the API head SHA differs from the checked-out SHA, the run is "Not
  checked: PR head moved", and the next `synchronize` event re-runs it.
- Evidence for an older commit is reported as stale. This includes after
  "Update branch".
- A deleted fork (`head.repo` is null) is "Not checked".

## Options for packaging

| Option | Trade-off | Verdict |
| --- | --- | --- |
| Composite action with a Python script, in this repository | No dependencies, reuses the CLI and output schemas, testable offline | **Recommended** |
| Docker action | Pulls a base image at run time (supply chain, network), slower | Rejected |
| JavaScript action | Needs Node and bundled dependencies; duplicates logic in a second language | Rejected |
| Documented copy-paste workflow that installs from PyPI | Copies drift; needs PyPI publishing (G3, not done) and hash-pinned installs | Possible fallback after G3 |

## Minimal file set

```text
actions/verify/action.yml      composite action: inputs fail-on, checkout-path; one run step
actions/verify/report.py       locate blocks, bind, run CLI, validate, render summary, decide exit
docs/examples/agent-contrib-verify.yml   example maintainer workflow
tests/test_action_report.py    offline tests of report.py
tests/test_workflow_lint.py    static lint of action.yml and the example workflow
```

Plus docs: a section in `docs/maintainers.md`, a threat-model section in
`SECURITY.md`, and a `MANIFEST.in` entry so the sdist carries `actions/` for
its tests. No CLI command, task/evidence schema or output schema changes.

Example workflow (shape, not final):

```yaml
name: Agent Contrib verification
on:
  pull_request:
    types: [opened, synchronize, reopened, edited, ready_for_review]
permissions:
  contents: read
  pull-requests: read
  issues: read
concurrency:
  group: agent-contrib-${{ github.event.pull_request.number }}
  cancel-in-progress: true
jobs:
  verify:
    if: contains(github.event.pull_request.body, '```agent-contrib-task')
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@<sha> # vX.Y.Z
        with:
          ref: ${{ github.event.pull_request.head.sha }}
          path: pr-head
          fetch-depth: 0
          persist-credentials: false
          submodules: false
          lfs: false
      - uses: nkovanen/agent-contrib/actions/verify@<sha> # vX.Y.Z
        with:
          checkout-path: pr-head
          fail-on: never
```

`with:` values and the `if:` condition are evaluated by the runner, not by a
shell, so expressions there are not injection points. `action.yml` has a single
`run:` step, `python3 -I "$GITHUB_ACTION_PATH/report.py"`, with every value in
`env:`.

## Test plan

All tests are offline and use the existing fake-GitHub and temporary-Git-repo
patterns. No new dependencies.

1. **Block parser.** Covers:
   - zero, one or two blocks of each kind;
   - CRLF line endings;
   - an indented fence, trailing spaces and info-string variants;
   - unterminated fences;
   - blocks inside HTML comments and inside longer fences (both count toward
     ambiguity);
   - a 32 KiB block, one byte over, and a body over 65,536 characters;
   - duplicate keys, NaN and lone surrogates.
2. **Binding.**
   - The head SHA moved.
   - `head_ref` differs from the PR's branch.
   - A `head_ref` that fails `check-ref-format`.
   - A deleted fork.
   - Evidence for an older commit.
   - A contract hash mismatch.
3. **Orchestration, end to end with temp repos and a fake `gh`.**
   - Consistent 0.1 and 0.2 evidence.
   - A scope violation.
   - An overlap.
   - A stale issue.
   - Schema 0.2 with `GET /user` returning 403, shown under "not evaluated",
     not as an inconsistency.
   - Budget below the minimum.
   - CLI output that fails its output schema, which must be reported as
     `error`.
4. **Summary sanitizer.** An injection corpus goes through every rendered slot:
   - Markdown links and images, raw HTML, `<details>`;
   - headings, table pipes, backticks, `@mentions`;
   - bidi overrides, zero-width characters and newlines;
   - lines starting with `::` and 10,000-character strings.

   The assertions:
   - every line matches one of the template's line shapes;
   - every untrusted-derived value sits in a code span with no backtick or
     newline;
   - the summary stays under 64 KiB;
   - contract or PR prose never appears.
5. **Log safety.** Printed JSON is wrapped by a fresh stop-commands token.
   No printed line starts with `::`.
6. **Decision mapping.** A table of schema-valid CLI outputs maps to
   `result` and the exit code for each `fail-on` value. With `never`, the exit
   is always 0, except for an internal error in the action itself, which still
   exits 0 and reports `error`.
7. **Workflow lint** (`tests/test_workflow_lint.py`). It is line-based because
   there is no YAML dependency. The test first asserts that both files use the
   supported YAML subset: block style only, no anchors, aliases or flow
   mappings in `run:` keys. Rules:
   - no `${{` anywhere inside a `run:` block scalar;
   - no `pull_request_target`, `workflow_run` or `issue_comment` trigger;
   - the `permissions:` block equals the read-only set above;
   - no `write` and no `secrets.`;
   - every `uses:` is pinned to a 40-hex SHA;
   - checkout has `persist-credentials: false`, `submodules: false`, `lfs: false`
     and `ref:` set to the head SHA;
   - no `GITHUB_ENV`, `GITHUB_PATH` or `actions/cache` in the action.

   Each rule has a seeded-bad mutant fixture that the lint must reject, for
   example `run: echo "${{ github.event.pull_request.title }}"`,
   `uses: actions/checkout@v4` or `permissions: write-all`.
8. **Manual, not CI.** A reviewer may also run `actionlint` and `zizmor` on the
   two files. They need a network install, so they are not test dependencies.
9. **Live smoke (slice 4).** A fork PR against a scratch repository: consistent
   evidence, a moved head and a PR that edits the workflow (to observe and
   document T1). This needs explicit user authorization, because it creates
   repositories and PRs.

## Slices

1. `report.py` core: block parser, binding checks, decision mapping and the
   summary renderer with sanitizer, plus tests 1, 2, 4, 5 and 6. It runs the CLI
   through an injectable runner. No action files yet.
2. `action.yml`, the example workflow, the workflow lint (test 7), the
   orchestration tests (test 3) and `MANIFEST.in`.
3. Docs: `docs/maintainers.md` (setup, pinning check, reading the summary,
   what it never claims, T1 residual risk) and `SECURITY.md` (threat model
   T1 to T9 in brief).
4. Live smoke on a scratch repository (user-authorized), plus a ruleset
   experiment if available. Results are recorded in this document.

Deferred: PR comments or custom check runs (needs `workflow_run` and a
separate threat analysis), gist/artifact evidence, `inspect --ai-policy`
excerpts in the summary (another ~70 reads per run), `pr-body` emitting the
blocks, and shallow base/head fetches.

## Open questions for the maintainer

1. Is `fail-on: never` the right default, or should found inconsistencies fail
   the job by default? The recommendation is `never`, because a red job is
   easily mistaken for "the action failed", and a green one for approval.
2. Should a PR that changes `.github/**` be reported as "Not checked:
   workflow files changed" when the action is still the pinned one? It cannot
   protect against a modified invocation, but it does flag the risk on
   honest runs.
