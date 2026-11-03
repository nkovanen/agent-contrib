# Contributing

Agent Contrib is an experimental, agent-independent contribution protocol.
Discuss substantial behavior or schema changes before implementation. Small
fixes should include a focused regression and a clear description of the
observed problem. Disclose agent assistance and describe what you actually
verified; generated prose is not evidence.

Read [AGENTS.md](AGENTS.md), [SECURITY.md](SECURITY.md) and the
[architecture overview](docs/architecture.md). Keep source approval, execution
authorization and publication authority separate. Do not add a task executor,
GitHub write path, provider requirement or repository-specific Skill logic.

## Local development

Use Python 3.10+ and Git. From the repository root:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install build
python -m unittest discover -v
python tools/check_install.py
```

The independent manifest-schema parity regression uses Node.js and Ajv's
draft-2020-12 engine. Python-only local runs may skip it. The dedicated Linux
`schema-parity` CI job requires Node/npm and installs Ajv 8.20.0 from
`tests/schema-parity/package-lock.json` into a temporary directory; a missing
dependency fails that job. These are development-only tools, with no Python
runtime dependency. To run the same required check locally (Node/npm needed):

```sh
parity_dir=$(mktemp -d)
cp tests/schema-parity/package*.json "$parity_dir/"
npm ci --prefix "$parity_dir" --include=dev --ignore-scripts --no-audit --no-fund
TIPJAR_PARITY_AJV="$parity_dir/node_modules/ajv/dist/2020" \
  python -m unittest tests.test_tipjar.ManifestTests -v
rm -rf "$parity_dir"
```

Setting `TIPJAR_PARITY_AJV` selects that exact validator module and makes missing
Node or Ajv a failure instead of a skip. The npm install uses the network and
requires no GitHub credentials.

The protocol tests use fake GitHub responses and temporary Git repositories;
they need Git but no GitHub authentication or network. Run them from this root.
The build/install check downloads standard build tools, creates wheel and source
archives, rebuilds from the source archive, and installs into temporary clean
virtual environments outside the checkout. It checks both `agent-contrib` and
`tipjar` console entry points and `python -m agent_contribute`, metadata, packaged resources, the Skill export, schema compatibility
and refusal to overwrite. It needs network access to retrieve build tooling,
not credentials. No Rust or LightCraft checkout is involved.

CI runs unit tests on the Python versions in
[ci.yml](.github/workflows/ci.yml) and the standalone package check. For a live
read-only check, install `gh` and authenticate separately, then use
`python -m agent_contribute discover owner/repo`. Live results change over time;
do not turn them into deterministic unit fixtures or publish private data.

The full suite and package checks run on Linux. Windows/macOS jobs run only
`tests.test_host_input_transport` and installed offline entrypoint smoke checks
on Python 3.10 and 3.14. Those jobs do not establish portability of the complete
Git, cache or evidence workflows.

## Changes and reviews

- Releases follow [docs/releasing.md](docs/releasing.md); `python tools/release_check.py`
  confirms that every version statement agrees. Releasing needs the maintainer's decision.
- Keep the single Skill source in
  `agent_contribute/adapters/agent-contribute/SKILL.md`. Export it through the CLI.
- CLI/library releases use semantic versions. Schema versions are separate;
  unsupported versions must fail closed. Never silently reinterpret old tasks.
- Add meaningful regressions for behavior/security changes. Preserve tests that
  cover untrusted text, incomplete reads, authorization and Git boundaries.
- When changing the installed workflow, review both contribution quality and
  trust boundaries. Preserve the requirements ledger, precommit ordering and
  independent compliance review; do not imply the CLI proves prose compliance.
- Record actual commands, exit status and limitations in the PR. Never claim
  tests passed if they were skipped or not run.
- Get independent review for authorization, input-handling and packaging changes.
- Keep credentials, host paths, caches, pilot/session logs and generated evidence
  out of commits. Preserve existing user changes and work in an isolated branch.

Submitting a contribution does not imply acceptance. Follow the repository's
actual policies, and do not use an ordinary open issue as permission to submit
agent-generated work. This repository does not enable an agent-approval label
policy by default.

## Release checklist

1. Review the change and changelog; align package and CLI versions. Confirm the
   supported schema set and packaged workflow. Readiness tests must pass.
2. Run all unit and standalone packaging checks on the final candidate. Push
   only with authorization and wait for GitHub Actions on that exact revision.
3. Create an annotated release tag after review. Never move an existing tag.
4. Publish a GitHub release with limitations and version compatibility. If
   attaching build artifacts, include checksums and build from that exact tag.
5. Install the published tag in a new environment outside the checkout and
   verify the console command, workflow, schemas and exported Skill. Exercise
   the installed Skill with a compatible harness.

Publishing to PyPI is outside the current release process. There are no silent
updates; users choose a version and refresh their Skill deliberately.
