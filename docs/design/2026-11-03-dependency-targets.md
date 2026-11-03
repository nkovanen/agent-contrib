# Offline dependency give-back targets

## Design

`tipjar dependencies PATH` reads a project directory or one supported manifest,
without Git, network, imports, installation or build commands. The first slice
supports package.json dependency groups, package-lock.json versions 1–3, and
requirements.txt named direct references. Directory reads are limited to those
three filenames; Cargo.toml, Cargo.lock and pyproject.toml are explicitly reported
as unsupported when present. Includes, workspaces and other files are not followed.

Only explicit https://github.com, git+https://github.com and git@github.com:
URLs become candidates. Repository names deduplicate case-insensitively; each
declaration retains package, ecosystem, relative source filename, field, revision
and subdirectory provenance. Unsafe URLs, other hosts, registry versions and
unsupported requirement syntax remain unresolved. Raw declarations are omitted
so credentials in refused URLs are not echoed. Source hashes bind observations
to exact bytes; they do not establish package ownership or welcoming policy.

Inputs must be bounded UTF-8 regular files, with no symlink path components.
Malformed JSON, duplicate keys, invalid manifest structure, excessive entries
and unsupported lock versions fail closed. JSON and sanitized text are available;
`--output` exclusively creates an optional JSON report. `complete` describes
supported file coverage; `resolution_complete` additionally requires every
observed dependency to resolve. Unsupported declarations do not prevent reporting
other candidates. No candidate grants approval or execution/publication authority.

## Implementation plan

1. Write fixtures/regressions for real npm locks, requirements, URL boundaries,
   provenance, deduplication, malformed input and filesystem bounds; observe red.
2. Implement one standard-library-only dependencies module and focused parsers.
3. Add an offline CLI command, JSON schema, text output and optional exclusive
   output. Keep discover input unchanged; users review and select candidates.
4. Document the report-to-discover/jar-review workflow and limits. Generate the
   output reference; run the full suite and build/install checks.
5. Merge latest origin/main without rebasing, reverify, commit for independent review.
