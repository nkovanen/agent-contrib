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
