# Give back to projects you depend on

A Tipjar gift is useful agent work. Start locally to find possible projects:

```sh
tipjar --format text dependencies ./my-project
tipjar dependencies ./my-project --output dependency-report.json
```

Add `--installed` to resolve ordinary npm registry dependencies from packages
that are already present locally (see the worked example below).

This command is offline: it reads declarations, makes no registry or GitHub
requests, and never installs packages, imports project code or runs a build.
Private package names stay local. The optional output is a new JSON file and
cannot overwrite an existing file. JSON is canonical; text summarizes up to 50
entries per list. `tipjar schema dependencies` prints the output schema.

Review `repositories`, then inspect a repository you choose explicitly:

```sh
tipjar discover owner/repository --signals
```

`discover` contacts GitHub and sends that selected repository name. It can read
several reviewed names using its existing `--repositories-file` format (one
`owner/repository` per line, at most 20). The dependency report itself is JSON,
not a repositories file. There is no automatic handoff or network scan.

Read the returned repository policy and any jar invitation before choosing an
issue. A dependency reference does not establish ownership, policy approval,
welcoming maintainers or permission to implement or publish. An absent jar is
undeclared. Respect explicit prohibitions and keep execution and publication
authorization separate; continue through the normal
[contribution workflow](getting-started.md).

## Supported first slice

| Input | Read locally | Limits |
| --- | --- | --- |
| `package.json` | `dependencies`, `devDependencies`, `optionalDependencies`, `peerDependencies` | Only explicit GitHub URLs resolve; registry versions and aliases remain unresolved |
| `package-lock.json` | v1 nested `dependencies`; v2/v3 `packages`, including root dependency groups | `resolved` takes precedence over `version`; transitive packages are included; workspaces are not followed |
| `requirements.txt` | Named direct references: `name[extra] @ git+https://github.com/owner/repo.git@revision#subdirectory=path` | Whitespace-prefixed comments outside quotes are stripped; URL fragments and quoted marker text are preserved. Environment markers are not evaluated; includes, editable installs, continuations, hashes and other pip options are unsupported and never followed |

The npm URL forms accepted are `https://github.com/owner/repo.git#revision`,
`git+https://github.com/owner/repo.git#revision`, and
`git@github.com:owner/repo.git#revision`. Requirements may use `@revision`
after the repository path, with an optional `#subdirectory=relative/path`.
References retain their case, revision and subdirectory. Repository candidates
deduplicate case-insensitively, in first-observed order. Credentials, ports,
queries, traversal, percent escapes, other hosts and GitHub web-page paths do not
produce repository candidates. GitHub shorthand is deliberately unsupported.
Raw URL declarations are omitted from reports so refused credentials are not echoed.

`PATH` may name one supported file or a directory. By default, a directory reads only the
three filenames above; there is no recursive scan. Present `Cargo.toml`,
`Cargo.lock` and `pyproject.toml` are listed as unsupported; no TOML parser or
registry-name guessing is included. Other filenames are outside this scan.

Each observation includes package, ecosystem, source filename, field (or line),
status/reason, repository, revision and subdirectory. `sources` records exact
SHA-256 hashes of the input bytes. These are declaration provenance, not proof
that a dependency was installed, used, verified or maintained by that repository.
Requirement markers and npm optional/dev groups are included regardless of the
current environment. Lockfile and manifest observations can disagree; both remain
visible, and revisions are not checked against GitHub.

`complete` means supported file coverage was read without known unsupported
manifest files; `resolution_complete` additionally means every declaration
resolved to an explicit GitHub URL. Unresolved packages and non-GitHub sources
remain visible. A successful report exits 0 even when either flag is false;
malformed/ambiguous input exits 1 without partial candidates. GitHub-only global
options `--cache` and `--report-budget` are refused.

Inputs are UTF-8, at most 8 MiB per file and 10,000 observations across the
report, with bounded names and fields. Nonregular files, symlinks in any input
path component, malformed JSON, duplicate keys and unknown lockfile versions
are refused. Symlink-safe descriptor-relative reads currently require POSIX
filesystem support; unsupported platforms fail closed. This is an offline
observation tool, not a sandbox against concurrent same-user file modification.

## Common npm dependencies already installed

Suppose an existing project declares ordinary registry versions:

```json
{"dependencies": {"express": "^5", "react": "^19", "lodash": "^4"}}
```

If its existing `node_modules/express/package.json`,
`node_modules/react/package.json` and `node_modules/lodash/package.json` contain
matching package names, observed versions and GitHub `repository` metadata:

```sh
tipjar --format text dependencies ./my-project --installed
tipjar dependencies ./my-project --installed --output installed-targets.json
```

For example, metadata naming `express` version `5.1.0` and repository
`https://github.com/expressjs/express.git` yields `expressjs/express`, with the
observed version and `node_modules/express/package.json` hash in the report.
Equivalent React/Lodash metadata yields `facebook/react` and `lodash/lodash`.
The tool does **not** install missing packages. Without `--installed`, those
registry declarations remain unresolved and node_modules is never read.

The option requires a directory containing package.json, or that file itself.
It reads only the exact `node_modules/NAME/package.json` paths for unique direct
registry dependencies in the supported manifest groups, including scoped names.
Project direct candidates precede lockfile candidates. No transitive installed
packages, parent directories, workspaces, aliases (`npm:`), local dependencies
or included files are searched. More than 100 eligible unique package names
fails closed; each metadata file has a 64 KiB regular-file bound. Symlinks in
node_modules, scope/package directories or package.json are refused, including
pnpm's usual symlink layout, and surfaced as unsupported rather than followed.

String and object `repository` metadata may use the same explicit GitHub URL
forms as declarations. Objects can specify `directory` for a monorepo package;
conflicting URL/directory subpaths remain ambiguous. Homepages and package names
never supply repository guesses. Missing/mismatched names, malformed JSON or
versions, absent repository metadata, and non-GitHub/unsafe sources remain visible.
A version must look like a concrete npm version; the tool does not evaluate
semver ranges or cross-check a lockfile to verify the observed version satisfies
the declaration. Installed metadata is untrusted local evidence, not proof of
package integrity, ownership, actual use, or maintainer invitation.

With the flag, top-level `installed` reports examined package count and complete
resolution of those lookups. Every attempted declaration has an `installed`
record with relative metadata file, SHA-256 when readable, observed name/version,
repository field and status/reason. Declaration provenance remains attached to
package.json. Missing/unsupported metadata makes `complete` and
`resolution_complete` false; successful partial reports still exit 0. Lockfile
registry-only entries remain unresolved even when a direct declaration resolves.
Review the explicit selected repository with `discover` as described above.
