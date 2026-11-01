# Command reference

Commands emit JSON except help/version. Exit codes: **0** for a complete read,
successful export/draft write or completion-ready verification; **1** for an
expected error, incomplete read or unresolved verification; **2** for usage
errors. An exit code is not authorization.

| Command | Result |
| --- | --- |
| `agent-contrib discover owner/repo` | Repository resolution, policy/instruction context, ranked issues and overlap/completeness metadata |
| `agent-contrib inspect 'owner/repo#123'` | Detailed issue snapshot, source policy, instructions, exclusions and PR matches |
| `agent-contrib prepare 'owner/repo#123' --output task.json` | A new schema `0.1` draft; an existing output file is never overwritten |
| `agent-contrib verify task.json` | Schema, current source/approval/overlap and execution-readiness checks; no commands executed |
| `agent-contrib verify task.json --evidence evidence.json --repo-dir checkout` | Also validates supplied evidence against the local checkout and live source |
| `agent-contrib scope-check task.json --repo-dir checkout [--base SHA]` | Offline check of committed, staged, unstaged and untracked paths against the contract scope; exit 1 lists each violation. Never evidence |
| `agent-contrib evidence init task.json --repo-dir checkout --base SHA --output evidence.json` | A new evidence skeleton with observed Git facts and contract IDs; results stay unfilled and the file fails validation until completed |
| `agent-contrib pr-body task.json [--evidence e.json --repo-dir checkout] [--closes] [--assistant TEXT] --output body.md` | A new Markdown PR description built from the contract, evidence and a fresh read-only `verify` run |
| `agent-contrib instructions` | Installed workflow Markdown, CLI version, schema support and update behavior |
| `agent-contrib skill --output SKILL.md` | Canonical adapter export, CLI version and SHA-256 |
| `agent-contrib --version` | CLI/library semantic version |

`discover`, `inspect` and `prepare` wrap their results with
`requested_repository`, `issue_source_repository`, `proposed_target_repository`
and `resolution_provenance`. The proposed target is context, never authority.
A disabled-issue fork uses one immediate parent's enabled tracker; ordinary
repositories and enabled-issue forks keep their own tracker. Missing parent
metadata, a parent without Issues, malformed responses and API failures remain
unresolved, with errors and `complete: false`.

Use the `reference` emitted by discovery for subsequent commands. In a fork
request, `fork/repo#123` means “resolve issue 123 for this requested repository”;
its `issue_url` names the actual source. It is not a claim that the issue exists
on the fork. Both repositories' open PRs are scanned, including drafts; a bare
`#123` in a PR belongs to that PR's repository.

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

## Schema 0.2 lifecycle (CLI 0.3.0 candidate)

```sh
agent-contrib prepare 'owner/repo#123' --schema-version 0.2 --output task.json
agent-contrib verify task.json --stage implementation
```

Prepare remains schema 0.1 unless explicitly selected. Schema 0.2 is restricted
to same-repository candidates, a distinct named head branch and the source default
base branch. It refuses resolved fork targets. No authorization is generated.

After the actual human/host has issued a task-bound record, it can supply it on
stdin using `--host-context-stdin`. The input is strict UTF-8 JSON, at most 8 MiB,
with a five-second read timeout. Terminal prompting, implicit files/environment
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

`instructions.resources` lists both task/evidence versions and host-context
schema 0.1. Library callers may pass host context explicitly to `core.verify`;
that is the same host-asserted boundary as the CLI, not a privileged API.

## Offline scope check

`scope-check` evaluates the working diff against the contract's
`scope.allowed_paths` and `scope.prohibited_paths` with the same function that
`verify` uses for evidence. It reads only the local checkout: committed changes
from `--base` (default: `source.commit`) to HEAD, staged and unstaged changes,
and untracked files that are not ignored. Renames report both paths. The base
must be a full 40-character SHA that is an ancestor of HEAD; gitlinks fail
closed. It makes no GitHub calls, so it can run as a pre-commit hook. Exit 0
means "no scope violation found", not evidence, readiness or authorization.
Each violation names the path and either the first matching prohibited pattern
or `not in allowed_paths`.

## Evidence skeleton

`evidence init` writes a draft evidence file for the contract's schema version.
It fills only what the CLI observes locally: the canonical `contract_sha256`,
`git_head`, `git_tree`, the given `base_commit` and the observed
`worktree_clean`. Validation entries copy each contract `id` and `argv`;
criteria copy their IDs. Every result field is left unfilled (`null` or empty),
criteria and attestations are `pending`, and `implementer` is blank, so the
skeleton deliberately fails evidence validation. It never runs argv and never
writes `passed`.

The base must be a full SHA that descends from `source.commit` and is an
ancestor of HEAD. Gitlinks are refused. The output is created exclusively and
must be outside the checkout's Git top level, because an untracked file there
would invalidate the evidence. A dirty worktree is recorded as observed
(`worktree_clean: false`), which `verify` rejects.

## PR description

`pr-body` runs the same read-only `verify` and renders Markdown: the issue
reference (`Refs` by default, `Closes` only with `--closes`), objective, scope,
criteria with their evidence status, validation argv with recorded status, exit
code, test and skip counts, review and sign-off status, every verify blocker
verbatim, the open-PR overlap scan, and an AI-assistance disclosure with the CLI
version and contract hash. `--assistant` adds host-reported model text.

All quoted text is neutralized: whitespace collapses to one line, HTML is
escaped, Markdown link/image/emphasis/code characters are backslash-escaped,
and zero-width space entities break `@` mentions, `#` references, `://` URLs
and closing keywords (close, fix, resolve and their forms). Evidence that fails
its schema is not quoted; its errors appear among the gates. The output file is
created exclusively. Rendering never writes to GitHub and is not publication
authority. The CLI does not fill repository PR templates; merge the sections
into one when the repository has it.
