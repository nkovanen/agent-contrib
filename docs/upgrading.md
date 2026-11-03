# Upgrading from 0.2 to 0.3

This page lists what changes for people and agents moving from the published
v0.2.0 to the v0.3.0 candidate, and what to do about each change. The
authoritative list is the CHANGELOG's
[compatibility notes](../CHANGELOG.md#compatibility-notes). v0.3.0 is unreleased:
there is no v0.3.0 tag yet.

Nothing is migrated automatically and the tool never updates itself. Existing
schema 0.1 contracts keep their format and route meaning. Most changes below are
fail-closed hardening, which can refuse a checkout or file that 0.2 accepted.
Message-only changes never change a decision.

## Before you start

1. Install the candidate in its own environment (see the
   [README](../README.md#install) and
   [installation](installation.md#testing-the-unreleased-v030-candidate)), and
   check that `agent-contrib --version` prints `0.3.0` in the environment your
   agent uses.
2. Export the Skill again: it changed since v0.2.0. The export refuses to
   overwrite, so write a new file, compare it with the old one, then replace it.
3. Re-run `agent-contrib instructions`. The workflow now has a Quick path and a
   mandatory repository policy review.

## Tipjar alias

A candidate containing the Tipjar identity change installs both `tipjar` and
`agent-contrib` for the same CLI. After installing that reviewed commit, check
`tipjar --version` alongside `agent-contrib --version`; both print `0.3.0`.
The published v0.2.0 has no alias. Existing scripts can keep `agent-contrib` or
`python -m agent_contribute`; the distribution, repository URLs, output
identifiers and canonical `agent-contribute` Skill keep their names. No file or
schema migration is needed for the alias. See [installation](installation.md#tipjar-command-compatibility).

## Versions and schemas

| Change | What to do |
| --- | --- |
| The CLI supports task and evidence schemas 0.1 and 0.2, and host-context 0.1 and 0.2. Unknown versions fail closed. | Nothing for 0.1 contracts. Use `prepare --schema-version 0.2` only for the new owner/maintainer route; never edit a 0.1 contract into 0.2. |
| `prepare` still defaults to schema 0.1. | Nothing. |
| Lifecycle options (`--stage`, `--host-context-stdin`) are refused for 0.1 contracts. | Use them only with a newly prepared schema 0.2 contract. |

## New contracts need a policy review

`prepare` now writes the prerequisite `ai-policy-review` with status `pending`
into every new contract (0.1 and 0.2), so `verify` blocks until it is resolved.
`discover`, `inspect` and `prepare` always add a `repository_policy` report.

What to do: read every source, hinted line and unassessed reference in that
report. Then set the prerequisite to `satisfied`, with evidence naming the
source commit, the report's `inventory_sha256` and your dispositions, or to
`blocked` if the project refuses the work. Before any authorization, run
`agent-contrib drift task.json --policy-sha256 HASH` to catch policy changes.
Contracts prepared before the upgrade keep their format, and the new
prerequisite is not added to them. Their verification can still change where the
hardening below now refuses or flags a checkout or input; see
[checkout and evidence refusals](#checkout-and-evidence-refusals) and
[JSON input and messages](#json-input-and-messages).

If you recorded hashes or hint IDs with an earlier 0.3.0 candidate build, review
the policy again. The inventory hash format changed (`drift` reports it as a
format change), and hint IDs changed from `H1`, `H2`, ... to stable `H-` plus a
SHA-256.

## Command-line usage

| Change | What to do |
| --- | --- |
| Global options (`--format`, `--report-budget`, `--min-remaining`, `--cache`) are accepted only before the subcommand. Elsewhere they are a usage error (exit 2) whose message says where to put them. | Write `agent-contrib --format text verify task.json`, not `verify task.json --format text`. |
| `--report-budget` and `--cache` are refused (exit 2) on the offline commands `instructions`, `schema`, `skill`, `lint`, `scope-check` and `evidence init`. `--min-remaining N` requires `--report-budget`. | Drop these options from offline commands. |
| `inspect --ai-policy` is deprecated: it is accepted and ignored, and writes one notice line to stderr. | Remove the flag; the policy report is always added. |
| `--base` (only `scope-check` and `evidence init`) accepts exactly a full 40-character SHA, `HEAD`, or a full ref such as `refs/heads/NAME` or `refs/tags/NAME`, optionally followed by `~N` or `^N`. Short SHAs and bare branch names fail with `invalid_base`. | Expand a short SHA with `git rev-parse ABBREV`. Evidence `base_commit` stays a full SHA, so 0.1 `verify` is unaffected. |
| An opted-in report that is incomplete (`--responsiveness`, `inspect --ownership`, `--check-top`, `--repo-dir`) makes the command exit 1. | Treat exit 1 as "not complete" and re-run or read the report's errors. |
| A closed or missing stdout exits 1 quietly. | Nothing. |

## Checkout and evidence refusals

These apply to `verify --repo-dir` (schema 0.1 too), `scope-check` and
`evidence init`.

| Error or effect | Cause | What to do |
| --- | --- | --- |
| `not_worktree_root` (an evidence error in `verify`) | `--repo-dir` names a subdirectory or a Git directory. | Pass the worktree top level (`git rev-parse --show-toplevel`). |
| `unborn_head` | HEAD is unborn, deleted or not a commit. | Commit, or check out the evidence branch. |
| `index_flags` | Index entries are marked assume-unchanged or skip-worktree, including a sparse checkout. | `git update-index --no-assume-unchanged --no-skip-worktree PATH`, or disable the sparse checkout, then re-run. |
| `unsafe_git_config` | The effective config (including `include`/`includeIf` files) sets `filter.*`, a `gpg` program, `diff.external`, `diff.*.command` or `textconv`, partial-clone or promisor settings, or `protocol.*`; or `core.ignoreCase=true` on a case-sensitive filesystem. | Find it with `git config --show-origin --show-scope --list`; it may come from the repository, an included file or your global config. Remove it there. |
| `unsafe_git_attributes` | `.git/info/attributes` is not empty. | Empty or remove it. |
| Evidence is dirty | A file is hidden only by `.git/info/exclude` or `core.excludesFile`, or a file's bytes match neither its blob nor what checkout writes (for example an edit hidden by `ident`, or a CRLF copy from a local `core.autocrlf`). | Commit, delete or move the file, or add it to a committed `.gitignore`; re-checkout affected files with `core.autocrlf=false`. |
| `verify` rejects the evidence | The change adds a symlink that resolves outside the contract scope, or to a directory a prohibited pattern can match beneath. | Remove the symlink, or keep its target inside the allowed scope. |
| `shallow_checkout` | A shallow clone lacks the base or its history. | `git fetch --unshallow`, or fetch the base commit. |
| `checkout_too_large_for_timeout` | Hashing every tracked file exceeded the scaled timeout. | Use a smaller checkout; the timeout already scales with tracked size. |
| `unsafe_temp_dir`, `temp_dir_error` | No usable temporary directory outside the checkout and its Git directories. | Point `TMPDIR` at a writable directory outside the checkout. |
| The evidence base is unauthenticated | GitHub's comparison of the base was partial or contradictory. | Re-run; make sure the base is a published commit on the default branch. |

Every tracked file is now hashed against a fresh temporary index, so `verify`
can take longer on large checkouts.

## JSON input and messages

| Change | What to do |
| --- | --- |
| Lone surrogate strings and overflowing numbers fail as `invalid_json` (previously `input_error`, or parsed to infinity). | Fix the file; check scripts that matched the old error code. |
| Malformed or missing PR `body`, `head` or `head.ref` fields make discovery and verification scans incomplete instead of empty. | Re-run later; treat the result as incomplete. |
| Prerequisite blockers, heuristic overlap reasons, a blank pending target ("Execution target not yet chosen") and misplaced-option usage errors have new wording. | Never parse message text; use error codes, gates and fields. Output JSON Schemas ship with the CLI (`agent-contrib schema COMMAND`). |

## New and optional

The schema 0.2 owner/maintainer route, `authorization-request`, the helper
commands, report-only options and `--format text` are new. None of them changes a
0.1 decision. Start with [getting started](getting-started.md) and the
[command reference](cli.md).


The Tipjar integration uses output schema 2, preserving packaged output/1.
Policy inventory format 3 includes pinned jar declarations; an old inventory
hash remains historical and requires a fresh policy review. Existing task and
evidence contracts retain their formats. Current live checks can block an old
contract if the source is now closed/unknown or its declaration changed since
preparation. A missing jar alone does not change either existing route.
