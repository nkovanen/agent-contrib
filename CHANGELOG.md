# Changelog

## 0.3.0 — unreleased

The v0.3.0 candidate adds a task-scoped authorization route (task schema 0.2),
read-only helper commands and report-only options, and hardens untrusted-input
handling. Schema 0.1 formats are unchanged and its routes keep their meaning;
every 0.1 behaviour change, including fail-closed hardening and message
changes, is listed under "Compatibility notes". No GitHub write API, merge, release
channel or runtime model provider is added.

### Highlights

- Schema 0.2: one candidate issue in a repository you own or maintain, with a
  host-issued mandate and separate `implementation`, `draft` and `completion`
  gates; `authorization-request` prepares the unsigned request.
- Host-context 0.2: reviewed overlap dispositions and one recognized
  draft-update round.
- A default-on repository policy report, a mandatory policy review recorded as
  `ai-policy-review`, and `drift --policy-sha256`.
- New helpers: `lint`, `scope-check`, `evidence init`, `drift`, `pr-body`,
  `feedback`, `audit`, `ownership` and `schema`.
- Report-only ranking aids, `--format text`, versioned output JSON Schemas,
  `--report-budget` and an opt-in, blob-verified `--cache`.
- Opt-in required CI checks for completion; a report-only maintainer Action.
- Hardened Git reads: checkout config, attributes, index flags and hidden files
  can no longer hide edits or run programs. See "Compatibility notes" and
  [upgrading](docs/upgrading.md).

### Added

