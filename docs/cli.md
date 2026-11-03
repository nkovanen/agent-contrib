# Command reference

Every `agent-contrib` command, its options, exit codes and limits. Commands print JSON
by default (see [text output](#text-output-unreleased)); the field-by-field JSON reference is in
[output-reference.md](output-reference.md). Start with the [command index](#command-index);
sections are grouped by task.

## Contents

- [Discovery and ranking](#discovery-and-ranking)
  - [Discovery results and references](#discovery-results-and-references)
  - [Opt-in ranking signals](#opt-in-ranking-signals)
  - [Repository responsiveness](#repository-responsiveness)
  - [Several repositories](#several-repositories)
  - [Repository policy report (default-on, report only)](#repository-policy-report-default-on-report-only)
  - [Ownership and resolution signals (report only)](#ownership-and-resolution-signals-report-only)
- [Contracts and verification](#contracts-and-verification)
  - [Contracts and verification gates](#contracts-and-verification-gates)
  - [Schema 0.2 lifecycle (CLI 0.3.0 candidate)](#schema-02-lifecycle-cli-030-candidate)
  - [Offline contract lint](#offline-contract-lint)
  - [Drift since preparation](#drift-since-preparation)
  - [Required CI checks (schema 0.2 completion, opt-in)](#required-ci-checks-schema-02-completion-opt-in)
- [Local checkout tools](#local-checkout-tools)
  - [Checkout requirements](#checkout-requirements)
  - [Offline scope check](#offline-scope-check)
  - [Evidence skeleton](#evidence-skeleton)
- [Host authorization](#host-authorization)
  - [Authorization request](#authorization-request)
- [Reports and integration](#reports-and-integration)
  - [PR description](#pr-description)
  - [PR feedback](#pr-feedback)
  - [CI observation (opt-in, report only)](#ci-observation-opt-in-report-only)
  - [Signature observation (opt-in, report only)](#signature-observation-opt-in-report-only)
  - [Output schemas](#output-schemas)
- [Global options and output](#global-options-and-output)
  - [Exit codes and output streams](#exit-codes-and-output-streams)
  - [Help](#help)
  - [API budget (opt-in)](#api-budget-opt-in)
  - [Content cache (opt-in)](#content-cache-opt-in)
  - [Text output (unreleased)](#text-output-unreleased)
- [Command index](#command-index)

## Command index

Every command exits **2** for a usage error and **1** when its own input, protocol or core reads
fail. Report-only reads that cannot change a command's result are the exceptions:
their failures are reported inside the report and the exit code is unchanged. These
are the default-on `repository_policy` report of `discover`, `inspect` and `prepare`,
`verify --observe-ci`, `verify --observe-signatures` and `--cache` (a cache miss or
unusable cache falls back to live reads). The opt-in reports `inspect --ownership`,
`discover --responsiveness`, `discover --check-top` and `discover --repo-dir` do make
an incomplete report exit 1, as the table says. "Reads GitHub" means fixed
`gh api --method GET` reads; nothing is ever written.

| Command | Purpose | Reads GitHub? | Exit codes |
| --- | --- | --- | --- |
| `discover` | Rank open issues of one repository, or 2-20, with policy and overlap context | Yes | 0 complete; 1 incomplete (also an incomplete `--responsiveness`, `--check-top` or `--repo-dir` report) |
| `inspect` | One issue: approval, instructions, exclusions, overlapping PRs | Yes | 0 complete; 1 incomplete (also incomplete `--ownership` signals) |
| `prepare` | Write a draft task contract; grants nothing | Yes | 0 complete read and draft written; 1 otherwise |
| `verify` | Contract, evidence and live gates; never runs validation commands | Yes | 0 when the gate passes (0.1: completion readiness; 0.2: the selected `--stage`); 1 otherwise |
| `authorization-request` | Schema 0.2: unsigned request with every mandate binding pre-filled | Yes | 0 ready for issuance; 1 otherwise |
| `lint` | Offline contract schema and reviewed-contract check | No | 0 schema-valid reviewed contract; 1 otherwise |
| `scope-check` | Offline check of local changes against the contract scope | No | 0 no violation; 1 violation or error |
| `evidence init` | Unfilled evidence skeleton from observed Git facts | No | 0 file written; 1 error |
| `pr-body` | Markdown PR description from the contract, evidence and a fresh `verify` | Yes | 0 file written; 1 error |
| `feedback` | Reviews, comments and exact-head checks of a published PR | Yes | 0 complete; 1 incomplete |
| `ownership` | Report-only claims, linked PRs and possible prior fixes for one issue | Yes | 0 complete; 1 incomplete |
| `drift` | What changed since the contract was prepared | Yes | 0 complete and not drifted; 1 drifted or incomplete |
| `audit` | Maintainer view of what agents see in a repository | Yes | 0 complete; 1 incomplete |
| `instructions` | Installed workflow, CLI version and supported schemas | No | 0 |
| `skill` | Export the canonical Skill file | No | 0 written; 1 error (an existing file is never overwritten) |
| `schema` | JSON Schema of a command's JSON output | No | 0 |

### Invocation forms

| Command | Result |
| --- | --- |
| `agent-contrib discover owner/repo [--limit N]` | Repository resolution, policy/instruction context, ranked issues and overlap/completeness metadata |
| `agent-contrib discover owner/a owner/b ... [--repositories-file FILE]` | Two to 20 repositories in one run, each with its own result, plus a merged candidate order |
| `agent-contrib discover owner/repo --signals` | Same reads and fields, plus per-issue `signals` and a signal-aware `ordering` |
| `agent-contrib discover owner/repo --responsiveness` | One extra read of recently closed PRs, reported as `repository_signals.responsiveness`; issues and ordering unchanged |
| `agent-contrib audit owner/repo [--print-policy]` | Read-only maintainer report: policy validity, labels, instruction coverage, issue-quality and overlap counts, non-binding suggestions |
| `agent-contrib inspect 'owner/repo#123'` | Detailed issue snapshot, source policy, instructions, exclusions and PR matches |
| `agent-contrib prepare 'owner/repo#123' --output task.json` | A new schema `0.1` draft with a `pending` `ai-policy-review` prerequisite; an existing output file is never overwritten |
| `agent-contrib verify task.json` | Schema, current source/approval/overlap and execution-readiness checks; no commands executed |
| `agent-contrib verify task.json --evidence evidence.json --repo-dir checkout` | Also validates supplied evidence against the local checkout and live source |
| `agent-contrib authorization-request task.json` | Schema 0.2 only: an unsigned request with every mandate binding pre-filled from the contract and live reads and every human-only field `null`. Grants nothing; exit 1 when not ready |
| `agent-contrib lint task.json` | Offline contract check: bundled task schema, then the reviewed-contract rules `verify` applies first; exit 0 only for a schema-valid reviewed contract. No GitHub or Git reads |
| `agent-contrib scope-check task.json --repo-dir checkout [--base REV]` | Offline check of committed, staged, unstaged and untracked paths against the contract scope; exit 1 lists each violation. Never evidence |
| `agent-contrib evidence init task.json --repo-dir checkout --base REV --output evidence.json` | A new evidence skeleton with observed Git facts and contract IDs; results stay unfilled and the file fails validation until completed |
| `agent-contrib pr-body task.json [--evidence e.json --repo-dir checkout] [--closes] [--assistant TEXT] --output body.md` | A new Markdown PR description built from the contract, evidence and a fresh read-only `verify` run |
| `agent-contrib feedback 'owner/repo#PR' [--expected-head SHA]` | Read-only review state, review/issue comments and failing or pending check runs for a published PR |
| `agent-contrib inspect 'owner/repo#123' --ownership` or `agent-contrib ownership 'owner/repo#123'` | Opt-in, report-only timeline and comment signals: cross-referenced PRs, assignments, claims and possible prior fixes |
| `repository_policy` (always added by `discover`, `inspect` and `prepare`) | Report-only policy inventory and hints; never a verdict. `--ai-policy` is deprecated and ignored (one stderr notice) |
| `agent-contrib drift task.json` | Read-only report of what changed since preparation: issue, instruction files, branch, policy and open-PR overlap |
| `agent-contrib verify task.json --evidence e.json --observe-ci` | Also reports GitHub check runs and combined status for the evidence head; never changes gates or exit code |
| `agent-contrib verify task.json --evidence e.json [--repo-dir checkout] --observe-signatures` | Also reports GitHub's signature verification for the evidence head, required-signature rulesets on the base branch and local signature-header presence; never verifies locally or changes gates or exit code |
| `agent-contrib --report-budget [--min-remaining N] COMMAND ...` | Adds the core REST rate-limit budget before and after a GitHub-reading command; optionally refuses to start below N |
| `agent-contrib --cache COMMAND ...` | Reuses verified file contents at pinned commits of public repositories from the user cache; every other read stays live and output is unchanged |
| `agent-contrib instructions` | Installed workflow Markdown, CLI version, schema support and update behavior |
| `agent-contrib skill --output SKILL.md` | Canonical adapter export, CLI version and SHA-256 |
| `agent-contrib schema COMMAND` | The JSON Schema of COMMAND's JSON output; see [Output schemas](#output-schemas) |
| `agent-contrib --version` | CLI/library semantic version |

## Discovery and ranking

### Discovery results and references

`discover`, `inspect` and `prepare` wrap their results with
`requested_repository`, `issue_source_repository`, `proposed_target_repository`
and `resolution_provenance`. The proposed target is context, never authority.
A disabled-issue fork uses one immediate parent's enabled tracker; ordinary
repositories and enabled-issue forks keep their own tracker. Missing parent
metadata, a parent without Issues, malformed responses and API failures remain
unresolved, with errors and `complete: false`.

A heuristic overlap's `reason` ends with what triggered it: the shared title
words (two or more) and/or shared checklist IDs, sorted, at most ten of each with
a count of the rest. An explicit issue reference keeps its own reason. The
duplicate entry fields are unchanged. When a shared ID is a well-known standard
name such as `SHA-256` or `UTF-8`, the reason adds that it may name a standard,
not a work item. The match still blocks: spelling alone cannot tell a standard
from a project ticket such as `SHA-1234`.

Use the `reference` emitted by discovery for subsequent commands. It keeps the
requested spelling; schema 0.2 `prepare` refuses a case variant of the canonical
`issue_source_repository` with `case_mismatch`, so rerun with that spelling. In a fork
request, `fork/repo#123` means “resolve issue 123 for this requested repository”;
its `issue_url` names the actual source. It is not a claim that the issue exists
on the fork. Both repositories' open PRs are scanned, including drafts; a bare
`#123` in a PR belongs to that PR's repository.

### Bounded candidate display (unreleased)

`discover --limit N` accepts ASCII decimal integers from 1 through 1000 (leading
zeros are allowed). Zero, negatives, non-decimal values and larger integers
return a structured `invalid_limit` error (exit 1) before any GitHub reads,
including `--report-budget`. A missing value is a usage error (exit 2).

The limit applies after all existing discovery scans, pagination, fork resolution,
ranking and opted-in reports. It changes neither read bounds nor `--check-top`'s
own budget. It slices the final ranked `issues` list for one repository. With
several repositories it slices the merged ranked `candidates` list globally,
then retains only those entries in each repository's `issues` list. A repository
may show zero candidates; its resolution, policy, reports, errors and provenance
are still present. The full per-repository and aggregate scan status stays intact.

Limited responses add `display` (also on each repository in a multi-repository
run), with:

- `requested_limit`: the normalized requested budget, shared across repositories.
- `total_issues_considered`: successfully inspected observed entries before display
  projection; inaccessible or malformed issues are not counted. Multi-repository
  totals count each requested repository's entries, even when trackers are shared.
- `returned`, `omitted`, `truncated`: retained entries, omitted entries, and whether
  any observed entry was omitted. These describe the display, not read completeness.
- `overlapping`, `excluded`: counts from the full observed list, including entries
  omitted by the limit. These counts do not waive blockers or approve work.

Text shows these totals and keeps its existing 20-row abbreviation; any extra
retained entries are available in JSON. Omitted entries are absent from both
lists; rerun without `--limit` for their details. Check `complete`, `errors` and
provenance independently. Even an unresolved repository has zero-count display
metadata. With no `--limit`, output and reads are unchanged and no `display`
field is added. These optional fields extend the unreleased output/1 candidate;
task and evidence schemas and their versions are unchanged.

### Opt-in ranking signals

`discover --signals` adds deterministic, explained heuristics to each issue
without extra API calls. Without the flag, output and ordering are unchanged.

- `code_location`: paths in the issue title/body (first 64 KiB) that exist in
  the snapshot tree, including repository-relative suffixes of stack-frame
  paths and file names that match exactly one tree path (at most 20). It is
  `unknown` when the tree read was incomplete. Module names of two or more
  segments joined by `.` or `::` (`pkg.mod`, `pkg.mod.func`, `crate::a::b`)
  also count when they name exactly one file: the file's path without its
  extension, or a package directory holding `__init__.py`, `mod.rs` or
  `index.*`, must end with the segments. A leading Rust `crate`, `self` or
  `super` is ignored. Trailing segments are treated as members, so the longest
  prefix that names any module decides; an ambiguous match gives no hint and
  never falls back to a shorter prefix. Single names (`signals`), names inside
  paths, names of more than 16 segments or longer than 300 characters (as a
  slash path), and a name cut off by the 64 KiB scan limit are refused whole;
  a name is never shortened to fit. Names are matched on regular-expression
  word characters (letters, digits and `_` in any script), so `äpkg.mod`
  resolves as a whole and `pkg.mod` inside it is never resolved on its own. A
  name containing other identifier characters, such as combining marks, `℘` or
  `·`, is refused; its fragments are never resolved either.
  Path and file-name matches come first and the same limit of 20 applies.
  `named_paths_missing` lists repository-relative file paths the issue names
  (`docs/x.md`, `./src/a.rs`, `.github/ci.yml`; a last segment with an
  extension) that the snapshot tree does not contain, at most 20 in order of
  appearance. The named path is compared exactly: unlike hints, an existing
  suffix (`src/a.rs` for `old/src/a.rs`) does not count. It is a heuristic, not
  a URL parser; it skips absolute paths, ordinary URLs, domains, `..` traversal and
  tokens cut at 300 characters, and it is empty when the tree is unknown. It is a
  staleness cue only: it does not change `value`, `score` or ordering.
- `acceptance_clarity`: `high`, `medium` or `low` from checklists,
  expected/actual sections, reproduction steps and code blocks.
- `activity`: age and last-update days, comment and reaction counts from the
  issue list payload; malformed fields are `null`.
- `maintainer`: whether the issue author's association is OWNER, MEMBER or
  COLLABORATOR.
- `labels`: the issue's label names (sanitized, at most 100).
- `demotion`: documented, report-only demotions with one reason each. A label
  matches a phrase when the phrase's words appear as whole words in the
  lower-cased label name, with punctuation and separators read as spaces
  (`Status: On-Hold` matches `on hold`; `blockedness` matches nothing). Each
  group counts once:
  - on hold or deferred: `icebox`, `on hold`, `blocked`, `deferred`,
    `postponed`, `frozen`;
  - needs a decision or design discussion: `needs decision`, `needs design`,
    `needs discussion`, `discussion`, `question`, `rfc`, `proposal`;
  - not planned or not this project: `not planned`, `out of scope`,
    `upstream`, `third party`, `wont do`;
  - major-version or breaking-change bucket: only an explicit bucket, where the
    label or its last `:` or `/` part is exactly `breaking`, `breaking change`,
    `breaking changes`, `vN` or `vN.x` (`v5`, `kind/breaking`, `target: v6`).
    `non-breaking`, `v5-compat` and `bug: v5 regression` are not buckets.
  A phrase right after `non`, `not`, `no` or `un` does not match, so
  `not blocked` and `no discussion needed` are not demotions.
  A title counts as meta-like when it starts with `meta`, `wip`, `tracking`,
  `tracker`, `roadmap`, `rfc`, `umbrella` or `epic` followed by `:`, `]`, `)` or
  `-`, or contains `meta issue`, `tracking issue`, `umbrella issue`, `roadmap`
  or `features list`. These rules come from dogfood evidence where icebox'd,
  maintainer-reserved `v5`, question-labelled and tracking issues ranked first.
  They are heuristics: a label can be stale, and titles can mislead.
- `score`: one point for found locations, up to two for clarity, one for a
  maintainer author unless the title is meta-like, minus two per demotion,
  never below zero.

`--check-top N` (1-5, with `--signals` and one repository) then reads the
existing ownership signals (as `inspect --ownership`) for only the top N
candidates. Each check reads the first timeline and comment page and at most 4
cross-referenced PR details, and all checks together make at most 30 reads.
Each read is one GitHub GET with no retry, so a transient failure marks the
check incomplete instead of making extra requests.
Reaching a cap, or a failed read, marks that check `complete: false`, and an
incomplete `top_check` exits 1. A checked issue is demoted when it has a
merged same-repository PR that references it exactly ("possibly already
fixed") or a current assignee. Claim comments never demote: comment prose is
untrusted and easy to misread (quoted instructions, code examples, other
issues), so claims stay visible only in the report-only `inspect --ownership`
output. A demoted issue then moves below every other candidate that is not
excluded or overlapping (known bad below unknown); relative order is otherwise
kept and issues below the top N are never read. Each
demotion is listed in the issue's `top_check.demotions`. No maintainer
"reserved" or "rejected" detector exists, so none is used. A clean or
incomplete check proves nothing, gates and overlap are unchanged, and the
reads appear in `--report-budget`. In live runs with N=5 it made 13-18 reads
and demoted ripgrep #2528 and hono #1018, both judged bad by that evaluator, to ranks 59 and 183.
Precision@5 stayed 1/5, 1/5 and 0/5 for click, ripgrep and hono: the issues
that moved up (ripgrep #1221, hono #2649) were judged bad too.

`tests/test_ranking_eval.py` replays a frozen dogfood-2 snapshot (public titles,
labels and signal inputs for click, ripgrep and hono, with the dogfood
evaluator's judgements; the evaluator was a model, Claude Opus 5.5, and no
separate human review was done) and checks precision@5 and the ranks of known bad labelled or meta issues offline.
The demotions move those issues out of the top ranks but do not raise
precision@5 on that snapshot (click 1/5, ripgrep 1/5, hono 0/5 before and
after): most remaining false candidates are design debates, already fixed or
not this project's bug, with no label or title cue.

Ordering stays exclusions first, then overlaps; with `--repo-dir` or
`--check-top` the next key is known-bad issues (locally referenced or demoted by
the check), which rank below every other candidate. Then low success likelihood;
only then does a higher `score` come first, with the issue number as the final
tie-breaker. Signals are heuristics. They never approve, authorize or replace
reading the issue.

`discover owner/repo --repo-dir CHECKOUT` (one repository) adds a report-only
`local_work` object for unpublished local work. A commit closes issue N only when
one line of its message, after stripping surrounding ASCII whitespace, is exactly
`<keyword> #N` or `<keyword> owner/repo#N` for the source repository (owner and
name in any case). The keyword is one of `fix`, `fixes`, `fixed`, `close`,
`closes`, `closed`, `resolve`, `resolves` or `resolved`, in any case, optionally
followed by a colon, then one space. Nothing else may be on the line, so lists
(`Fixes #1, #2`), inline mentions, `Refs #N`, PR numbers, other repositories and
quoted examples never count, and Markdown is not interpreted (a line that is
exactly `Fixes #12` counts even inside a code block). The rule is conservative by
design: under-counting only means an issue is not demoted. Only commits
reachable from the checkout's HEAD but not from the snapshot's source
default-branch commit are read. It lists the newest 500 commits at most,
checks each commit object's size before reading any message, and reads only
whole messages: a commit larger than 64 KiB is skipped, and reading stops once
messages would exceed 4 MiB in total. Reads use the hardened Git reader after the
worktree-root and checkout-config checks. A missing base commit (the CLI never
fetches), a missing or non-Git `--repo-dir`, a shallow checkout (a shallow
boundary can hide commits), an unsafe
config, a subdirectory, more than 500 commits, a skipped message or a message
containing a NUL byte make it incomplete, which exits 1. Messages are read from
the raw commit objects (`git cat-file --batch`), never reformatted, and commit
headers such as the author are not parsed. With `--signals`, each issue gets `signals.local_work`
(`referenced`, `none` or `unknown`), and a referenced issue ranks below every
other candidate that is not excluded or overlapping. Its score, gates and
exclusions are unchanged. Without `--signals` the issue order is unchanged. A
reference is not proof that the work is done.

### Repository responsiveness

`discover --responsiveness` makes exactly one additional GET for the issue
source repository, `repos/{source}/pulls?state=closed&sort=updated&direction=desc&per_page=100`,
and adds a top-level `repository_signals.responsiveness` report. Without the
flag, reads and output are unchanged, including with `--signals`. The report is
a one-page sample of the most recently updated closed PRs, never full history:

- `sample_size`: closed PRs read; `external_closed` and `external_merged`: of
  those, PRs whose author association is not OWNER, MEMBER or COLLABORATOR and
  whose author is not a bot.
- `value: measured` with `external_merge_rate` and `median_days_to_close`
  (creation to close, merged or not) when at least `minimum_external` (5)
  external PRs are present; otherwise `insufficient`, with the rate and median
  `null`.
- `value: unknown`, `complete: false` and an error when the read fails, a page
  or entry is malformed (including a missing `merged_at` field, a merge time
  outside the PR's creation-to-close interval, or a missing or repeated PR
  number), or discovery did not complete
  its source snapshot (then nothing is read).

Each report has an `explanation`. No PR text is copied. The report never changes
approval, exclusions, overlaps, ordering or discovery `complete`. As with
`inspect --ownership`, exit 1 also covers an incomplete opted-in report; in a
multi-repository run each repository carries its own report. Author association
is not verified identity, and responsiveness is a heuristic, never approval.

### Several repositories

`discover` accepts several repositories as arguments and/or
`--repositories-file FILE` (UTF-8, at most 64 KiB, one `owner/repo` per line,
blank lines and `#` comments ignored). With exactly one repository the output is
the unchanged single-repository result. With 2 to 20 distinct repositories it
returns `repositories` (each repository's complete single-repository result, in
input order), `candidates` (every issue with its repository, reference and the
ordering facts), `errors` prefixed with the repository name, and top-level
`complete`, true only if every repository is complete. A failing repository
never aborts the others or marks them complete. All identifiers are validated
before any read. The merged order is exclusions, overlaps, low likelihood,
higher signal score with `--signals`, then repository and issue number.

Reads cost the sum of the single-repository runs; combine with
`--report-budget --min-remaining N` on large lists. A display cap such as the
proposed `discover --limit` (#1) would apply per repository. Deriving
repositories from a dependency graph is out of scope.

### Repository policy report (default-on, report only)

`discover` (once per repository), `inspect` and `prepare` add `repository_policy`
in the CLI output. The report changes no core result, contract field,
`instructions_sha256` or exit code. Separately, `prepare` now writes a pending
`ai-policy-review` prerequisite into new contracts; existing contracts are unchanged. `--ai-policy` is deprecated: it is
accepted, changes no output or exit status, and writes one notice line to stderr (best effort: a missing,
closed or readerless stderr changes nothing). The earlier unreleased `ai_policy` excerpts and
the `agent_contribute.aipolicy` module no longer exist.

- **Inventory.** The issue source repository (never a requested fork) at the
  observed commit. It covers the loaded instruction files plus policy-named
  files at any depth. A name matches when it equals a prefix or continues it
  after `.`, `-`, `_` or a space, case-insensitively: `contributing`,
  `contribute`, `ai`, `llm`, `agents`, `claude`, `gemini`,
  `copilot-instructions`, `pull_request_template`, `code_of_conduct`,
  `code-of-conduct`, `security`, `support`, `governance` (nested copies of these
  five are read after top-level ones and their hints rank lower, but they are
  never skipped), and a root `readme`.
  So `CONTRIBUTING.en.md`, `AI_USAGE_RULES.md`, `SECURITY-POLICY.md` and
  `README.development.md` all match. Also matched: `.cursorrules`,
  `.cursor/rules/*`, `llms.txt`, `.github/PULL_REQUEST_TEMPLATE/*`, and files
  under `contributing/`, `contributors/`, `contribute/`, `policy/` or
  `policies/` directories.
  - Paths are classified in full and displayed shortened to 500 characters,
    with `path_truncated`.
  - Core instruction paths of 500 or more characters may already have been
    shortened, so they are listed as an unresolved identity.
  - The owner's `.github` repository (root, `.github/`, `docs/`) is read at its
    default-branch commit. Contents are read by commit SHA, and the decoded
    bytes must hash to the tree's Git blob SHA.
- **Formats.** `.md`, `.markdown`, `.rst`, `.txt` and extensionless files are
  scanned. Other document formats with a policy name (`.adoc`, `.pdf`, `.html`,
  `.docx`, `.odt`, `.org`, `.textile`, `.rtf`, `.mdx`) are listed in
  `unassessed` as `unsupported format`. Code, data and image files are not
  policy candidates.
- **`sources_scanned`.** Origin, repository, path, commit, SHA-256 of the file
  bytes, scan kind, and notes such as `paragraphs with non-Latin script not
  assessed: N`. The vocabulary is English only.
- **`unassessed`.** Policy-like links from any scanned file, including READMEs
  (`referenced, not assessed`; links to a scanned file at the same revision are
  omitted). Also unsupported formats, failed reads, an owner `.github`
  repository that is `not found or inaccessible` (never "absent"), and content
  that did not match the pinned tree entry.
- **`hints`.** Attention labels, not classifications:
  - `possible_agent_restriction`, `possible_ai_restriction` and
    `possible_pr_restriction`: an agent/automation, AI or pull-request term
    within 12 words of a restriction word.
  - `ai_mention`: any AI or agent term.

  Paragraphs are joined across wrapped lines, and headings are kept as context.
  HTML comments are scanned, and entities, tags, fullwidth forms and zero-width
  characters are normalized. Adding sentences or paragraphs before or after a
  passage never removes its hint kinds. Inserting words between the matched
  terms can move them out of the 12-word window, and so can added text that
  turns an existing line into a heading. Excerpts are sanitized and at most 300
  characters, start late enough that the restriction word lies within their
  first 170 characters, and carry `excerpt_truncated` when text before or after
  was left out.

  Hints are ordered for attention: agent, then PR submitter-eligibility rules (a
  PR term near "limited", "restricted", "invitation" or "instead", or near both
  "only" and an actor such as "maintainer" or "members": "Pull requests are
  limited to maintainers", "Only a maintainer may submit"; not review
  requirements), then AI restrictions, then PR restrictions whose paragraph also
  names AI or agents, then PR restrictions in
  policy files (AI policy, agent instructions, contributing, PR templates), then
  other PR restrictions, then restrictions from nested security, support,
  governance or conduct files, and mentions last. When the 100-hint bound or the
  report-size bound applies, mentions are dropped first. A dropped restriction
  hint is counted as `restriction hints` or `report size: restriction hints`,
  which `hides_sources`.
- **`limits_reached` and `reads`.** At most 25 logical GitHub requests per
  report (each with the client's usual three attempts), 12 source and 8 owner
  policy files, 200 kB per file and 1 MB scanned, all counted in UTF-8 bytes. The report keeps 100 hints,
  50 unassessed entries and 256 kB serialized, and identifiers are truncated
  with `what_truncated`. Anything dropped is counted in `limits_reached`. To
  fit the size bound, hints go first, then unassessed entries, then long source
  paths are shortened, and finally source records are left out. Each step is
  recorded as a `report size: ...` limit.
- **Identity.** Every source, omitted candidate and unassessed entry has
  `identity_sha256`, a hash of its original repository and path (or URL) as
  read from GitHub. Displayed paths can be shortened (`path_truncated`,
  `what_truncated`) or sanitized of control and format characters
  (`path_sanitized`, `what_sanitized`), so two entries can look alike. The
  identity, not the display text, is what deduplication and `inventory_sha256`
  use.
- **`hinted_lines` and `project_vocabulary`.** `hinted_lines` is the reading
  list: one entry per hinted source line in attention order, with every hint
  kind on that line. Lines whose only hints are mentions made of the project's
  own name (for example "agent" in a repository named `agent-kit`) are
  summarized in `project_vocabulary` with a count and bounded line list.
  Restriction hints are never summarized, and `hints` still lists every
  retained hint.
- **Hint IDs.** `hints[].id` is `H-` plus the full SHA-256 (64 hex digits) of
  the canonical JSON `["policy-hint/1", source identity_sha256, line, kind]`.
  It never depends on report position, so a disposition recorded by ID keeps
  naming the same line when other sources or hints change the order, or a later
  build reorders the report. An edit that moves the line changes the ID. If two
  hints ever shared an ID, the first is kept, the others are dropped and counted
  as `hint_id_collision`, a limit that hides sources, so the review stays
  unresolved.
- **`omitted_sources` and `hides_sources`.** A policy candidate that a file,
  byte or request limit left unread is named in `omitted_sources` (at most 50,
  with its repository, path, kind and reason; overflow is counted). Each
  `limits_reached` entry says whether it `hides_sources`; hint limits do not.
  `limits_hide_sources` is true when any limit hides a source or reference. The
  workflow then treats repository policy as unresolved until every omitted
  candidate is read manually or shown inapplicable.
- **`never_inspected`.** A fixed list: wikis, external websites, images and PDFs,
  comments, other repositories, non-Latin text.
- **`owner_lookup`.** The owner `.github` lookup outcome: `read`,
  `not_found_or_inaccessible` (HTTP 404 from the repository metadata lookup
  only), `unavailable` (any other failure, including a 404 on the commit or tree
  after the repository was found,
  recorded as the hiding limit `owner lookup` because its policy files are
  unknown), `not_read_request_limit` or `not_applicable`. It is part of
  `inventory_sha256`, so a change such as readable to not found is drift, and
  `drift --policy-sha256` treats an `unavailable` lookup as incomplete.
- **Unread candidates.** Unassessed and omitted file entries carry `blob_sha`,
  the pinned Git blob id from the tree, so an edit to an unread policy file
  (such as `AI_POLICY.adoc` or an oversized `AI_POLICY.md`) changes the
  inventory hash. Policy-like links to files in the pinned tree (such as
  `docs/rules.md`) carry that file's blob id too, without a new read, as do
  `github.com/OWNER/REPO/blob|tree/REF/PATH` links into either inventoried
  repository (the source or the owner `.github`, in both directions) whose REF
  is that repository's default branch or pinned commit (host and owner case, `www.`,
  `http://`, protocol-relative forms, fragments and queries are accepted). A
  known file without a valid blob id, or a blob/tree link into an inventoried
  repository that cannot be resolved to its pinned tree (another branch, a tag, an unknown ref,
  a missing path or a directory), is the hiding limit `unfingerprinted files`.
- **`inventory_sha256`.** A hash of the scanned sources' bytes, the retained
  unassessed identifiers and the limits. It excludes commit SHAs, so unrelated
  pushes do not change it. No verifier checks it; the workflow records it in
  prerequisite `ai-policy-review`.
- **`inventory_format`.** The version of the material that `inventory_sha256`
  hashes, itself part of the hash (currently 2). Format 1 is the unversioned
  hash of earlier 0.3.0 candidate builds. Any change to the hashed material
  bumps it, so a hash recorded under another format is recognizable.

With `--format text`, the Policy line is followed by up to five restriction
hints in attention order, for example `! possible_ai_restriction
pallets/.github:CONTRIBUTING.md:22 -- AI-generated PRs and issues are closed on
sight...`, and a count of the rest. Shortened excerpts end with `...`. Restriction
hints that limits dropped are counted separately. With none it says "No
restriction hints; this is not permission.", or "No restriction hints retained"
when limits dropped hints or hid sources.
Up to five unassessed references and files follow, one per line, sanitized and
shortened to 150 characters, for example `? https://palletsprojects.com/contributing/
(referenced, not assessed) from pallets/click:README.md:62`, and a pointer to
`repository_policy.unassessed` for the rest.

There is deliberately no `coverage`, `complete` or `clear` field. Hints are
noisy on purpose. The installed workflow's mandatory policy review decides what
they mean, and that review is not verifier-enforced.

### Ownership and resolution signals (report only)

`inspect --ownership` adds `ownership_signals` to the normal inspect result;
`ownership 'owner/repo#123'` prints them with repository resolution. Without
the flag, `inspect`, `prepare` and `verify` neither read nor report them, and no
approval, overlap or readiness decision changes in any schema version.

Reads: the issue timeline and comments (complete pagination; timeline events
without IDs are deduplicated by content), then a fresh `pulls/{n}` read for
each cross-referenced PR (at most 50, otherwise incomplete). Each PR reports
repository, repository ID, number, sanitized `title`, `base_ref`, state, draft, merged,
merge/close times and `exact_reference`: whether the PR text references this issue exactly (local
`#N` only in the issue's own repository, `owner/repo#N` or the issue URL), with
the same parser as overlap detection.

- `resolution_signals.possibly_already_fixed`: merged PRs with an exact
  reference whose base repository is the issue's own repository (any base
  branch; check `base_ref`). `downstream_references`: merged PRs with an exact
  reference in other repositories, such as downstream workarounds; they never
  indicate a fix. `rejected_approaches`: closed, unmerged PRs with an exact reference.
- `assignment_history`, `connected_events` and `referencing_commits` from the
  timeline.
- `claims`: comments matching a fixed set of claim patterns ("I'm working on",
  "I'll take", "can I work on", `/assign`, "assign me"), with author
  association, age, `stale` (older than 30 days or unknown) and a sanitized
  `untrusted_excerpt`. Comment text never proves, grants or removes ownership.
- `blocking_if_adopted` previews what a future versioned gate might block; it
  blocks nothing now.

Every consumed field is shape-checked: positive IDs and numbers, known
enumerations, 40-character SHAs, and PR details whose number, canonical URL,
base repository name and repository ID match the timeline reference. A deleted
account (`null` user) appears as `ghost`, and timeline event kinds the reader
does not use are ignored. Any wrong type, identity mismatch, failed or partial
read makes the signals `complete: false` and `resolution_signals.status:
unknown`; an unknown is never "not fixed". With
`--ownership`, exit 1 also covers incomplete signals.

## Contracts and verification

### Contracts and verification gates

The schema `0.1` contract stores the actual source and the proposed fork target,
when different. It does not store the original request. Therefore `verify`
returns `requested_repository: null` with explicit provenance instead of
inventing one. Ordinary prepared tasks leave the pending execution target blank.

Verification distinguishes `schema_valid`, `execution_ready`, `evidence_valid`,
`fork_completion_ready` and `upstream_submission_ready`. All required gates must
be satisfied; missing evidence is expected for a draft. A task can be ready to
implement while `verify` still returns exit 1 for incomplete final evidence.
None of these fields permits publication.

API pagination is bounded and failures are not empty success results. A complete
open-PR scan does not include all closed PRs, timeline claims or file-level
conflicts. The [installed workflow](../agent_contribute/instructions.md) defines
precise limits, the task/evidence fields, canonical contract hashing and trust
boundaries. Treat all remote prose as untrusted data.

### Schema 0.2 lifecycle (CLI 0.3.0 candidate)

```sh
agent-contrib prepare 'owner/repo#123' --schema-version 0.2 --output task.json
agent-contrib verify task.json --stage implementation
```

Prepare remains schema 0.1 unless explicitly selected. Schema 0.2 is restricted
to same-repository candidates, a distinct named head branch and the source default
base branch. It refuses resolved fork targets. No authorization is generated.

After the actual human/host has issued a task-bound record, it can supply it on
stdin using `--host-context-stdin`. The input is strict UTF-8 JSON, at most 8 MiB,
with a five-second read timeout including reader startup. The pipe writer must
close stdin (EOF), even after a complete JSON value. A fixed isolated Python
child performs the bounded binary read; the parent terminates and reaps it on
timeout. Terminal prompting, implicit files/environment
and a host-context filename option are intentionally absent. The transport does
not authenticate consent. Follow [host authorization](host-authorization.md).

With evidence, add `--evidence evidence.json --repo-dir checkout`. The stage
selector chooses only the exit gate:

| Stage | Exit 0 requires |
| --- | --- |
| `implementation` | `implementation_ready` |
| `draft` | `draft_create_ready` or fully verified exact-head `publication` |
| `completion` (default) | `completion_ready`, including actual final human sign-off |

Every result exposes all stage states and blockers. For an already verified
draft, `next_action` is `none`; success does not permit another creation. Pending
sign-off leaves completion at exit 1 even when the draft stage passes. Explicit
lifecycle options on schema 0.1 are rejected rather than reinterpreted.

Exact-head PR history is read only under a valid mandate. Without one, the
implementation and draft blockers say `Exact-head PR history not checked:
requires a valid mandate`; both gates stay blocked.
The prerequisite blocker lists each prerequisite that is not `satisfied` with
non-blank evidence, as `ID (status)` or `ID (satisfied without evidence)`.

`instructions.resources` lists both task/evidence versions and host-context
schemas 0.1 and 0.2.

When a host-context 0.2 document carries a `draft_update` record (#21), `verify`
adds a `draft_update` report and recognizes the draft only after its one
fast-forward update (slice 2). The record's contract, mandate, credential,
repository, PR, event, interval and identity bindings must check out, else the
status is `invalid` and no publication is read. With a record present, the
draft at its creation head is never recognized. The status is then:

- `recognized`: the live PR head `P` equals the validated evidence HEAD `E`,
  `P != from_head`, and `compare from_head...P` is `ahead`. The creation head
  precedes both `from_head` and `P`, and the PR is still the one claimed open,
  unmerged draft by the bound actor, created inside the mandate interval and
  not in the future. Its complete timeline has no force-push, head-ref
  deletion or restore, close, reopen, merge, ready-for-review or
  convert-to-draft event. A final re-read equals the first and keeps the
  route. The evidence is based on the reviewed source commit exactly, has no
  merge commit in `from_head..E` and only validations started after the
  round's `issued_at`. `publication.verified` is true at `E`; completion also
  needs a final sign-off for `E` issued after the round.
- `not_evaluated`: the PR is still at `from_head`, so no update was pushed.
- `blocked`: anything else, with the reasons in `errors`.

Every comparison must be internally consistent (status, commits and counters),
or it blocks. `candidate_head` is `E` exactly when the status is `recognized`,
else `null`; `live_head` is the PR head of the first complete read, or `null`.
The record may have expired after the push; `current` reports whether its
interval contains the verification time, judged after every read. Pre-push
readiness is not evaluated: no `next_action` asks for an update or a push, and
nothing here authorizes a push. Without the section the output is unchanged.
See [host authorization](host-authorization.md#draft-update-rounds-host-context-02).

With a host-context 0.2 document, `verify` adds `overlap_dispositions` and
`waived_duplicates`. The status is:
- `absent`: no record;
- `invalid`: a schema, binding or expiry error. Nothing is waived. A record
  rejected on its own checks makes no extra read, but one that expires during
  the reads becomes `invalid` only after them;
- `evaluated`: the record's contract, mandate, credential, event, interval and
  entry bindings check out.

For an `evaluated` record, `verify` reads each disposed PR (`pulls/{n}`) and each
distinct base-branch tip (`git/ref/heads/{ref}`): at most 20 PRs and 20 refs. It
recomputes the match and reconciles it with the open-PR scan. It removes a PR
from the blocking lists only when all of these hold:
- the scan was complete;
- the match is the same topical one (never a direct reference);
- the author is not the credential actor;
- every bound observation is equal (ID, URL, repository, author, state, draft,
  head repository and SHA, `updated_at`, title/body/ref hash and base tip);
- the record is still unexpired after all reads.

A direct reference, contradiction or failed read seen in that read blocks. A
direct reference first seen there is also added to `duplicates` with
`observed_in: "disposition_read"`; a failed read is a blocker only, never a
claimed overlap. A waived PR stays in `duplicates`. Waivers never remove any other blocker; text
output names them. A record that expires during the reads fails every stage
closed. Library callers may pass host context explicitly to `core.verify`;
that is the same host-asserted boundary as the CLI, not a privileged API.

### Offline contract lint

`lint task.json` reads one contract and nothing else. It validates it against
the bundled task schema for its `schema_version` (unknown versions fail), and
for a schema-valid contract it applies the same reviewed-contract rules that
`verify` checks: reviewed status with no open questions, required fields,
concrete repository-relative scope, unique IDs, a definition of done covering
every criterion and validation, complete prepared discovery and satisfied
prerequisites. `reviewed` (and exit 0) means only that the contract is ready
for `verify`. It says nothing about the live issue, approval, overlap,
authorization or evidence, and it never runs validation argv.

### Drift since preparation

`drift task.json` compares a schema-valid contract with the live source and
never writes anything. It reports:

- `source`: stored and current source repository and issue URL, and for 0.2
  stored and current repository, owner and issue numeric IDs. Any difference,
  such as a fork tracker switch or a recreated repository, is drift; an
  unresolved 0.2 identity makes the report incomplete.
- `issue`: whether the combined issue hash changed, stored and current
  `updated_at`, and the current title/body hashes, state, labels and assignees.
  Per-component baselines are unavailable because schemas 0.1 and 0.2 store one
  combined hash.
- `instructions`: the files `added`, `removed` and `modified` (path and both
  SHA-256s). The baseline is reconstructed by re-reading the instruction files
  at the contract's immutable `source.commit`; it is used only when its
  aggregate equals the stored `instructions_sha256` (`baseline_verified`).
- `default_branch`: stored and current branch and commit. An advanced commit
  alone is informational and not drift.
- `policy`: stored and current approval status, plus policy hashes for 0.2.
- `overlap`: open source-repository PRs added to or gone from the prepared list.

The issue component read must hash to the same value as the inspection it
accompanies; if the issue changed in between, the report is incomplete. Exit 0
only when every read completed and nothing drifted. Any failed read,
including an unverifiable baseline, gives `complete: false`. The pinned re-read
costs another snapshot's worth of reads. After drift, review and prepare the
contract again.


`drift task.json --policy-sha256 HASH` also re-reads the repository policy
inventory at the current default-branch commit and adds
`repository_policy_drift`. HASH is the `inventory_sha256` recorded in the
`ai-policy-review` prerequisite evidence; a malformed value is a usage error
before any read.

- `policy_drifted` is `true` when the current inventory hash differs (it then
  counts as drift, exit 1), and `null` when the current read is incomplete or a
  limit hides sources (incomplete, exit 1).
- When the inventory rebuilt at the contract's pinned commit reproduces HASH
  (`baseline_verified`), `added`, `removed` and `changed` list every inventoried
  candidate by `identity_sha256` and `what`, with its `state` (`scanned`,
  `unassessed: <reason>` or `omitted: <reason>`) and `fingerprint` (content
  SHA-256 when scanned, pinned blob id when unread). Otherwise they are `null`:
  the owner `.github` repository is read at its current tip, so a baseline cannot
  always be rebuilt, and no deltas are invented.
- `current_inventory_format` is the current report's `inventory_format`.
  `recorded_inventory_format` is the format under which the current report or the
  pinned baseline reproduces HASH, or `null` when neither does. When the pinned
  baseline reproduces HASH only under another known format (a hash recorded by an
  earlier build), the note says so instead of suggesting a moved owner
  repository; it is still drift (exit 1): re-review and record the new hash.
  When nothing reproduces HASH, the note says it may come from a different
  inventory format, a moved owner `.github` repository or another snapshot.

This catches an edit to a policy-only file such as `SECURITY.md` or a new
`AI_POLICY.md`, which `instructions_sha256` does not cover. It costs up to two
policy reports (at most 25 requests each).

### Required CI checks (schema 0.2 completion, opt-in)

A reviewed schema 0.2 contract may declare `ci_requirements`: 0 to 20 unique
`{"check": NAME, "app_id": N}` pairs. `check` is 1 to 200 characters without
control or format characters, and `app_id` is a positive integer. A non-empty list
needs `create_draft` in `execution.requested_actions`. An absent or empty list
changes nothing: no reads, no output, no blocker.

With requirements, once an exact-head published draft is verified, `verify` reads
every check suite and then every check run (`filter=all`) for the evidence
`git_head`, within a 50-request budget. It adds `ci_gate`. A requirement is `met`
only when all of these hold:

- every check run whose raw name is exactly `check`, from app `app_id`, on that
  head, is completed with `success`;
- every check suite of that app on the head is completed;
- at least one such run exists;
- both reads are complete, consistent and cover fewer than 1,000 suites.

There is no latest-attempt selection: a retained failed attempt blocks even if a
retry succeeded. Other states, decided in this order:
`unknown` (incomplete or inconsistent reads, the suite window, an exhausted
budget), `failed`, `not_met` (neutral or skipped), `pending` (an unfinished run,
`action_required`, or an unfinished suite of that app, such as after a
rerequest), and `missing`. Same-name runs from other apps are counted, never
accepted, and commit statuses never count.

A contract with requirements also cannot complete when the implementation diff
touches `.github/` (additions, deletions and renames). Every gate blocker appears
only in `stage_blockers.completion`; the implementation and draft gates and the
`--observe-ci` report are unchanged. The gate observes the results GitHub
currently retains for that head. It does not prove which tree a job checked out,
and it never replaces review or final sign-off. Design:
[docs/design/2026-11-03-ci-gating.md](design/2026-11-03-ci-gating.md).

## Local checkout tools

### Checkout requirements

`--repo-dir` must be the Git worktree top level. `verify`, `scope-check` and
`evidence init` refuse a subdirectory or Git directory, because tree, index and
untracked-file reads there would omit the rest of the checkout. They also refuse an
index with assume-unchanged or skip-worktree entries, including any sparse
checkout, because Git status and diff would hide changes to those files. The
index is only read, never changed; clear the flags or use a full checkout.
A checkout whose effective Git config (including `include`/`includeIf` files)
sets a key a read could run as a program or use to fetch is refused with
`unsafe_git_config`: `filter.*`, `gpg.program` and `gpg.*.program`,
`diff.external`, `diff.*.command`, `diff.*.textconv`,
`extensions.partialClone`, `remote.*.promisor`, `remote.*.partialCloneFilter`
and `protocol.*`. Git reads also force `log.showSignature=false` and
`protocol.allow=never` and disable lazy fetching, so a missing object is a read
error, never a fetch. Credential, SSH, askpass, pager, editor and merge-driver
settings are not refused because none of the fixed read commands reaches them.
Reads also force full stat and mode checks (`core.checkStat=default`,
`core.trustctime=true`, `core.ignoreStat=false`, `core.fileMode=true`, and
`core.symlinks=true` on POSIX), so
relaxed checkout settings cannot hide an edit or an executable bit; on a
filesystem without executable bits every file then looks changed, which fails
closed. `core.ignoreCase=true` is refused on a case-sensitive filesystem, where
it would hide case twins, and accepted where the filesystem really ignores case.
Worktree content is compared with a commit through a fresh temporary index
outside the checkout, so the checkout's stat cache is never trusted; every
tracked file is hashed on each run. Each file's bytes must equal either the
committed blob or exactly what checkout writes for it (`cat-file --filters`,
with `core.autocrlf=false` and `core.eol=lf`). Git takes those attributes from
the checkout's `.gitattributes` files; a changed tracked one is reported as a
change, and an untracked one is always reported (even when a committed
`.gitignore` would ignore it) and is never within `scope-check` scope. So `ident`, `eol`/`text` and `working-tree-encoding` cannot hide
an edit, and an untouched checkout with those conversions stays clean. A CRLF
copy produced only by a local `core.autocrlf` reports as changed. A non-empty
`.git/info/attributes` is refused with `unsafe_git_attributes`;
`core.attributesFile` and system attributes are always ignored.

### Offline scope check

`scope-check` evaluates the working diff against the contract's
`scope.allowed_paths` and `scope.prohibited_paths` with the same function that
`verify` uses for evidence. It reads only the local checkout: committed changes
from `--base` (default: `source.commit`) to HEAD, staged and unstaged changes,
and untracked files that are not ignored. Only per-directory `.gitignore` files
count as ignore rules; `.git/info/exclude` and `core.excludesFile` never hide a
file, and an untracked `.gitignore` is always reported. Files ignored by a
committed `.gitignore` are not reported (`verify` and `evidence init` apply the
same rule). Renames report both paths. The base
must be an ancestor of HEAD; gitlinks fail closed. `--base` accepts exactly a
full 40-character SHA, `HEAD`, or a full ref name such as `refs/heads/NAME` or
`refs/tags/NAME`, each optionally followed by `~N` or `^N` (for example
`HEAD~3` or `refs/heads/base~1`). Short branch or tag names, abbreviated SHAs
(convert with `git rev-parse ABBREV`), pseudo-refs other than `HEAD` and other
revision syntax (`:/text`, `@{...}`, `REV^{type}`, paths, ranges) are refused.
`HEAD` and `refs/...` names are looked up exactly with `git show-ref --verify`,
never through Git's short-name lookup, so a same-named ref such as
`refs/tags/HEAD` cannot stand in for them; an unborn `HEAD` is refused. The
object ID is captured first, then the suffix and `^{commit}` are applied to it
with `git rev-parse`.
Every read uses the same hook, fsmonitor and replacement-object protections as
other Git reads, and nothing under `.git` is opened directly. `base_commit`
reports the full SHA. A value that is blank, starts with `-` or contains
whitespace or control characters is refused. When the default base is not an ancestor of HEAD,
`warnings` suggests passing `--base` for stacked or rebased work; the result
still fails. When the default base is an ancestor but more than one commit
behind HEAD and out-of-scope paths changed, `warnings` names the base, the
commit count and suggests `--base`; the violations and exit status are
unchanged. It makes no GitHub calls, so it can run as a pre-commit hook. Exit 0
means "no scope violation found", not evidence, readiness or authorization.
Each violation names the path and either the first matching prohibited pattern
or `not in allowed_paths`.

A changed path that is a symlink is also judged by its target, the same way in
`verify` and `scope-check`. The target comes from the commit, the index or the
worktree that holds the link, read without following it. It is resolved
lexically from the link's directory, expanding every link hop, including links
to directories, up to 40 hops. The link is a violation, with the reason as its
rule, when the target is absolute (`/x` or `C:/x`), contains a backslash,
escapes the repository, points at the repository root, is longer than 4096
bytes, contains a NUL byte, is not valid UTF-8, cannot be read (for example a
permission error on a hop), loops, or resolves to a path outside `allowed_paths` or matching
`prohibited_paths` (for example `symlink to AGENTS.md: not in allowed_paths`).
A link that resolves to a directory of the same snapshot (the commit, the index
or the worktree) exposes everything beneath it, so it is also a violation when
any prohibited pattern can match some path beneath that directory, whether or
not such a path exists (for example `symlink to docs/private/: prohibited_paths:
docs/private/* can match beneath it` under `docs/*`). The check is conservative:
a pattern counts when a prefix of it matches the directory plus `/`.
A link to an allowed file passes; a scope pass does not prove the target exists.
Git records no path beyond a symlink, so a
file written through a linked directory appears at its real path and is judged
there.

### Evidence skeleton

`evidence init` writes a draft evidence file for the contract's schema version.
It fills only what the CLI observes locally: the canonical `contract_sha256`,
`git_head`, `git_tree`, the given `base_commit` and the observed
`worktree_clean`. Validation entries copy each contract `id` and `argv`;
criteria copy their IDs. Every result field is left unfilled (`null` or empty),
criteria and attestations are `pending`, and `implementer` is blank, so the
skeleton deliberately fails evidence validation. It never runs argv and never
writes `passed`.

The base is resolved like `scope-check --base` and recorded as a full SHA. It
must descend from `source.commit` and be an ancestor of HEAD. Gitlinks are
refused. The output is created exclusively and
must be outside the checkout's Git top level, because an untracked file there
would invalidate the evidence. A dirty worktree is recorded as observed
(`worktree_clean: false`), which `verify` rejects.

## Host authorization

Schema 0.2 mandates and final sign-off are issued by the human or host, never by the CLI; see
[host authorization](host-authorization.md). The CLI only prepares the request.

### Authorization request

`authorization-request task.json` makes the same GitHub reads as `verify
task.json` without host context, writes no file and reads no stdin. It first
validates the full task 0.2 schema: a schema 0.1 or unknown version is a usage
error (exit 2), and an invalid contract returns `error.code: invalid_contract`
with `schema_errors` and no template (exit 1), before any read; the payload is
identical with `--report-budget`, which takes no budget snapshot in that case.

The output has `issued: false`, `contract_sha256`, `mandate_fields`,
`human_only_fields`, `requested_actions`, `unresolved_fields`, `preflight_errors` and
`ready_for_issuance` (exit 0 only when true). In a ready request the `null`
leaves of `mandate_fields` are exactly `human_only_fields`: a ready request
still awaits the host for every one of them. `requested_actions` repeats the
contract's actions; the host chooses `mandate_fields.actions`. When identity or
permission reads fail, `credential_actor_id` and `authority` are also `null` and
listed in `unresolved_fields`, which names only these derived fields; only fresh
trusted reads resolve them. Text output shows the requested actions, any
unresolved derived fields and the human-only fields.
`preflight_errors` omit the blockers that exist only because no mandate exists
yet. They are untrusted diagnostics and may contain repository-authored paths.

The request deliberately contains no scope, path, objective, criteria or
validation summary. The host renders the complete contract from the file it
hashes, issues the record, and the worker relays it unchanged. The request is not
host context: piping it to `verify --host-context-stdin` fails schema validation.

## Reports and integration

### PR description

`pr-body` runs the same read-only `verify` and renders Markdown: the issue
reference (`Refs` by default, `Closes` only with `--closes`), objective, scope,
criteria with their evidence status, each validation `argv` as an exact JSON
code span with the recorded status, exit code, test and skip counts, review and
sign-off status, the count and full neutralized text of every verify blocker,
the open-PR scan provenance (completeness, pages, error count per scanned
repository) with every overlapping PR, and an AI-assistance disclosure with the
CLI version and contract hash. `--assistant` adds host-reported model text.

When supplied evidence does not pass `verify`, its statuses are labelled
`unverified claim`. Evidence that fails its schema is not quoted at all; its
errors appear among the gates. For schema 0.2, review and sign-off states come
from `verify`. `pr-body` takes no host context, so for 0.2 it shows only
`technical_evidence_valid` with source (including repository, owner and issue
identity), evidence and review blockers. It omits
the implementation, draft and completion gates, `next_action`, final sign-off and
authorization blockers, and says so, rather than misreporting authorized work as
unauthorized. The host's `verify --host-context-stdin` run decides those.

One extra bounded read of the tree at the contract's pinned `source.commit`
finds pull request templates (`pull_request_template.md` or a
`pull_request_template/` directory at the root, `.github/` or `docs/`,
case-insensitive). The body names each path and blob SHA, or says that none
exists, or that presence is unknown when the read fails or is truncated.
Template contents are not read and the CLI does not fill the template.

All quoted prose is neutralized: whitespace collapses to one line, HTML is
escaped, Markdown link/image/emphasis/code characters are backslash-escaped,
and zero-width space entities break `@` mentions, `#` references, `://` URLs
and closing keywords (close, fix, resolve and their forms). Data shown in code
spans (argv, template paths) is exact JSON. The output file is created
exclusively. Rendering never writes to GitHub and is not publication authority.

### PR feedback

`feedback` reads one PR, its reviews, review comments, issue comments and the
check runs for its current head, then rereads the PR. The PR must have the
requested number, the canonical repository as its base and a valid head SHA. A
head that moves during the read makes the result incomplete.

Per reviewer it reports `latest_state` and `decision`: the latest APPROVED,
CHANGES_REQUESTED or DISMISSED review (DISMISSED clears it; COMMENTED and
PENDING never change it). Reviews are grouped by numeric user ID; `author` is
the latest observation and `decision_author` the author of the decisive review.
`changes_requested_by_trusted_association` is true when the decisive review of
an outstanding change request has a non-bot author with association OWNER,
MEMBER or COLLABORATOR. That association is a GitHub heuristic, not a
verified maintainer role. Deleted accounts appear as `ghost`. Review comments
include path, line and `outdated` (no diff position, or made on another
commit). Failing (failure, timed out, cancelled, action required, startup
failure, stale) and pending check runs are listed only for the exact head;
`other_head_runs` counts runs for other heads. `--expected-head` (for example
the evidence `git_head` of the recognized draft) adds `head_moved`. Logs are not
read.

All text fields are `untrusted_*` data with terminal controls removed. Feedback
never widens scope or grants authority; a requested change outside the reviewed
contract needs contract re-review. Malformed reviews, comments or check runs
are errors, not silently cleaned records: IDs and diff positions must be
positive, author associations, review states, run statuses and conclusions must
be known values, a run's conclusion must be set exactly when it is completed,
and SHAs must be 40 hex characters. Null bodies, commit IDs and lines are
accepted where GitHub documents them as nullable. Check-run pagination requires unique run IDs, a stable
`total_count` and a matching final count. Any of these failures gives
`complete: false` (exit 1).

### CI observation (opt-in, report only)

`verify ... --evidence evidence.json --observe-ci` adds `ci_observation` after
the verify decision and exit code are fixed; it never changes any gate. For the
evidence `git_head` in the contract's target repository (the source when the
target is blank), it reads every check-run page and the paginated combined
commit status. It reports check runs for that exact head (name, app slug and
numeric app ID, status, conclusion, URL), the count of runs for other heads,
and the combined state with each status context.

Shapes are strict: positive IDs, documented statuses and conclusions (set
exactly when a run is completed), and a combined status for the requested SHA.
For both check runs and statuses, `total_count` must be a non-negative integer
that stays stable across pages and equals the number of unique items read. Any failure, or a missing or
invalid evidence head, gives `complete: false` with errors. Queued, pending,
approval-required or missing runs are never success. This is an observation of
what GitHub reports, not proof that the evidence checks equal the CI checks.

### Signature observation (opt-in, report only)

`verify ... --evidence evidence.json [--repo-dir checkout] --observe-signatures`
adds `signature_observation` after the verify decision and exit code are fixed.
It is added only for a schema-valid contract and never changes any gate,
`next_action` or the exit status. The repository is the contract's target, or
the source when the target is blank. It has three parts:

- `github_verification`: one `GET repos/{target}/git/commits/{git_head}`. It
  reports `verified`, `reason` and `verified_at` from GitHub's verification
  object. A reason outside GitHub's documented set is `unrecognized` and is not
  echoed; the signature, payload and message are never copied. `verified` must
  agree with a `valid` reason. `verified_means` states what it shows: GitHub
  matched the signature to a key registered to an account. That is not
  approval, authorship, review or proof that tests ran. A head not yet pushed to
  the target cannot be observed and is reported as a failed read.
- `required_signatures`: every page of `GET
  repos/{target}/rules/branches/{base}`, where `base` is the contract's
  `execution.base_ref` or else `source.default_branch`. `required` is true when
  an active ruleset rule of type `required_signatures` applies, and
  `ruleset_ids` lists those rulesets. `false` means only that no visible active
  ruleset requires signatures. Each rule type must be one of GitHub's documented
  lowercase rule types. A malformed type makes the part unknown. So does a
  well-formed but unrecognized type, unless an exact `required_signatures` rule
  is also present. `classic_branch_protection` is always
  `not_observed`, because reading it needs admin access, and ruleset bypass
  actors are not visible either.
- `local_commits` (only with `--repo-dir`; otherwise `not_requested`): the
  commits in evidence `base_commit..git_head`, oldest first, each with
  `signature_header: present` or `absent`, plus counts. This is header
  presence, not validity; anyone can write a forged header. First the checkout's
  effective Git configuration is checked, as for every checkout reader; config
  a read could run as a program or use to fetch (signature programs, filters,
  promisor remotes, protocol settings) makes the part incomplete before any other
  read. Then only `rev-parse --is-shallow-repository`, `merge-base`, `rev-list`
  and `cat-file` run, through the hardened Git reads, which never lazy-fetch. No signature
  program runs: no gpg, ssh-keygen, `verify-commit` or `--show-signature`, so
  repository-configured programs are never executed. The base must be a full SHA
  and an ancestor of the head. A shallow repository is reported as incomplete,
  because its boundary can silently cut the range even when the base is
  reachable through a merge. More than 1000 commits is also reported as
  incomplete; the list is never truncated.

Any failed, partial or malformed read makes that part, and the observation,
`complete: false` with fixed error strings. Contract-required verified heads and
signed evidence attestations (the rest of #18) are not implemented.

### Output schemas

Every command's JSON output has a packaged JSON Schema (draft 2020-12 subset).
`agent-contrib schema COMMAND` prints it; `error` is the error envelope that
replaces any command's result on a usage, input or protocol error, and
`evidence-init` is `evidence init`. `instructions` reports the
`output_schema_version` (currently `1`) and the package directory. Objects are
closed: a field is required unless marked optional, and fields not listed never
appear. Output values do not carry the schema version; a shape change bumps the
version together with the CLI's semantic version and changelog. Remote text in
fields named `untrusted_*` and in instruction files stays untrusted data.

The field-by-field reference for every command is in
[output-reference.md](output-reference.md). It is generated from the schemas, and a
test fails when it drifts.

## Global options and output

### Exit codes and output streams

Commands emit JSON by default except help/version. Exit codes: **0** for a complete read,
successful export/draft write or a passed verification gate (completion
readiness for schema 0.1, the selected `--stage` for 0.2); **1** for an
expected error, incomplete read or unresolved verification; **2** for usage
errors. An exit code is not authorization.

JSON results are flushed before returning. If the stdout pipe's consumer has
closed, the command closes the failed stream and exits **1** without a traceback
or a second error during interpreter shutdown. This also overrides an otherwise
successful result or usage-error status when its JSON cannot be delivered.
A missing stdout stream (for example, fd 1 closed before Python starts) also
returns **1** quietly. Caller-provided replacement streams need only support
`write()`; their `flush()` and cleanup `close()` methods are used when available.
Writable stdout, including a redirected output file, retains the normal JSON
format and command exit status. Help/version output is unchanged.

### Help

`agent-contrib --help` and `agent-contrib COMMAND --help` describe each command
and option of the installed version. Exit status is 0 when a command succeeds and
its gate passes, 1 when a gate is not passed, a read is incomplete or an error
occurs, and 2 for usage errors.

### API budget (opt-in)

`--report-budget` before a GitHub-reading command reads `GET rate_limit` (which
does not consume the budget) before and after the command and adds
`api_budget`: both snapshots (limit, remaining, used, reset) and
`used_during_command`. Because other processes may share the token, that
number is an upper bound. It is `null`, with `delta_unknown_reason`, when a
snapshot failed, the reset window or limit changed, or the used counter
decreased; a negative difference is never reported. A snapshot is rejected
(`null` values with an error, never zero) unless its counters are non-negative
integers with `used + remaining == limit`. Command arguments are validated
before the first snapshot: malformed repository references, unreadable input
files and schema-invalid `drift`/`pr-body`/`authorization-request` contracts
cause no GitHub read.
`verify` still reports schema and evidence failures in its normal result envelope;
optional budget reads do not turn those failures into success. `--min-remaining N` refuses to start (error `rate_limit_budget`, exit 1)
when the budget is unknown or below N, before any command read. The CLI does not
estimate a command's cost; choose N yourself. Offline commands reject the flag
(see "Global options on offline commands").
Without the flag, no rate-limit read happens and output is unchanged.

### Content cache (opt-in)

`--cache` before a command reuses file contents that GitHub returned for a
pinned commit, so repeated `discover`, `inspect`, `prepare`, `verify` and
`drift` runs skip re-reading the same instruction and policy files. The cache is
content-addressed and self-verifying, and it never changes output, gates or exit
status.

- Only `repos/{owner}/{repo}/contents/{path}?ref={40-hex commit}` reads are
  served from it, and only for a repository whose live metadata earlier in the
  same command said both `"private": false` and `"visibility": "public"`. Private, internal or unobserved
  repositories always read live.
- The expected Git blob SHA for the path comes from the **live** recursive tree
  read at that commit. Trees, metadata, issues, PRs, labels, permissions, branch
  heads, comparisons, checks and every other read are never cached.
- Entries are the decoded file bytes, named by blob SHA. A stored response must
  carry that SHA and hash to it. Every hit recomputes the Git blob hash
  (SHA-1 of `blob <length>\0<bytes>`) and must match the live tree; a
  mismatching, oversized, symlinked, foreign-owned or non-regular entry (such
  as a FIFO, opened nonblocking) is deleted and read live. Identical files at different paths share one entry.
- The directory is `$XDG_CACHE_HOME/agent-contrib` (an absolute
  `XDG_CACHE_HOME`), otherwise `~/.cache/agent-contrib`.
  - It is opened once by walking every component of the absolute path from `/`
    without following symlinks: a symlink anywhere in the path disables the
    cache. Ancestors must already exist; only the cache directory itself is
    created (0700), after every ancestor passed.
  - The configured path is read lexically. `os.path.abspath` collapses `..`
    before the walk, so `a/link/../c` means `a/c`, even where a shell following
    `link` would land elsewhere.
  - Every ancestor must be owned by root or by you, and not group- or
    other-writable. The only exception is a root-owned sticky directory, such
    as `/tmp`. Ancestors you own must carry no POSIX ACL.
  - The cache directory itself must be yours, mode exactly 0700, with no POSIX
    ACL.
  - Any doubt disables the cache for that run; it is never an error and, by
    design, prints no diagnostic, so output stays identical. If warm runs never
    get faster, check these rules for your `XDG_CACHE_HOME`. Platforms
    without `os.listxattr`, where ACLs cannot be ruled out, disable it too.
  - **Default Ubuntu homes disable the cache:** umask 002 makes `~/.cache`
    0775. To enable it, point `XDG_CACHE_HOME` at a private 0700 directory, for
    example `mkdir -m 700 ~/.agent-contrib-cache` and then
    `XDG_CACHE_HOME=~/.agent-contrib-cache agent-contrib --cache …`. Every
    ancestor of that directory must meet the rules above.
  - Every read, write, rename, scan and delete then works relative to that
    open directory, so renaming or replacing its name afterwards cannot
    redirect them.
  - Writes are atomic and private (0600), and eviction touches only valid
    entry names and the CLI's own temporary files. A temporary file older than
    one hour, left by a crashed store, is removed. Younger ones count toward the
    total but are never deleted, since they may belong to a concurrent store.
  - Without POSIX ownership checks or `dir_fd` support, the cache is bypassed.
- Entries are at most 8 MiB. After each store the total is brought under
  256 MiB by deleting the oldest entries. Entries another invocation removes
  meanwhile are skipped, so concurrent commands may exceed the total briefly,
  but once they finish the last eviction pass has seen every stored entry. Delete the directory to clear it; any cache error falls back
  to the live read.
- `--report-budget` counts only the live reads that remain. The cache is active
  for one invocation; library callers never inherit it.
- Offline commands reject `--cache`, as they reject `--report-budget`.

### Text output (unreleased)

Put the global option before the subcommand:

```sh
agent-contrib --format text discover owner/repo
agent-contrib --format text verify task.json
agent-contrib --format json inspect 'owner/repo#123'
```

Text changes presentation only, never scan depth, authorization or exit status.
It is a summary: discovery shows at most 20 issues per repository, each with its
overlapping-PR count, whether it is excluded and (with `--signals`) its score,
followed by overlapping and excluded counts over all issues; lists show at
most 50 entries and long remote lines are shortened. Omitted list entries are
counted. `inspect --ownership` and `ownership` list the ownership report's
possible prior fixes, downstream references, rejected approaches, open linked
PRs, claims (author association and age) and assignments, say whether the report
is complete and list its errors. Discovery adds one line each for `--responsiveness` and `--repo-dir` local
work when requested. Multi-repository discovery includes every repository's completeness and
errors. Verification shows the gates and blockers. With an explicit
`verify --stage X`, text starts with stage X, its exit gate and its blockers;
the other stages appear only as blocker counts, because they do not decide that
exit. When schema validation fails before any stage is evaluated, the stage
line reads `not evaluated; see Errors` and the schema errors follow. JSON still
contains every stage. `scope-check` lists each violating path
and rule, warnings and errors. `drift` lists the reasons that set `drifted`, then
informational changes (an advanced default branch, PRs no longer open) apart.
`authorization-request` shows whether the request is ready for issuance, that it
is unsigned and grants nothing, the contract hash, and each preflight error and
unresolved field. `instructions` prints a version line and then the
workflow Markdown unchanged, so it can be read without unwrapping JSON. Other
commands show top-level scalar fields; use JSON for full nested results, instructions and provenance.
Remote text is sanitized to a single line so it cannot add fake gate headings.
Default JSON bytes are unchanged. Parse-time usage errors still use structured
JSON when argument parsing has not produced a valid format selection.
A global option (`--format`, `--report-budget`, `--min-remaining`, `--cache`) placed after
the subcommand is still a usage error (exit 2); its message says to move the
option before the subcommand.

#### Global options on offline commands

`instructions`, `schema`, `skill`, `lint`, `scope-check` and `evidence init`
never read GitHub. On them `--report-budget` and `--cache` are both usage errors
(exit 2, "`--cache` applies only to commands that read GitHub", and likewise for
`--report-budget`), checked before any file is read; `--min-remaining` already
requires `--report-budget`. `--format` applies to every command.

The text option uses the same stdout handling as JSON. Closed output returns 1
quietly; writable output retains the command's normal exit status.
