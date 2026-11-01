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

## Install

Requires Python 3.10+, Git, [GitHub CLI](https://cli.github.com/) and
[pipx](https://pipx.pypa.io/latest/how-to/install-pipx.html).

```sh
pipx install 'git+https://github.com/nkovanen/agent-contrib.git@v0.2.0'
agent-contrib --version
```

The published tag above remains v0.2.0. This branch develops v0.3.0; its new
authorization route requires an explicitly installed, reviewed candidate commit.
There is no v0.3.0 release yet.

Authenticate with `gh auth login` if you haven't already. If the command isn't
found, run `pipx ensurepath` and restart your terminal and agent.

Add the skill to your agent:

### Claude Code

```sh
mkdir -p "$HOME/.claude/skills/agent-contribute"
agent-contrib skill --output "$HOME/.claude/skills/agent-contribute/SKILL.md"
```

### Codex

```sh
mkdir -p "$HOME/.agents/skills/agent-contribute"
agent-contrib skill --output "$HOME/.agents/skills/agent-contribute/SKILL.md"
```

For Paseo, run these commands on the agent host and use the directory for its
underlying provider. Other agents can load the same exported `SKILL.md` as reusable
instructions. Restart your agent if it doesn't pick up the new skill.

Now say **“Go help owner/repo.”** Discovery needs no setup in the target
repository. You use your existing agent and model subscription.

See [installation](docs/installation.md) for virtual environments, Windows and
updates. Skill export refuses to overwrite an existing file. Updates are
explicit and versioned; the tool never updates itself.

## What the agent does

1. Finds issues, reads contribution policies and checks open PRs for overlap.
2. Ranks feasible tasks and prepares a specification: scope, acceptance criteria,
   prohibited changes, tests and required evidence.
3. Checks repository approval and your permission to implement the chosen task.
4. Works in an isolated branch, runs checks and obtains an independent review.
5. Records the results and prepares a PR for human review.

A request to help a repository gets you discovery and a draft specification.
Implementation and publication need their own authorization. Agent Contrib's
CLI only reads GitHub; your agent handles implementation and any authorized PR
operation. Nothing is merged automatically.

If a fork has Issues disabled, the CLI reads tasks from its parent and keeps the
fork as the proposed contribution target. It reports the requested repository,
issue source and proposed target separately. Finding work upstream does not
grant permission to submit it there.

## Repository approval

An ordinary issue is a **candidate**. Labels such as `help wanted` and
`good first issue` do not imply permission to submit agent-generated work.

**Maintainer-approved** tasks require an explicit repository policy and a
matching approval label. In v0, that policy delegates approval to everyone who
can apply issue labels, including triagers. It does not verify that the person
applying a label is a maintainer. Projects that need tighter control should keep
tasks as candidates for now. See [maintainer setup](docs/maintainers.md).

On the v0.3.0 candidate, schema 0.2 adds a separate route for a repository owner
or maintainer authorizing one candidate task in that same repository. It checks
live GitHub identity and admin/maintain permissions, plus a separately supplied
human/host mandate bound to the reviewed contract. The task stays a candidate.

The CLI cannot prove who typed a chat message. The host must retain the actual
human approval and issued hash; the worker cannot issue its own mandate. Current
harnesses need an explicit human/host handoff. See [host authorization](docs/host-authorization.md).

Local implementation, draft publication and final human sign-off remain separate.
A tested, independently reviewed draft can be ready while final sign-off is pending.

## CLI

```sh
agent-contrib discover owner/repo
agent-contrib inspect 'owner/repo#123'
agent-contrib prepare 'owner/repo#123' --output task.json
agent-contrib verify task.json
agent-contrib verify task.json --evidence evidence.json --repo-dir ./checkout
```

Use a repository and issue from discovery in place of the examples. Commands
return JSON. `prepare` writes a draft; it does not approve the task. `verify`
checks the contract and supplied evidence without running their commands. The
default remains schema 0.1 and completion-based verification. For an explicitly
authorized same-repository candidate using the v0.3.0 CLI:

```sh
agent-contrib prepare 'owner/repo#123' --schema-version 0.2 --output task.json
agent-contrib verify task.json --stage implementation
```

The prepared task is still a draft. Review its scope, then stop for the actual
human's task-specific authorization. A task file or an admin credential is not
that authorization. The [installed workflow](agent_contribute/instructions.md)
describes the human/host input, evidence and draft-stage checks.

[Command reference](docs/cli.md) · [Task schema](agent_contribute/task.schema.json) ·
[Evidence schema](agent_contribute/evidence.schema.json)

## How it's built

The Python CLI/library owns discovery, GitHub access, schemas and verification.
The small [skill](agent_contribute/adapters/agent-contribute/SKILL.md) loads the
workflow with `agent-contrib instructions`; it contains no repository-specific
rules. Both ship in the same package. CLI 0.3.0 supports task and evidence schemas
0.1 and 0.2, with an explicit host-context format. Unknown and mixed versions are
rejected; old 0.1 contracts retain their decisions.

There are no Python runtime dependencies, hosted services or required model
providers. GitHub access goes through your local `gh` authentication.
[Architecture and workflow](docs/architecture.md) has the details.

## Tools in the unreleased branch

These commands are implemented on this development branch; installing v0.2.0
above does not include them. See [development status](docs/development-status.md)
for unfinished parts and [the command reference](docs/cli.md) for exact outputs.

| Task | Command |
| --- | --- |
| Compare candidates across repositories | `discover owner/a owner/b --signals` |
| Inspect claims and possible prior fixes | `inspect 'owner/repo#123' --ownership` |
| Locate AI-contribution statements | `inspect 'owner/repo#123' --ai-policy` |
| Check repository setup | `audit owner/repo` |
| Check local changes against a contract | `scope-check task.json --repo-dir checkout` |
| Start an unfilled evidence record | `evidence init task.json --repo-dir checkout --base FULL_SHA --output evidence.json` |
| Review changes since preparation | `drift task.json` |
| Observe CI without changing readiness | `verify task.json --evidence evidence.json --observe-ci` |
| Prepare a description for human review | `pr-body task.json --output body.md` |
| Read reviews and checks on an existing PR | `feedback 'owner/repo#123'` |

JSON remains the default. Put `--format text` before the command for a short
summary, or `--report-budget` to observe the API budget. Optional signals and CI
observations do not grant authority or replace the existing verification gates.
Evidence initialization runs no tests and deliberately creates an incomplete
record. Rendering a PR description never publishes it.

## Current limits

v0.3.0 is under development. Discovery, fork resolution, task preparation and
passive verification are implemented. The agent chooses the task; CLI rankings
are heuristics.

- Schema 0.2 covers same-repository candidates targeting the default branch.
  Existing fork and policy-approved routes retain schema 0.1 behavior.
- Exact-head recognition exempts only the verified contribution's own open draft
  in the new post-publication stage. Other overlaps still block. Draft updates,
  force-push adoption and reopening are not supported by this route. It cannot
  detect past updates if all worker records are regenerated; the host must retain
  and audit the original publication head.
- Human mandates and sign-off are host-asserted; test and reviewer evidence is
  self-reported. Hashes bind records but do not prove consent or test execution.
- Missing permissions, stale identities/commits and incomplete reads fail closed.
  The credential must be a personal account with admin or maintain access for
  the new route; bot and delegated identities are unsupported.
- Core discovery scans open PRs. Publication preflight additionally scans exact
  head/base open and closed history. Timeline claims, reopened history and
  conflicts outside those checks still need review. Optional ownership reports
  expose some timeline signals but do not change readiness.
- The CI configuration covers Linux with Python 3.10–3.14. New local commits
  still need their own green hosted run before publication. Windows host-context
  input is unsupported; macOS is untested. There is no PyPI
  publication or silent update channel.

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
No LightCraft checkout or Rust build is needed.

## License

[MIT](LICENSE). Original attribution is retained in [NOTICE](NOTICE).
