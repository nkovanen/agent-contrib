# Agent Contrib

Let your coding agent help open-source projects.

Agent Contrib helps Claude Code, Codex and other coding agents find useful GitHub
work, understand the requirements and prepare a contribution. It reads issues,
existing pull requests and repository instructions, then gives the agent a task
specification it can work from.

Install the CLI and skill once. Then tell your agent:

> Go help pallets/click.

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

Approval to work on an issue, your permission to execute locally and permission
to publish a PR are checked separately.

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
checks the contract and supplied evidence without running their commands. It
returns exit code 1 when requirements are still unmet, including for a valid
draft that has no implementation evidence yet.

[Command reference](docs/cli.md) · [Task schema](agent_contribute/task.schema.json) ·
[Evidence schema](agent_contribute/evidence.schema.json)

## How it's built

The Python CLI/library owns discovery, GitHub access, schemas and verification.
The small [skill](agent_contribute/adapters/agent-contribute/SKILL.md) loads the
workflow with `agent-contrib instructions`; it contains no repository-specific
rules. Both ship in the same package. CLI 0.2.0 supports task and evidence schema
0.1 and rejects unknown versions.

There are no Python runtime dependencies, hosted services or required model
providers. GitHub access goes through your local `gh` authentication.
[Architecture and workflow](docs/architecture.md) has the details.

## Current limits

v0.2.0 is an early release. Discovery, fork resolution, specification preparation
and evidence verification are implemented. The agent makes the final task
selection; CLI rankings are only heuristics.

- Overlap checks scan open PRs. They can flag unrelated work, and even your own
  existing draft can block verification. Closed PRs and ownership claims in
  comments still need manual review.
- Evidence is self-reported. The verifier checks consistency with the commit,
  contract and scope; it cannot prove that tests ran or authenticate a reviewer.
- Incomplete API reads block readiness. Fork resolution follows one parent;
  submodule evidence is unsupported.
- CI covers Linux with Python 3.10–3.14. Windows is not tested.

Narrower approval permissions, authenticated evidence and a way to resolve
reviewed overlaps remain future work. Releases are on GitHub; there is no PyPI
package in this iteration.

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