- `discover --limit N` (#1): display at most 1–1000 final ranked candidates
  after full scans and reports. Multi-repository runs share one global budget.
  Optional `display` fields in the unreleased output/1 schema report observed,
  returned and omitted counts, truncation, and full overlap/exclusion totals;
  text keeps hidden overlaps visible in its totals. No-limit output, scan
  completeness, approval, task/evidence schemas and read-only authority are unchanged.

- Tipjar identity for gifting useful agent work, with a `tipjar` console alias
  for the existing CLI. `agent-contrib`, the distribution and Python module,
  canonical Skill, repository URLs and output identifiers remain compatible.
  Discoverable repository jars are planned; this alias adds no protocol or
  authority.

- `tools/benchmark/` (#28, development only; not in the wheel): a read-only,
  bounded collector of issues open at a past cutoff with post-cutoff outcome
  labels, an offline replay of `discover` and `--signals` ranking, and
  top-k precision with explicit bounds for unjudged slots, a conditional
  bootstrap and a seeded random-permutation null. Labels come from stored
  outcome evidence and never assume unknown reasons or authorship; replays
  refuse incomplete results. Results and the pre-registered protocol are in
  [docs/benchmark.md](docs/benchmark.md): under the registered labels no
  ranking change qualifies. PR titles renamed after the cutoff are not
  reconstructed for PRs whose current title overlaps no issue (open, BM-02).

- `drift task.json --policy-sha256 HASH` (N1, dogfood 4): re-reads the
  repository policy inventory and reports `repository_policy_drift`, with
  `policy_drifted` and, when a baseline can be rebuilt at the pinned commit,
  added, removed and changed source identities. A policy-only edit (for example
  to `SECURITY.md`) after the review used to be invisible to `drift`. Drift or
  an incomplete policy read exits 1. The Quick path and the policy step now run
  it before any authorization or publication.
- A report-only maintainer GitHub Action, slice 1 (#11):
  `actions/verify/` with an example workflow
  (`docs/examples/agent-contrib-verify.yml`). It reads only the
  `pull_request` event payload and the PR-head checkout, needs only
  `contents: read` and makes no API calls. It checks that the contract and
  evidence blocks in the PR body describe this PR's route, head, tree, base
  and scope, and writes a job summary. It never runs PR code and never writes
  to GitHub. Live checks (freshness, overlap, approval, identity) are listed as
  not evaluated.
- Opt-in required CI checks for schema 0.2 completion (#17): an optional
  `ci_requirements` list of `{check, app_id}` pairs in the unreleased task
  schema 0.2. Once the exact-head draft is verified, `verify` reads the head's
  check suites and every check run and reports `ci_gate`. A requirement is met
  only if every run with that exact raw name from that app succeeded, every
  suite of that app is completed, at least one run exists, and the reads are
  complete and below GitHub's 1,000-suite window. A `.github/` change also
  blocks. Blockers appear only at completion. Contracts without the field
  verify byte-identically (golden), and `--observe-ci` is unchanged.
- `remote.counted_pages` appends its pagination parameters with `&` when the
  endpoint already has a query string.
- Release preparation (#26, not activated): `docs/releasing.md` runbook with
  verification and rollback, `tools/release_check.py` (version statements
  agree; `--release` needs a dated CHANGELOG heading; `--tag` checks the tag),
  and a proposed PyPI trusted-publishing workflow with build provenance in
  `docs/examples/release-pypi.yml`, which runs only after a maintainer adopts it.
- `discover --repo-dir CHECKOUT` (F12): a report-only `local_work` list of issues
  closed by local commits that are not in the source default branch. A commit
  closes issue N only with a message line that is exactly `<keyword> #N` (or this
  repository's `owner/repo#N`), using a GitHub closing keyword; nothing else on
  the line, so mentions, lists, `Refs` and quoted examples never count (dogfood 4
  N4, review R12). Text discover marks each demoted issue. It is read
  with the hardened Git reader and capped at 500 commits, 64 KiB per commit and
  4 MiB in total, checked by object size before any message is read; messages
  come from raw commit objects, and a shallow checkout or a NUL byte in a
  message is incomplete. With `--signals`,
  referenced issues rank below the other candidates that are not excluded or
  overlapping.
- Host-context schema **0.2** with reviewed overlap dispositions (#7). The 0.1
  sections are unchanged, plus an optional host-issued `overlap_dispositions`
  record. It is bound to the contract, mandate and credential, and pins each
  disposed PR's identity, author, state, draft flag, head, `updated_at`,
  content hash, match reason and the base-branch tip of the reviewed
  comparison. `verify` re-reads every disposed PR and base tip (at most 40
  GETs). It removes an overlap from blocking only when the match is the same
  topical one and every bound observation still holds. Direct references,
  contradictions, failed reads, the actor's own PRs, incomplete scans and
  expired or invalid records block. Waived PRs stay listed, are reported in
  `overlap_dispositions` and `waived_duplicates`, and are named in text output.
  Host issuer requirements are documented. A 0.1 document carrying the section
  and any other version fail closed.
- Host-context 0.2 also accepts an optional, strictly validated `draft_update`
  record (#21, slice 1: inert). `verify` reports it as `draft_update`, with
  status `not_evaluated` or `invalid`. It never changes a gate, blocker,
  `next_action`, exit status or GitHub read, and the mandate hash is unchanged.
  Host requirements for update rounds are documented.
- Draft-update recognition after the one host push (#21, slice 2). With a
  `draft_update` record, the draft at its creation head is no longer
  recognized; it is recognized at the updated head only when the live head is
  the validated evidence HEAD, a strict fast-forward of `from_head` by
  consistent comparisons, with no forbidden timeline event (complete
  pagination), an unchanged final re-read, evidence based on the reviewed
  commit exactly with no merge commit in the round, and validations started
  inside the round. Completion needs a final sign-off issued after the round.
  `draft_update` reports `recognized`, `not_evaluated` (no push yet) or
  `blocked`, with `candidate_head` and `live_head`. No push readiness is
  reported and nothing authorizes a push.
- A default-on, report-only `repository_policy` in `discover`, `inspect` and
  `prepare` output (#8, part; dogfood E-01 to E-05). The earlier scanner found
  nothing on pallets/click, BurntSushi/ripgrep and honojs/hono, although each
  project refuses such work: in an owner `.github` file, in `AI_POLICY.md`, or
  with "Pull requests are limited to maintainers". The report covers
  policy-named files (suffixed and translated names included) and the owner
  `.github` repository at pinned commits, with Git blob identity checked. It
  lists hints, unassessed references and formats, and candidates omitted by
  limits; it has no coverage verdict. The installed workflow gains a mandatory
  policy review with five dispositions and an `unresolved` state, recorded as
  the `ai-policy-review` prerequisite. Source-hiding limits count as
  unresolved, and local authorization never overrides the source project's
  policy. `--ai-policy` is syntax-compatible only (accepted, ignored); the
  candidate-only `ai_policy` excerpts and `agent_contribute.aipolicy` module are
  removed. Existing contracts, `instructions_sha256` and verifier decisions
  are unchanged; newly prepared contracts gain a pending `ai-policy-review`
  prerequisite (see Compatibility notes).
- Explicit task and evidence schema **0.2** (`prepare --schema-version 0.2`) for
  one same-repository candidate issue (#3). A human/host-issued mandate in
  host-context schema 0.1 (`verify --host-context-stdin`, at most 8 MiB, 5 s) is
  bound to the contract hash, numeric repository, owner, issue and credential IDs,
  refs and actions. Live GETs require a personal credential with exactly the
  `admin` or `maintain` role. Mandates and sign-off are host-asserted, not
  cryptographic consent. The base must be the source default branch; a
  case-variant repository spelling is refused with `case_mismatch`.
- Separate schema 0.2 gates selected with `verify --stage
  implementation|draft|completion`. Implementation needs complete, empty
  exact-head PR history; without a valid mandate the blockers say `Exact-head PR
  history not checked: requires a valid mandate`. Exactly one authenticated open
  draft at the tested head is recognized after publication; unrelated overlaps
  still block. A draft created inside an expired mandate's interval stays
  recognized; new actions need a current mandate. Final sign-off is a separate,
  later host record whose expiry is checked after all GitHub reads.
- `authorization-request` (schema 0.2): an unsigned request with every mandate
  binding pre-filled from the contract and live reads and every human-only field
  `null`. It validates the full schema before any read, labels its diagnostics
  untrusted, contains no display summary and cannot pass as host context.
- `lint task.json` (F17): offline contract check against the bundled schema and
  the reviewed-contract rules, with no GitHub or Git reads; exit 0 only for a
  schema-valid reviewed contract.
- `scope-check` (#15): offline check of committed, staged, unstaged and untracked
  paths with the same scope evaluator as `verify`.
- `evidence init` (#14): an evidence skeleton with only observed Git facts and
  contract IDs; it never runs argv or writes `passed` and fails validation until
  filled.
- `--base` for `scope-check` and `evidence init` accepts exactly a full SHA,
  `HEAD` or a full `refs/...` name, optionally followed by `~N`/`^N`, looked up
  exactly (never through Git's short-name lookup). Other forms are refused with
  a conversion hint. `scope-check` warns when the default base is not an
  ancestor of HEAD.
- `pr-body` (#19): a Markdown PR description from the contract, evidence and a
  fresh `verify`, with remote text neutralized and `Refs` by default. For schema
  0.2 it shows only `technical_evidence_valid` with source (including identity),
  evidence and review blockers, and says that authority gates, `next_action` and
  sign-off are omitted because it takes no host context.
- `feedback 'owner/repo#PR'` (#20): latest reviews, comments, outdated flags and
  failing or pending checks for the exact head. Each reviewer's decision is
  classified by the association on the review that made it (`decision_author`).
- `audit owner/repo` (#10): read-only maintainer report using exactly the reads
  `discover` makes.
- `drift task.json` (#16, part): issue, per-file instruction, branch, policy and
  overlap changes since preparation, plus changed source repository, issue URL
  and (0.2) numeric identities. It never rewrites the contract.
- Multi-repository `discover` (#13) for 2–20 repositories with isolated results
  and a merged candidate order; a single repository's output is unchanged.
- Optional reports that grant no approval or authority and change no readiness
  gate. `--signals` re-ranks candidates by its score after exclusions,
  overlaps and low likelihood; the others leave ordering unchanged:
  `discover --signals` (#12; code location including unique dotted and `::`
  module names, clarity, activity, author association; over-long, truncated or
  partly non-word module names are refused whole, never shortened), `discover
  --responsiveness` (#12; one read of recently closed PRs, skipped after an
  incomplete snapshot; malformed, repeated or out-of-interval PR entries make it
  `unknown`), `inspect
  --ownership` and `ownership` (#5, #6; a conflicting repository ID for one
  cross-referenced PR leaves the report incomplete), `verify --observe-ci` (#17, part), `verify --observe-signatures` (#18,
  part; GitHub's verification of the evidence head, labelled as not approval;
  active `required_signatures` rulesets on the base branch; and, with
  `--repo-dir`, signature-header presence for at most 1000 commits in
  `base_commit..git_head`, never truncated; no gpg, ssh-keygen or
  `verify-commit` runs) and `--report-budget` / `--min-remaining` (#27, part).
  `--cache` (#27) reuses file contents at a pinned commit of a public
  repository from the user cache, keyed by Git blob SHA and re-verified
  against the live tree on every hit; trees and all mutable reads stay live
  and output is unchanged. It is used only under a private directory chain
  (cache directory exactly 0700); a default Ubuntu `~/.cache` (0775) disables
  it, so point `XDG_CACHE_HOME` at a private directory. An opted-in report that is incomplete exits 1
  where documented. `discover
  --signals` also lists `code_location.named_paths_missing`: file paths the
  issue names that are not in the snapshot tree, compared exactly (F13).
- `discover --signals` reports each issue's `labels` and a `demotion` breakdown,
  and lowers the score by 2 for each documented label group (on hold, needs a
  decision, not planned, explicit major-version bucket; negated labels do not
  match) and for meta, tracking, roadmap or WIP titles, whose maintainer point
  is no longer counted (E-08, E-09). Default discover output and ordering are
  unchanged. An offline regression replays the dogfood-2 click, ripgrep and
  hono rankings; precision@5 is unchanged on it (1/5, 1/5, 0/5).
  `discover --signals --check-top N` (1-5) reads bounded ownership signals for
  the top N only (one timeline and comment page, 4 PR details each, 30 reads in
  all). A merged same-repository fix or a current assignee moves a checked
  issue below every other candidate that is not excluded or
  overlapping, with the reason listed; claim comments never demote. With
  `--check-top`, `signals.assignees` reports current assignees. Report only.
- `--format text` summaries (#24, part); JSON stays canonical and unchanged.
- `--help` describes every command and option, input constraints and exit status.
- Installed workflow: a source-linked requirements ledger, precommit gates,
  independent compliance review, the contract fields that hold the AI-policy
  review and ledger reference, an implement-only local profile, coordinator relay
  rules, the stacked-base limitation and normative host issuer requirements.
- Versioned JSON Schemas for every command's JSON output ship in
  `schemas/output/1/` (#24). `agent-contrib schema COMMAND` prints one (`error`
  is the error envelope), `instructions` reports `output_schema_version` and the
  directory, and `docs/output-reference.md` has a field reference generated from them. Every
  output the test suite produces is validated against its schema. Output values
  do not carry the version, so existing results are unchanged; a shape change
  bumps it. The bundled validator gained `null`, `number`, type lists, `anyOf`,
  local `$ref` and `additionalProperties` maps, which the task, evidence and
  host-context schemas do not use. It now checks every item of a list whose
  length the schema allows (previously only the first 1000) and rejects NaN and
  infinities as numbers. Output schemas state every length bound and anchor
  every pattern, so standard validators decide like the bundled one.
  Error, warning and other diagnostic lists, free text and remote-derived
  lists claim no cap below the input bounds, because producers never truncate
  them (R5-04).

### Changed

- Text `inspect --ownership` and `ownership` show the ownership report:
  possible prior fixes, downstream references, rejected approaches, open linked
  PRs, claims, assignments, completeness and errors (external evaluation 3, G1).
  JSON is unchanged.
- Policy hint IDs are stable (dogfood N12): `hints[].id` is `H-` plus the full
  SHA-256 of (source `identity_sha256`, line, kind) instead of the report
  position (`H1`, `H2`, ...), so a disposition recorded by ID keeps naming the
  same line when other sources or builds change the order. Report order is
  unchanged. A shared ID fails closed as the hiding limit `hint_id_collision`.
- The installed workflow's Quick path names `lint` before `verify`, the
  optional `discover` ranking aids `--check-top N` and `--repo-dir CHECKOUT`,
  and the optional `--cache` (dogfood N13).

- The Quick path names the "Repository policy review" section explicitly instead
  of "the repository policy step below" (N3, dogfood 4).
- The repository policy report adds `hinted_lines` (N2, dogfood 4), one
  reading entry per hinted line with all its hint kinds. It also adds
  `project_vocabulary`, which summarizes mentions made only of the project's own
  name. Restriction hints are never summarized. The text view groups by line and
  counts the summarized mentions, and the review obligation now says to read
  every hinted line.
- Installed workflow Quick path (N-02): the stop rule now matches the policy
  section ("a relevant rule that is prohibited or unresolved" instead of "a
  refusal or restriction"), the policy step comes before ranking and selection,
  and a constrained policy (a human must review, submit or write every comment)
  requires asking the user to commit to that mode first. Disposition (c) is
  valid only after that commitment.
- Text output of `discover`, `inspect` and `prepare` lists up to five policy
  restriction hints (kind, `repository:path:line`, sanitized excerpt) under the
  Policy line, plus a count of the rest. Before, only counts were shown, so
  text-mode agents never saw the sentence that justifies a stop (N-01).
  HTML comment markers are left out of these text excerpts; JSON is unchanged.
  Shortened excerpts end with `...` and hints carry `excerpt_truncated`. An
  excerpt keeps its restriction word near the start. Text output counts dropped
  restriction hints, and says "No restriction hints retained" when limits
  caused losses (RP-26).
- Text output of `discover`, `inspect` and `prepare` also lists up to five
  unassessed policy references and files (target, reason, `from` file and
  line; sanitized, shortened to 150 characters) and points to JSON for the
  rest. Before, it printed only their count, so a text-mode agent could not
  see which pages the review obligation asks it to read (G3, evaluation 3).
- Repository policy hints (N-04, external evaluation 2): hints are ordered
  agent, PR eligibility, AI, then PR restrictions with AI context, PR
  restrictions in policy files, other PR restrictions, restrictions from nested
  security, support, governance or conduct files (such as
  `doc/source/reference/security.rst`), and mentions. Nested files rank lower
  but are never skipped (RP-25). Bounds drop mentions first. A dropped restriction hint is reported
  as a source-hiding limit (`restriction hints`).
  PR submitter-eligibility rules ("Pull requests are limited to maintainers",
  "issues instead of pull requests", "Only a maintainer may submit") rank just
  below agent restrictions; review requirements such as "PRs must be reviewed by
  maintainers" do not (RP-27).
- `authorization-request` JSON adds `requested_actions` (the contract's actions;
  the host still chooses the mandate actions). Text output now lists the
  requested actions and the human-only fields, and labels `unresolved_fields`
  as derived fields, so a ready request no longer reads as having nothing left
  to fill (dogfood N6).
- `--ai-policy` is deprecated: it still changes no output or exit status, and now
  writes one notice line to stderr (dogfood N5). The notice is best effort: a
  missing, closed or readerless stderr is closed quietly, so interpreter
  shutdown cannot turn the exit status into 120 (R13-01).
- `--cache` on an offline command (`instructions`, `schema`, `skill`, `lint`,
  `scope-check`, `evidence init`) is now a usage error (exit 2), like
  `--report-budget`; it was silently accepted (dogfood N7).

- `discover --repo-dir` errors say the local-work report is incomplete and that
  discover exits 1, and name a missing directory or a non-Git directory instead
  of the evidence wording (dogfood 4 N8).
- `--observe-ci` and `--observe-signatures` share one target/head prelude.
  With an evidence head but an invalid target repository,
  `ci_observation.head_sha` is now `null`, like `signature_observation`, since
  nothing was observed at that head. A missing `execution` object no longer
  raises in the CI observer. Readiness and exit codes are unchanged (A2-05).
- The installed workflow runs `drift` before any authorization request and
  before publication, and names `--observe-ci`/`--observe-signatures` as
  report-only (A2-10).
- `--format text authorization-request` lists its preflight errors and
  unresolved fields, so a request that is not ready says why (A2-08).
- Ownership `possibly_already_fixed` counts only merged PRs in the issue's own
  repository; merged PRs elsewhere move to `downstream_references` (E-11: a
  downstream workaround was reported as a possible fix). Cross-referenced PRs
  also report a sanitized `title` and `base_ref`.
- The workflow recommends deterministic, countable acceptance criteria over
  wall-clock limits unless the repository defines the benchmark (F26).
- Text `discover` shows a responsiveness line with `--responsiveness` (F23) and
  a local-work line with `--repo-dir`.
- The workflow's Quick path step 3 names the repository policy step's sections
  (F43, F44).
- Evidence-base and reviewed-source history errors name the base SHA, the
  repository, its default branch and the tip commit it was compared with, plus
  the comparison status or read error (F19). Conditions are unchanged.
- The prerequisite blocker names each failing prerequisite, for example
  `Prerequisites are not satisfied with evidence: P1 (pending), P4 (satisfied
  without evidence)`. The condition is unchanged.
- A heuristic overlap `reason` ends with the shared title words and checklist IDs
  that triggered it, and says when a shared ID such as `SHA-256` may name a
  standard (R7-01). Matching and fields are unchanged; such overlaps still block.
- A failed GitHub read says when it was HTTP 404 (not found or not visible to
  this account) or HTTP 401 (not authenticated) instead of always "check gh
  auth" (E-17). `gh` output is never echoed; codes and exits are unchanged.
- Text `discover` shows each issue's overlapping-PR count, excluded flag and
  (with `--signals`) score, plus overlapping and excluded totals that include
  issues beyond the 20-line cap (F8).
- `scope-check` warns when the default base is more than one commit behind
  HEAD and out-of-scope paths changed, naming the base and suggesting `--base`
  (F36). Violations and exit status are unchanged.
- A global option placed after the subcommand is still a usage error; the
  message now says to move it before the subcommand. `discover` with no
  repository reports the missing `reference`.
- CLI input files are read once and validated before any GitHub or budget read,
  with identical errors with or without `--report-budget`. Schema-invalid
  `drift`, `pr-body` and `authorization-request` contracts make no GitHub read.

### Security

- Untracked `.gitattributes` files are always reported, even when a committed
  `.gitignore` ignores them, because they change how Git compares checkout
  content; `scope-check` treats one as out of scope. Previously an ignored
  `src/.gitattributes` with `eol=crlf` made CRLF bytes that differ from HEAD
  pass `verify` (FR2-01).
- A recursive-tree entry with a missing or unknown `type`, a `mode` that
  contradicts its type, or an empty path is a malformed GitHub response in
  the source snapshot and the policy inventory, not a skipped non-blob. A new
  `AI_POLICY.md` entry without a valid type made `drift --policy-sha256`
  report an unchanged, complete inventory and exit 0 (FR1-08). The same check
  applies to the `--cache` tree (a malformed entry makes the whole tree
  uncacheable, so content reads stay live) and to the `pr-body` template
  lookup (reported as unknown, never as no template). A tree that lists one
  path twice is malformed in every reader, whatever the order: with
  conflicting blob IDs the last one used to win, so drift could report an
  unchanged inventory and exit 0 (FR1-09).
- A claimed draft whose GitHub creation time is still in the future is not
  recognized, even inside the mandate interval (FR1-03).
- Schema 0.2 exempts the own draft from overlap only when the open-PR scan lists
  it with the same numeric ID that exact-head history and detail report; a
  conflicting or missing scan ID keeps it blocking (FR1-02). A PR number the
  scan lists twice is a conflict in either order, never resolved by the last
  entry (FR1-05).
- A GitHub comparison counts as a history proof only when its response proves
  the status: the echoed base commit, a merge base consistent with the status,
  and non-negative `ahead_by`/`behind_by`/`total_commits` that agree with it.
  A bare or contradictory `status` used to authenticate the reviewed source
  commit and the evidence base (FR1-01). Equal commits must compare
  `identical` and different commits must not (FR1-04), and a status that is
  not a string is a malformed response rather than a crash (FR1-06).
- Scope judges each changed symlink by where it points (G-08), in `verify`
  evidence checks and `scope-check`. The committed (or staged, or worktree)
  target is read without following it and resolved lexically from the link's
  directory through every link hop, directory links included. A target that is
  absolute, uses a backslash or a drive letter, escapes the repository, points
  at the repository root, exceeds 4096 bytes or 40 hops, contains a NUL byte,
  is not valid UTF-8, cannot be read, or resolves outside
  `allowed_paths` or into `prohibited_paths` is a scope violation that names the
  reason. A link to an allowed file still passes. A link that resolves to a
  directory of the same snapshot is also a violation when any prohibited
  pattern can match a path beneath it, so `docs/l -> private` no longer passes
  under `docs/*` with `docs/private/*` prohibited (FR2-02).
- Reject JSON strings containing a lone surrogate escape (`"\ud800"`) and
  numbers that overflow to infinity (`1e999`) as `invalid_json` in GitHub
  responses, contracts, evidence and host context. A lone surrogate used to
  abort a whole multi-repository `discover` at hashing time; an overflowing
  number in a repository policy used to crash `inspect` output. Now only the
  affected read or repository is incomplete or unknown.
- Overlap scans treat a PR whose `body`, `head` or `head.ref` is missing or has
  the wrong type as malformed, making the scan incomplete. Values such as `[]`,
  `false` or `0` used to be scanned as empty text. An explicit `null` body or
  head stays empty.
- `--repo-dir` must be the Git worktree top level for `verify`, `scope-check`
  and `evidence init` (`not_worktree_root`). From a subdirectory, tree, index and
  untracked reads omitted the rest of the checkout, hiding gitlinks and
  out-of-scope files.
- HEAD is captured once with an exact lookup and used for every tree, diff,
  ancestry, gitlink and timestamp read. An unborn or deleted branch, or a HEAD
  naming a non-commit, fails with `unborn_head`; a `refs/tags/HEAD` tag can no
  longer stand in for it.
- Schema 0.2 requires the collaborator-permission login to be a valid ASCII
  GitHub login before its case-insensitive comparison, so Unicode confusables
  such as `ſ` or the Kelvin sign no longer match.
- `verify`, `scope-check` and `evidence init` fail closed with `index_flags`
  when the index marks tracked paths assume-unchanged or skip-worktree
  (including sparse checkouts), because status and diff would hide changes to
  those files. The index is only read, never modified.
- Schema 0.2 binds the local branch by its exact full ref: symbolic HEAD must
  equal `refs/heads/` plus the reviewed `head_ref`, so a same-named tag or a
  name differing only by trailing Unicode whitespace no longer matches. Git
  output loses only its trailing newline, never other whitespace.

- Checkout Git config can no longer make a read run a program or fetch.
  `verify`, `scope-check` and `evidence init` refuse (`unsafe_git_config`) a
  checkout whose effective config, including `include`/`includeIf` files, sets
  `filter.*`, a `gpg` program, `diff.external`, `diff.*.command`/`textconv`,
  partial-clone/promisor settings or `protocol.*`. Every Git read forces
  `log.showSignature=false` and `protocol.allow=never` and sets
  `GIT_NO_LAZY_FETCH`, `GIT_PROTOCOL_FROM_USER=0` and `GIT_TERMINAL_PROMPT=0`.
  Previously a local clean filter, a `gpg.program` with `log.showSignature`, or
  a promisor `ext::` transport ran during status, diff, show or merge-base.
- Git reads force `core.checkStat=default`, `core.trustctime=true`,
  `core.ignoreStat=false` and `core.fileMode=true`, so relaxed checkout stat or
  mode settings cannot hide a same-size edit or an executable-bit change. On
  POSIX they also force `core.symlinks=true`, so a regular file replacing a
  tracked symlink is reported.
  `core.ignoreCase=true` on a case-sensitive filesystem is refused
  (`unsafe_git_config`) because it hides case twins. The setting is read as
  Git's effective boolean (an empty or later-overridden value is false), and a
  `.GIT` symlink or second entry cannot make a case-sensitive filesystem look
  case-insensitive.
- `scope-check` stops on a gitlink before any index or worktree diff, and every
  index or worktree diff and status passes `--ignore-submodules=all`, so Git
  never starts a command inside a populated submodule with that submodule's own
  config. Previously scope-check reported the gitlink but still ran a
  submodule-configured clean filter.
- Every tracked file's worktree bytes must equal either its committed blob or
  exactly what checkout writes for it (`git cat-file --filters`, with
  `core.autocrlf=false` and `core.eol=lf`). `ident`, `eol`/`text` and
  `working-tree-encoding` conversions therefore cannot hide an edit (for
  example code added inside `$Id: ...$`), while an untouched checkout with
  legitimate committed conversions (an expanded `$Id`, CRLF `.bat` files,
  UTF-16 sources) stays clean. Every read ignores `core.attributesFile`; a
  non-empty `.git/info/attributes` is refused (`unsafe_git_attributes`). No
  Git version beyond those already required is needed (R1-19, G-17, G-18).
- Worktree content is compared with HEAD (and, for `scope-check`, the base)
  through a fresh temporary index outside the checkout, so a hand-edited stat
  cache in `.git/index` cannot hide an edit. The checkout's index is used only
  where it is itself the subject (staged changes, index flags) and is never
  written. Large checkouts take longer, because every tracked file is hashed.
- Untracked files are found with only per-directory `.gitignore` rules:
  `.git/info/exclude` and a local `core.excludesFile` no longer hide an
  untracked file from `verify`, `scope-check` or `evidence init`, and an
  untracked `.gitignore` is always reported. A committed `.gitignore` still
  applies.

### Fixed

- `scope-check` refuses an untracked nested repository with the gitlink error,
  since adding it would create a gitlink (FR2-03).
- An unwritable temporary root is skipped in favour of `/tmp` or `/var/tmp`,
  and a temporary directory that still cannot be created reports
  `temp_dir_error` instead of an unstructured input error (G-20).
- Every Git read sets `GIT_ATTR_NOSYSTEM=1`, so a system-wide gitattributes file
  cannot shape how checkout files are compared (G-19).
- Schema 0.2 `verify` lists contract route errors (pending mode, invalid or
  equal refs, a different target or head repository) in its errors and every
  stage's blockers even without a host context, as `authorization-request`
  already did. With a mandate they appear once. Only blockers are added
  (A2-02).
- The temporary index for the content check is created under a temporary root
  whose real path is outside the worktree and its Git directories (falling
  back from `TMPDIR` to `/tmp` or `/var/tmp`, else `unsafe_temp_dir`), so a
  `TMPDIR` inside `.git` or the checkout no longer receives it (R1-20).
- The worktree content check gets a timeout scaled from the tracked blob size
  (15 s plus one second per 32 MiB, at most 900 s), and running out reports
  `checkout_too_large_for_timeout` with the byte count instead of a generic
  read error. Other Git reads keep their 15 s limit (G-16).
- Approval-label documentation states what policy 0.1 checks: a configured
  label currently present, not who applied it. The policy is suitable only if
  everyone who can label issues is trusted to approve agent work. Public events
  name a labeling actor, but its approval authority cannot be verified from
  public REST data (#9). No behaviour changes.
- In a shallow clone that lacks the base or its history, `verify`,
  `scope-check` and `evidence init` now say so (`shallow_checkout`, with a
  fetch hint) instead of a generic read or base error. They still fail closed.
- Closed or missing stdout exits 1 quietly, including buffered errors and
  caller-provided write-only streams (#4). Help and version are unchanged.
- Library `verify` of a schema-valid 0.1 contract with host context keeps
  `schema_valid: true` and reports the refusal only in `errors`.

### Compatibility notes

- Discovery's issue lists now reject a repeated repository number even if the
  API supplies different IDs. The repeated entry is omitted and the scan stays
  incomplete, including without `--limit`; inconsistent identities cannot expand
  the limited detail lists or produce contradictory display counts. Valid
  no-limit output is unchanged.

- `repository_policy` adds `inventory_format` (currently 2), and the format is
  part of the `inventory_sha256` input, so every inventory hash differs from
  earlier 0.3.0 candidate builds (format 1, unversioned). `drift
  --policy-sha256` reports `current_inventory_format` and
  `recorded_inventory_format`. A format-1 hash of the same pinned snapshot is
  recognized and reported as a format change rather than blamed on a moved
  owner `.github` repository; an unknown hash's note names a different
  inventory format as one possible cause. Both still count as drift (exit 1)
  (N11).
- `repository_policy.inventory_sha256` now also covers the pinned blob id of
  every unread policy candidate (RP-28) and the owner `.github` lookup outcome
  (`owner_lookup`, RP-29), so it differs from earlier 0.3.0 candidate builds.
  An owner lookup that fails other than with an HTTP 404 on the repository
  metadata (a later commit or tree 404 included) is now a hiding limit,
  so it is unknown rather than "absent". Linked local files carry their pinned
  blob id: relative links, and github.com blob/tree links into the source or
  the owner `.github` repository (in either direction) at that repository's
  default branch or pinned commit. A known file without a valid blob id, or an
  unresolvable blob/tree link into either repository, is a hiding limit. Only newly
  recorded review hashes are affected. The policy hash is not part of
  `instructions_sha256`, so existing contracts and their verification decisions
  are unchanged.
- Schema 0.1 `verify` on a draft whose execution mode is `pending` and whose
  target is blank now reports "Execution target not yet chosen (execution mode
  is pending)" instead of "Execution target repository is invalid". The
  decision is unchanged; a non-blank invalid target keeps the old message
  (N-05). The installed workflow's requirements ledger also names CLA and DCO
  sign-offs as human-submitter obligations.
- `prepare` (task schemas 0.1 and 0.2) now writes the prerequisite
  `ai-policy-review` with status `pending` into every new contract, so a policy
  review must be recorded (`satisfied` with evidence, or `blocked`) or visibly
  removed before verification can pass. Previously prepared contracts and their
  verification decisions are unchanged; the draft output of `prepare` differs.
- CLI/library versions follow semantic versioning; task, evidence and
  host-context schema versions are independent. Supported sets: task/evidence
  0.1 and 0.2, host-context 0.1 and 0.2. Unknown versions fail closed; nothing is
  migrated. `prepare` still defaults to 0.1.
- Schema 0.1 changes, all fail-closed or message-only:
  - `verify` rejects evidence whose implementation adds a symlink that resolves
    outside the contract scope (G-08); a symlink to an in-scope file still passes.
    A symlink to a directory beneath which a prohibited pattern can match is
    rejected too (FR2-02).
  - `verify --repo-dir` from a subdirectory or Git directory now fails with an
    evidence error instead of reading part of the checkout.
  - An unborn, deleted or non-commit HEAD now fails with `unborn_head`.
  - An index with assume-unchanged or skip-worktree entries, including a sparse
    checkout, now fails with `index_flags`.
  - A partial or contradictory GitHub comparison of the evidence base now
    fails as unauthenticated instead of passing on its `status` alone.
  - A checkout with the Git config keys listed under Security fails with
    `unsafe_git_config`.
  - Files hidden only by `.git/info/exclude` or `core.excludesFile` now make
    evidence dirty.
  - A file whose bytes match neither its blob nor its checkout output (for
    example an edit hidden by `ident`, or a CRLF copy produced only by a local
    `core.autocrlf`) now makes evidence dirty; a non-empty
    `.git/info/attributes` fails with `unsafe_git_attributes`.
  - Malformed or missing PR `body`/`head`/`head.ref` fields now make discovery
    and verification scans incomplete instead of empty.
  - Lone-surrogate strings and overflowing numbers now fail as `invalid_json`;
    contracts or responses that used to fail with `input_error`, or to parse to
    infinity, change error code.
  - The prerequisite blocker and heuristic overlap reasons carry more detail,
    so their strings differ; the decisions do not.
  - Misplaced global options produce a more specific usage message.
  - `--base` grammar applies only to the new `scope-check` and `evidence init`;
    evidence `base_commit` stays a full SHA, so 0.1 `verify` is unaffected.
  - Lifecycle options (`--stage`, `--host-context-stdin`) are rejected for 0.1
    contracts rather than reinterpreted.
- Default `discover` read sequence and output structure are pinned by goldens.
  Individual values can still differ where listed above: heuristic overlap
  reasons and malformed-input completeness.

## 0.2.0 — 2026-11-01

First standalone release, extracted from the reviewed LightCraft experiment.
Licensed under MIT, with original attribution retained.

- Read-only GitHub issue discovery, policy/instruction inspection and open-PR
  overlap detection through `gh`.
- One-hop parent issue discovery for forks with Issues disabled; distinct
  requested, source and proposed-target identities with provenance.
- Draft task contracts and passive evidence verification using schema `0.1`.
- Separate repository approval, execution authorization and publication mandate.
- A portable Skill that loads the workflow from the installed CLI.
- Standalone Python packaging, GitHub installation and CI; no LightCraft or Rust
  build dependency. The 65 original protocol regressions are retained.
- Normalize Git UTC timestamps for Python 3.10 compatibility, with an additional
  regression covering newer Git versions that emit a trailing `Z`.

The standalone release preserves the POC's protocol behavior. Approval delegates
to accounts with label permissions; evidence is self-attested; topical overlap
and existing own drafts can block verification. No automatic submission,
execution harness, actor-specific approval or PyPI publication is included.

### Earlier experiment

The 0.1.0 prototype and development of 0.2.0 occurred in
[LightCraft PR #1](https://github.com/nkovanen/lightcraft/pull/1).
Historical pilot logs remain there rather than in this distribution.
