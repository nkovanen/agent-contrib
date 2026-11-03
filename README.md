# Tipjar

Gift useful agent work to open-source projects, with human authorization at each step.

Tipjar is the new identity for Agent Contrib. A tip is agent work contributed to
a project. It is a read-only command-line tool plus a thin agent Skill for Claude
Code, Codex and other coding agents. It finds suitable GitHub issues, reads each
project's rules and open pull requests, and turns the chosen issue into a reviewed
task contract. Your agent implements and publishes only after a human authorizes
each step; the CLI itself never writes to GitHub.

`tipjar find` verifies one batch of at most ten indexed public jar candidates.
It is not an exhaustive directory. No adoption is established and there is no
curated fallback list. Direct `tipjar jar owner/repo` reads without indexing.
The candidate can inspect a repository's root invitation with
`tipjar jar owner/repo`. Discovery, preparation and live verification read the actual issue source’s
pinned declaration. Closed or unknown jars block contribution readiness; use
`tipjar discover acme/one acme/two --welcomed-only` to select declared welcomes
among named repositories. All other policy and authority gates still apply.
You can explicitly target a repository without a jar through existing discovery
and pending preparation. An absent jar is undeclared and grants no approval.
Explicit repository bans remain binding. Source approval, local execution
permission and publication authority remain separate.

**Versions.** v0.2.0 is the published release. This branch is the **v0.3.0
candidate (unreleased)**: no v0.3.0 tag exists yet. Coming from 0.2? Read
[upgrading](docs/upgrading.md).

## Install

