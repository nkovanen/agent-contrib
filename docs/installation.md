# Installation and controlled updates

Install on the machine that runs your agent. A remote Paseo agent needs the CLI,
Git and `gh` on its host, not merely on the device displaying the conversation.
The package requires Python 3.10+ and has no Python runtime dependencies. Build
and installer tools have their own Python requirements. Linux is the tested
platform; Windows and macOS are untested. In the unreleased v0.3.0 route, `verify --host-context-stdin` waits on stdin with
`select()`, which Windows supports only for sockets, so it fails closed there.
Scope and containment decisions use the literal POSIX paths Git reports on
every OS. Backslashes, drive letters and case are never normalized, so a path
that would match only after normalization is out of scope.

## Pinned GitHub install

After installing [pipx](https://pipx.pypa.io/latest/how-to/install-pipx.html), Git
and [GitHub CLI](https://cli.github.com/):

```sh
pipx install 'git+https://github.com/nkovanen/agent-contrib.git@v0.2.0'
agent-contrib --version
agent-contrib instructions
```

Run `pipx ensurepath` and restart the terminal/agent if the command cannot be
found. Authenticate `gh` using its own supported mechanism, and check with
`gh auth status`. Do not paste credentials into a task contract or chat. No
LightCraft checkout, subscription to a particular model, or repository-specific
setup is needed for discovery.

For a standard virtual environment instead of pipx:

```sh
python3 -m venv "$HOME/.local/share/agent-contrib-0.2.0"
"$HOME/.local/share/agent-contrib-0.2.0/bin/python" -m pip install \
  'git+https://github.com/nkovanen/agent-contrib.git@v0.2.0'
export PATH="$HOME/.local/share/agent-contrib-0.2.0/bin:$PATH"
agent-contrib --version
```

Persist that PATH entry in the environment used to start your harness. An
immutable release commit may replace the tag in the Git URL when exact commit
pinning is required. Installation uses standard Python build tools, not a
custom shell installer. Nothing is published to PyPI in this release.

## Install the Skill

The installed package is the canonical source. Export creates a new file and
prints its SHA-256; it refuses to overwrite an existing file or symlink.

| Harness | Personal Skill file |
| --- | --- |
| Claude Code | `~/.claude/skills/agent-contribute/SKILL.md` |
| Codex | `~/.agents/skills/agent-contribute/SKILL.md` |
| Paseo | Use the underlying provider's path on the agent host |
| Other | Export to that harness's Skill directory or load the Markdown as reusable instructions |

For Claude Code:

```sh
mkdir -p "$HOME/.claude/skills/agent-contribute"
agent-contrib skill --output "$HOME/.claude/skills/agent-contribute/SKILL.md"
```

For Codex:

```sh
mkdir -p "$HOME/.agents/skills/agent-contribute"
agent-contrib skill --output "$HOME/.agents/skills/agent-contribute/SKILL.md"
```

These locations follow [Claude Code's Skill documentation](https://code.claude.com/docs/en/skills)
and [Codex's Skill documentation](https://learn.chatgpt.com/docs/build-skills).
Project-local Skill directories are also supported by those harnesses, but a
personal install avoids per-project setup. Restart the harness if it has cached
its Skill catalog. Say “Go help owner/repo.” Claude Code also supports explicit
`/agent-contribute`; Codex supports explicit `$agent-contribute` invocation.

On Windows, use PowerShell paths and `New-Item -ItemType Directory -Force` instead
of `mkdir -p`; for example:

```powershell
New-Item -ItemType Directory -Force "$HOME/.agents/skills/agent-contribute"
agent-contrib skill --output "$HOME/.agents/skills/agent-contribute/SKILL.md"
```

The same CLI commands apply, but Windows execution is not covered by the current
CI matrix. A virtual environment uses `Scripts/python.exe` and `Scripts` on PATH.

## Compatibility and updates

The published CLI **0.2.0** bundles task and evidence schemas **0.1**, workflow guidance and
the thin adapter together. `agent-contrib instructions` reports this support set.
The unreleased CLI **0.3.0** also bundles explicit task/evidence schema **0.2**
and host-context schema **0.1**; default contracts remain 0.1. Unknown versions fail closed. The Skill intentionally has no independent copy
of the protocol: it asks the installed CLI for instructions every time.

Updates are explicit. Read the target release notes, back up contracts/evidence
and the existing Skill, then deliberately reinstall a chosen Git tag. For
example, reinstalling this release with pipx is:

```sh
pipx install --force 'git+https://github.com/nkovanen/agent-contrib.git@v0.2.0'
agent-contrib --version
agent-contrib skill --output ./agent-contribute-SKILL.new.md
```

Inspect and compare the exported file before replacing the installed Skill using
your normal file tools. Do not bypass an export failure by blindly deleting an
existing customization. Rerun verification after changing relevant inputs. No
silent update checks, migrations or downloads happen while using the CLI.

To uninstall the CLI, use `pipx uninstall agent-contrib`; remove the Skill file
separately if desired. Existing task/evidence files are yours and are not removed.

## Testing the unreleased v0.3.0 candidate

The published v0.2.0 tag is unchanged. To test the new route, create a separate
virtual environment and install the exact reviewed candidate commit from GitHub.
Replace `REVIEWED_COMMIT` with the full immutable commit SHA supplied by its review:

```sh
python3 -m venv /tmp/agent-contrib-candidate
/tmp/agent-contrib-candidate/bin/python -m pip install 'git+https://github.com/nkovanen/agent-contrib.git@REVIEWED_COMMIT'
/tmp/agent-contrib-candidate/bin/agent-contrib --version
```

A local integration commit may not be pushed yet. In that case, install a clean
`git archive` export of that exact commit into the new environment instead; do not
substitute a different remote commit or a mutable working tree.

Export the Skill using that environment's command into the chosen fresh agent
workspace. Record the installed commit, CLI version and exported hash. Keep the
published installation separate; do not install a v0.3.0 tag that does not exist.
Use the [human/host handoff](host-authorization.md) at authorization boundaries.
