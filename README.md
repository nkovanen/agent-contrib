# Agent Contrib

**Let your coding agent help open-source projects.**

Agent Contrib gives your existing coding agent a common way to find GitHub work,
prepare a task contract, and check contribution evidence. Bring your own agent,
model and compute. Maintainers keep control of contribution policy and acceptance.

1. **Install once:** the CLI and a small Skill for your agent.
2. **Say:** “Go help owner/repo.”
3. Your agent discovers issues, policies and overlapping pull requests.
4. It evaluates candidates and prepares a scoped specification for review.
5. With appropriate authorization, it implements and validates through its usual tools.
6. A human reviews the result before upstream publication.

**v0.2.0 is an experimental protocol, not an autonomous PR bot.** A bare help
request produces discovery and a draft specification. It does not authorize
implementation or publication. The CLI never runs a model, executes a task's
commands, pushes code, opens a PR or merges.

## Install

You need Python 3.10+, Git, and [GitHub CLI (`gh`)](https://cli.github.com/).
Install [pipx](https://pipx.pypa.io/latest/how-to/install-pipx.html) using its
platform instructions, then run:

```sh
pipx install 'git+https://github.com/nkovanen/agent-contrib.git@v0.2.0'
agent-contrib --version
# 0.2.0
```

If `agent-contrib` is not on your PATH, run `pipx ensurepath` and restart your
terminal and agent. Use `gh auth login` if needed; `gh auth status` should show an
account suitable for the repositories you want to read. Agent Contrib uses
read-only GitHub API requests through that installation of `gh`. No AI API key
or LightCraft checkout is needed. This release is distributed on GitHub, not PyPI.

Install the Skill for your harness, on the machine where the agent runs:

**Claude Code**

```sh
mkdir -p "$HOME/.claude/skills/agent-contribute"
agent-contrib skill --output "$HOME/.claude/skills/agent-contribute/SKILL.md"
```

**Codex**

```sh
mkdir -p "$HOME/.agents/skills/agent-contribute"
agent-contrib skill --output "$HOME/.agents/skills/agent-contribute/SKILL.md"
```

Restart the harness if needed, then say **“Go help owner/repo.”** The Skill reads
`agent-contrib instructions` from the installed release. Export refuses to
overwrite an existing file; see [installation and deliberate updates](docs/installation.md)
for virtual environments, Windows, existing Skills and version compatibility.

**Paseo and other harnesses:** install the CLI on the agent host, then export the
same Skill to the underlying provider's Skill directory. If a harness has no
Skill support, give it the exported Markdown as reusable instructions. No
provider-specific protocol fork is necessary.

## Use the CLI directly

```sh
agent-contrib discover owner/repo
agent-contrib inspect 'owner/repo#123'
agent-contrib prepare 'owner/repo#123' --output task.json
agent-contrib verify task.json
agent-contrib verify task.json --evidence evidence.json --repo-dir ./checkout
agent-contrib instructions
```

Replace `owner/repo` and `123` with a real repository and an issue emitted by
`discover`. Output is JSON, except `--help` and `--version`. `prepare` creates a
new **draft**, never an approved executable plan. `verify` returns exit 1 while
required gates are unresolved, including a valid draft with no completion
evidence. Read the separate readiness fields, not only the exit code.

A fork with Issues disabled resolves read-only to its immediate parent's issue
tracker. For example, `discover nkovanen/lightcraft` reports:

```json
{
  "requested_repository": "nkovanen/lightcraft",
  "issue_source_repository": "storytold/lightcraft",
  "proposed_target_repository": "nkovanen/lightcraft"
}
```

The response also records metadata provenance. Parent discovery never grants
permission to contribute upstream or write to the fork. Ordinary repositories
and forks with their own Issues enabled use their own tracker. See the
[command reference](docs/cli.md) for completeness and failure behavior.

## Candidates, approval and authority

An ordinary open issue is a **candidate**, even if it says `help wanted` or
`good first issue`. A task is **maintainer-approved** only when the source
repository explicitly opts in through a default-branch policy and the issue
carries a designated label. Policy and labels are refreshed during verification.

**The v0 approval policy delegates to every account with issue-label permissions,
including triagers. It does not authenticate the label actor as a maintainer.**
Repositories that need narrower authority should not enable this policy yet.
See [maintainer integration](docs/maintainers.md).

Source approval, permission to implement locally, and permission to publish are
separate. A fork experiment may be authorized without upstream approval; it must
remain within that fork's mandate. Final-revision human sign-off is required for
completion readiness. A readiness result never supplies a publication mandate.

## How it fits together

```text
Your agent + thin Skill
          |
          v
Versioned CLI / Python library ----> gh API (GET only)
          |                          issues, PRs, policies, instructions
          v
Task contract -> your agent's tools -> evidence + independent review
                                            |
                                            v
                                      passive verification
```

The package contains the schemas, workflow and **one canonical Skill** at
[`agent_contribute/adapters/agent-contribute/SKILL.md`](agent_contribute/adapters/agent-contribute/SKILL.md).
The Skill delegates protocol decisions to the installed CLI; repository-specific
requirements are discovered dynamically. CLI 0.2.0 supports task/evidence schema
`0.1` exactly. Unknown schemas fail closed. Nothing updates itself.

## What works, and what remains limited

Implemented: paginated GitHub discovery; fork resolution; source/target identity
separation; open-PR overlap checks in both repositories; policy and agent-file
reads; draft preparation; strict schema validation; execution gates; and passive
checks of commit-bound validation, scope, artifacts, review and human sign-off.

Limitations:

- The agent makes the final feasibility ranking; CLI scores are coarse heuristics.
- Open-PR overlap detection is conservative. Topical false positives and your own
  existing draft can block verification; there is no override yet. Timeline
  claims, recently closed PRs and deeper code overlap need manual review.
- Evidence is self-attested. Consistent JSON does not prove tests ran or establish
  reviewer identity. Review actual changes and logs independently.
- API errors, capped scans, stale instructions and unresolved questions block
  readiness. Fork resolution is one hop; submodule evidence is unsupported.
- The release is tested on Linux. Cross-platform harness support does not imply
  every local build environment has been tested.

Actor-specific approval, authenticated evidence, reviewed overlap resolution and
additional forges are future work, with no committed release date. There is no
hosted backend, database, mandatory model provider or automatic upstream submission.

## Project

- [Contributor workflow and architecture](docs/architecture.md)
- [Contributing and standalone checks](CONTRIBUTING.md)
- [Security and trust boundaries](SECURITY.md)
- [LightCraft case study and extraction provenance](docs/lightcraft-case-study.md)
- [Changelog](CHANGELOG.md) · [Releases](https://github.com/nkovanen/agent-contrib/releases)

Licensed under [MIT](LICENSE-MIT) **OR** [Apache-2.0](LICENSE-APACHE), at your option.
See [NOTICE](NOTICE) for original attribution.