Requires Python 3.10+, Git, [GitHub CLI](https://cli.github.com/) (`gh auth login`)
and [pipx](https://pipx.pypa.io/latest/how-to/install-pipx.html). Published release:

```sh
pipx install 'git+https://github.com/nkovanen/agent-contrib.git@v0.2.0'
agent-contrib --version
```

The v0.3.0 candidate, in its own environment. Replace `PUSHED_FULL_COMMIT_SHA`
with the full SHA of a reviewed commit that is on GitHub (see
[installation](docs/installation.md#testing-the-unreleased-v030-candidate)):

```sh
python3 -m venv "$HOME/.local/share/agent-contrib-candidate"
"$HOME/.local/share/agent-contrib-candidate/bin/python" -m pip install \
  'git+https://github.com/nkovanen/agent-contrib.git@PUSHED_FULL_COMMIT_SHA'
export PATH="$HOME/.local/share/agent-contrib-candidate/bin:$PATH"
agent-contrib --version   # must print 0.3.0
tipjar --version          # same CLI, in a candidate containing the alias
```

In this candidate, `tipjar` and `agent-contrib` call the same CLI; for example,
`tipjar discover owner/repo --signals`. The published v0.2.0 has no `tipjar`
command. The distribution remains `agent-contrib`, the Python module remains
`agent_contribute`, and the single canonical Skill remains `agent-contribute`.
Help, output identifiers and repository URLs retain their existing names.

Current `main` contains the unreleased v0.3.0 candidate, including the
`tipjar` alias. Installing `@main` selects that moving candidate; pin a reviewed
full commit SHA for a reproducible install. The Skill runs the first
`agent-contrib` on PATH, so set PATH where your agent starts and restart the agent.

Add the Skill (for Codex, use `$HOME/.agents/skills/agent-contribute` instead):

```sh
mkdir -p "$HOME/.claude/skills/agent-contribute"   # Claude Code
agent-contrib skill --output "$HOME/.claude/skills/agent-contribute/SKILL.md"
```

Other agents can load the same `SKILL.md`. [Installation](docs/installation.md)
covers Paseo, Windows and updates (the tool never updates itself);
[getting started](docs/getting-started.md) walks through a complete run.

## "Go help owner/repo"

Say it to your agent. Its installed workflow runs six steps and stops wherever a
human must decide:

1. **Discover.** `agent-contrib discover owner/repo --signals` ranks open issues;
   `--signals` re-ranks heuristically and never approves. Then the agent reads
   every source in the `repository_policy` report. **Stop** if a relevant rule
   refuses agent work or cannot be resolved.
2. **Inspect.** `agent-contrib inspect 'owner/repo#N' --ownership` shows claims,
   linked PRs and possible prior fixes. **Stop** on an overlapping PR, claim or
   prior fix, or an incomplete read.
3. **Prepare.** `agent-contrib prepare 'owner/repo#N' --output task.json` writes a
   draft contract (scope, criteria, validations, requirements ledger), and
   `agent-contrib lint task.json` checks it offline.
4. **Verify and ask.** `agent-contrib verify task.json` reports the contract hash
   and blockers; `authorization-request` and `drift` prepare the request. A bare
   "help" request ends here. **Stop** until you authorize the work: for schema 0.2
   a human/host-issued mandate, never one the agent writes.
5. **Implement, then publish a draft.** On an isolated branch, with scope checks,
   the repository's checks and independent review. **Stop** before publishing:
   a draft PR needs its own authorization and a passing draft gate.
6. **Complete.** For schema 0.2, **stop** until a human/host final sign-off covers
   the exact final head. Nothing marks the PR ready, merges or releases it.

To bound the displayed list, use `agent-contrib discover owner/repo --limit 10`
(1–1000). All existing scans and ranking still run. Limited JSON and text report
total observed candidates, shown/omitted counts and full overlap/exclusion counts;
display truncation never means a complete scan. With several repositories,
`--limit` is one global budget. Omitting it preserves the existing output.

## Find invitations

```sh
tipjar find
tipjar find --owner acme
tipjar --format text find --owner acme
tipjar jar acme/project
```

Only `welcome` observations are selectable, subject to policy review. Search
indexing can lag or omit repositories, especially forks, and repeated calls can
return the same batch. An empty result says “No verified welcoming repositories
in this batch”; it does not establish that none exist. Continue with `discover`,
`inspect` and `prepare` for assessment. A jar alone does not supply the missing
arbitrary outside-contributor upstream authorization route. Find proposes,
executes and publishes nothing. See [find limits](docs/cli.md#find).

## Approval and authorization

An ordinary issue is a **candidate**. Labels such as `help wanted` do not permit
agent-generated work. A task is **policy-approved** only through an explicit
`.agent-contrib.json` policy and a configured label currently on the issue; the
CLI does not verify who applied it. Public issue events name an event actor, but
an outside contributor cannot use them to verify that actor's maintainer
authority. See [maintainer setup](docs/maintainers.md).

Schema 0.1 (the default) covers fork experiments and policy-approved work,
authorized by your explicit instruction. Schema 0.2 covers one candidate issue in
a repository you own or maintain: a host-issued mandate bound to the contract
hash, then separate `implementation`, `draft` and `completion` gates. Mandates are
an audit trail, not cryptographic consent ([host authorization](docs/host-authorization.md)).

## Safety model

- **Read-only GitHub.** The CLI runs only `gh api --method GET`. Locally it writes
  only files you name (never overwriting one) and, with `--cache`, its cache.
- **Untrusted text.** Issue text, repository instructions, contracts and evidence
  are data. The CLI never executes a contract's validation commands.
- **Fail closed.** Missing permissions, stale identities, unknown schema versions,
  unsafe checkout settings and incomplete reads block. An exit code is never
  authorization.
- **Separate decisions.** Source approval, permission to implement and permission
  to publish are separate records; one never implies another.
- **Nothing auto-published.** Publication is a draft PR, only after its own
  authorization. Nothing is merged, marked ready or released automatically.

## What's new in 0.3

- The schema 0.2 owner/maintainer route: staged gates, `authorization-request`,
  overlap dispositions and draft-update rounds ([host authorization](docs/host-authorization.md)).
- A default-on repository policy report, a mandatory review and `drift --policy-sha256`.
- New helper commands, report-only ranking aids, `--format text`, output JSON
  Schemas, `--report-budget` and an opt-in verified `--cache` ([reference](docs/cli.md)).
- Opt-in required CI checks and a report-only maintainer Action ([maintainers](docs/maintainers.md)).
- Hardened Git reads and stricter evidence checks ([security](SECURITY.md)). Every
  0.1 behaviour change: [compatibility notes](CHANGELOG.md#compatibility-notes),
  [upgrading](docs/upgrading.md).

## Commands

| Command | Purpose |
| --- | --- |
| `init`, `jar-check` | Create an explicit-state local invitation template; validate a local manifest offline |
| `dependencies` | Offline GitHub give-back candidates from local dependency declarations ([workflow](docs/dependencies.md)) |
| `session` | [Plan an offline gift-work shortlist](docs/planning-sessions.md) with explicit stopping caps |
| `jar` | Inspect one pinned root invitation; inspection only, no authority |
| `find` | Verify one public invitation batch (`--owner OWNER` optional) |
| `discover` | Rank issues of one repository, or 2–20 repositories |
| `inspect` | One issue: approval, instructions, exclusions, overlapping PRs |
| `prepare` | Write a draft contract (schema 0.1, or 0.2 when selected) |
| `lint` | Offline check of a contract against its schema and review rules |
| `verify` | Check a contract and evidence against live GitHub (0.2: `--stage`) |
| `authorization-request` | Schema 0.2: unsigned mandate request; grants nothing |
| `drift` | What changed since the contract was prepared |
| `scope-check`, `evidence init` | Offline scope check; evidence skeleton from observed Git facts |
| `pr-body`, `feedback` | PR description (publishes nothing); reviews and checks on a published PR |
| `receipt`, `impact`, `card` | Save public PR observations, summarize recorded impact and create offline SVG gift cards ([receipts](docs/receipts.md)) |
| `audit`, `ownership` | Maintainer view of a repository; claims and possible prior fixes |
| `instructions`, `skill`, `schema` | Installed workflow, Skill export, output JSON Schemas |

Output is JSON; put `--format text` before the command for a summary. Exit status
is 0 when the command's gate passes, 1 when it does not or a read is incomplete,
and 2 for usage errors. Details: [command reference](docs/cli.md).

## Current limits

- Schema 0.2 covers same-repository work on the default branch, with a published
  evidence base. Evidence is self-reported; hashes prove neither consent nor execution.
- A draft update is recognized only after one host-authorized fast-forward push;
  pre-push readiness, force-push adoption and reopening are unsupported.
- Full regression coverage is Linux with Python 3.10–3.14. Windows/macOS CI
  covers bounded host-context stdin and installed offline CLI smoke checks;
  it does not validate the full Git, cache or evidence workflows there.
  There is no PyPI release.

[Product map](docs/product-map.md) (shipped and planned) ·
[architecture](docs/architecture.md) (how it is built).

## Local directory demo

Browse the fictional Tipjar directory, import a local find snapshot, or draft a
repository invitation without any GitHub requests:

```sh
python3 -m http.server 8765 --bind 127.0.0.1 --directory web
```

Open http://localhost:8765. See [web/README.md](web/README.md) for the snapshot
contract, safe local behavior and optional static hosting instructions. The web
assets ship in the source distribution; the Python library stays independent.

## Development

```sh
python -m pip install build
python -m unittest discover -v
python tools/check_install.py
```

See [contributing](CONTRIBUTING.md); report vulnerabilities through
[GitHub's private reporting form](https://github.com/nkovanen/agent-contrib/security/advisories/new).
Origin: [LightCraft PR #1](https://github.com/nkovanen/lightcraft/pull/1) ([case study](docs/lightcraft-case-study.md)).

## License

[MIT](LICENSE). Original attribution is retained in [NOTICE](NOTICE).
