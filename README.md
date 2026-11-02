# Agent Contrib

Let your coding agent help open-source projects.

Agent Contrib helps Claude Code, Codex and other coding agents find useful GitHub
work, understand the requirements and prepare a contribution. It reads issues,
existing pull requests and repository instructions, then gives the agent a task
specification it can work from.

Install the CLI and skill once. Then tell your agent:

> Go help owner/repo.

The agent evaluates candidates and brings back a scoped task. Once you authorize
the work, it implements through its own tools, runs the repository's checks and
prepares the result for review. You review before anything is published upstream.

**Versions.** The published release is **v0.2.0**. This branch is the
**v0.3.0 candidate (unreleased)**: no v0.3.0 tag exists yet.

## Install

Requires Python 3.10+, Git, [GitHub CLI](https://cli.github.com/) and
[pipx](https://pipx.pypa.io/latest/how-to/install-pipx.html).

Published release:

```sh
pipx install 'git+https://github.com/nkovanen/agent-contrib.git@v0.2.0'
agent-contrib --version
```

Pre-release v0.3.0 candidate, in its own environment. Replace
`PUSHED_FULL_COMMIT_SHA` with the full SHA of a reviewed commit that has been
pushed to GitHub (an unpushed commit cannot be fetched; see
[installation](docs/installation.md#testing-the-unreleased-v030-candidate)):

```sh
python3 -m venv "$HOME/.local/share/agent-contrib-candidate"
"$HOME/.local/share/agent-contrib-candidate/bin/python" -m pip install \
  'git+https://github.com/nkovanen/agent-contrib.git@PUSHED_FULL_COMMIT_SHA'
export PATH="$HOME/.local/share/agent-contrib-candidate/bin:$PATH"
agent-contrib --version   # must print 0.3.0
```

The Skill runs the unqualified `agent-contrib`, so the first one on PATH wins.
Put that PATH entry in the environment that launches your agent (shell profile
or harness configuration) and restart the agent; otherwise it keeps using
v0.2.0.

Authenticate with `gh auth login` if you haven't already. If the command isn't
found, run `pipx ensurepath` and restart your terminal and agent.

Add the skill to your agent:

```sh
# Claude Code
mkdir -p "$HOME/.claude/skills/agent-contribute"
agent-contrib skill --output "$HOME/.claude/skills/agent-contribute/SKILL.md"

# Codex
mkdir -p "$HOME/.agents/skills/agent-contribute"
agent-contrib skill --output "$HOME/.agents/skills/agent-contribute/SKILL.md"
```

For Paseo, run these commands on the agent host and use the directory for its
underlying provider. Other agents can load the same exported `SKILL.md` as
reusable instructions. Restart your agent if it doesn't pick up the new skill.

Now say **“Go help owner/repo.”** Discovery needs no setup in the target
repository. See [installation](docs/installation.md) for virtual environments,
Windows, the candidate install and updates. The tool never updates itself.

## What the agent does

1. Finds issues, reads contribution policies and checks open PRs for overlap.
   Records applicable repository requirements, their sources and when each is due.
2. Ranks feasible tasks and prepares a specification: scope, acceptance criteria,
   prohibited changes, tests and required evidence.
3. Checks repository approval and your permission to implement the chosen task.
4. Works in an isolated branch, follows precommit and final checks in order, and
   obtains independent review of both the code and repository compliance.
5. Records the results and prepares a PR for human review.

A request to help a repository gets you discovery and a draft specification.
Implementation and publication need their own authorization. The CLI only reads
GitHub; your agent implements and performs any authorized PR operation. Nothing
is merged automatically. The [installed workflow](agent_contribute/instructions.md#repository-requirements-required-for-every-contribution-route)
also requires a source-linked requirements ledger; a green test suite alone is
not readiness.

If a fork has Issues disabled, the CLI reads tasks from its parent and keeps the
fork as the proposed target. Finding work upstream does not grant permission to
submit it there.

## Approval and authorization

An ordinary issue is a **candidate**. Labels such as `help wanted` do not permit
agent-generated work. A task is **maintainer-approved** only through an explicit
`.agent-contrib.json` policy and a matching label; that v0 policy trusts everyone
who can apply labels, including triagers. See [maintainer setup](docs/maintainers.md).

Each contract uses one of two task schemas:

| Schema | Route | How it is authorized |
| --- | --- | --- |
| 0.1 (default) | Fork experiment, or upstream contribution of policy-approved work | The user's explicit instruction, recorded in the contract; `verify` reports completion readiness |
| 0.2 (`--schema-version 0.2`, v0.3.0 candidate) | One candidate issue in the same repository, owner or maintainer credential, PR to the default branch | A human/host-issued mandate bound to the contract hash; separate `implementation`, `draft` and `completion` gates |

For schema 0.2 the CLI checks live GitHub facts: the personal credential, its
exact admin or maintain role, and the repository and issue identities. It
cannot tell who approved. A human or trusted host issues the mandate (and later
the final sign-off) and keeps the record and hash outside the worker's control;
the worker only relays them, and `authorization-request` only prepares the
fields. No harness issues mandates natively yet, so a same-user process could
forge one: this is an audit trail, not cryptographic consent. An implement-only
mandate is the local-only profile. See [host authorization](docs/host-authorization.md).

## Commands

All commands only read GitHub (`gh api --method GET`) or the local checkout and
print JSON. The default flow:

```sh
agent-contrib discover owner/repo
agent-contrib inspect 'owner/repo#123'
agent-contrib prepare 'owner/repo#123' --output task.json        # draft; grants nothing
agent-contrib verify task.json --evidence evidence.json --repo-dir ./checkout
```

| Command | Purpose |
| --- | --- |
| `discover` | Rank issues of one repository, or 2–20 repositories |
| `inspect` | One issue: approval, instructions, exclusions, overlapping PRs |
| `prepare` | Write a draft contract (schema 0.1, or 0.2 when selected) |
| `verify` | Check a contract and evidence against live GitHub; never runs validation commands. Schema 0.2 adds `--stage` and `--host-context-stdin` |
| `authorization-request` | Schema 0.2: unsigned request with the mandate bindings pre-filled; grants nothing |
| `scope-check` | Offline check of local changes against the contract scope |
| `evidence init` | Unfilled evidence skeleton from observed Git facts |
| `drift` | What changed since the contract was prepared |
| `pr-body` | Markdown PR description from the contract, evidence and live gates; publishes nothing |
| `feedback` | Reviews, comments and exact-head checks on a published PR |
| `audit` | Maintainer view of what agents see in a repository |
| `ownership` | Claims, cross-referenced PRs and possible prior fixes for one issue |
| `instructions` | The installed workflow and supported schema versions |
| `skill` | Export the canonical Skill file |
| `schema` | Print the JSON Schema of a command's JSON output |

v0.2.0 has `discover`, `inspect`, `prepare`, `verify`, `instructions` and
`skill`; the other commands are new in the v0.3.0 candidate. Optional reports
never grant approval or authority and never change a readiness gate:
`discover --signals`, `discover --responsiveness`, `inspect --ownership`,
`inspect --ai-policy`, `verify --observe-ci` and `--report-budget`. `--signals`
re-ranks candidates by its score after exclusions, overlaps and low likelihood;
the others leave ordering unchanged.
Put `--format text` before the command for an abridged summary; JSON is
canonical. Exit status: 0 when the command's gate passes, 1 when it does not or
a read is incomplete, 2 for usage errors. An exit code is never authorization.

[Command reference](docs/cli.md) · [Product map](docs/product-map.md) ·
Task schemas [0.1](agent_contribute/task.schema.json) and
[0.2](agent_contribute/schemas/0.2/task.schema.json) ·
[Host-context schema](agent_contribute/schemas/host-context/0.1.schema.json)

## Current limits

- Schema 0.2 covers same-repository candidates targeting the default branch.
  Forks and policy-approved work use schema 0.1. A schema 0.2 evidence base must
  be a published default-branch commit.
- Mandates and sign-off are host-asserted; test and review evidence is
  self-reported. Hashes bind records but prove neither consent nor execution.
- The credential must be a personal account with admin or maintain access for
  schema 0.2; bots and delegated identities are unsupported.
- Exact-head recognition exempts only the contribution's own open draft. Draft
  updates, force-push adoption and reopening are unsupported, and the host must
  retain the original publication head.
- Discovery scans open PRs; publication preflight also scans exact-head
  history. Timeline claims and file-level conflicts still need review. Only a
  host-issued disposition (host-context 0.2) can clear a topical overlap, and
  only while the PR and base tip are unchanged; direct references never clear.
- CI covers Linux with Python 3.10–3.14. Windows host-context input is
  unsupported and macOS is untested. No PyPI release or update channel.

Missing permissions, stale identities and incomplete reads fail closed. See the
[product map](docs/product-map.md) for what is shipped and planned.

## How it's built

A Python CLI/library owns discovery, GitHub access, schemas and verification.
The small [skill](agent_contribute/adapters/agent-contribute/SKILL.md) loads the
workflow with `agent-contrib instructions` and holds no repository-specific
rules. Both ship in one package with no Python runtime dependencies, hosted
service or required model provider. CLI 0.3.0 supports task and evidence schemas
0.1 and 0.2 and host-context 0.1 and 0.2; unknown versions fail closed. Schema 0.1
formats are unchanged and its routes keep their meaning, apart from the
hardening and message changes in the
[compatibility notes](CHANGELOG.md#compatibility-notes). [Architecture](docs/architecture.md) has the details.

## Development

From the repository root, in a virtual environment:

```sh
python -m pip install build
python -m unittest discover -v
python tools/check_install.py
```

The package check builds a wheel and source archive, rebuilds from that archive,
and checks clean installations outside the checkout.
[Contributing](CONTRIBUTING.md) describes the checks and release process.
Report vulnerabilities through [GitHub's private reporting form](https://github.com/nkovanen/agent-contrib/security/advisories/new).

This project started in [LightCraft PR #1](https://github.com/nkovanen/lightcraft/pull/1).
The [case study](docs/lightcraft-case-study.md) covers the pilot and extraction.

## License

[MIT](LICENSE). Original attribution is retained in [NOTICE](NOTICE).
