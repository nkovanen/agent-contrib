# Tipjar directory

A local-first static directory and manifest editor. Tips are agent work, not
money. The six initial projects are fictional samples: no real invitations,
endorsements, contribution counts or claims of maintainer consent.

From a source checkout (or extracted source distribution):

```sh
python3 -m http.server 8765 --bind 127.0.0.1 --directory web
```

Open http://localhost:8765. No frontend installation, build, credentials, remote
fonts, telemetry, or GitHub requests are needed. The page does not save imported
data; reloading restores the demo. The Python package/wheel is independent of
the site. Node is optional for development: `node tests/web/model.test.cjs` tests
the data boundaries; unittest runs it when Node is available.

## Use a real snapshot

In this unreleased preview, export a bounded public search batch with the candidate CLI:

```sh
tipjar find > jars.json
```

Choose or drop `jars.json` below. Search coverage is partial and indexing may lag;
no adoption or exhaustive directory is established. A failed/incomplete batch may
still retain observations; inspect its diagnostics before using it.
This importer requires format `find-jars-report/1`, at most 1 MiB and 200
observations. It ignores extra bounded metadata, rejects unknown formats,
invalid identities, conflicting dispositions, duplicate repositories, invalid
UTF-8 and unsupported manifest schemas. Example **fictional** snapshot:

```json
{
  "format": "find-jars-report/1",
  "complete": true,
  "observations": [{
    "repository": "example/project",
    "disposition": "welcome",
    "jar": {
      "repository": "example/project",
      "state": "welcome",
      "complete": true,
      "commit": null,
      "sha256": null,
      "manifest": {"schema_version": "0.1", "status": "welcome", "wanted": ["Documentation"]}
    }
  }]
}
```

A snapshot is untrusted data, not verified permission. The overall `complete`
flag reports whether this bounded batch finished its reads without unresolved
observations/errors. It never means exhaustive discovery: indexed coverage is
always partial, including when `complete` is true. Each jar has its own read
completeness. Search errors appear separately from coverage and batch-read status.
Canonical null repository observations (malformed or privacy-suppressed hits)
are counted as skipped, without inventing names or displaying their identity
metadata. An invalid null diagnostic still rejects the entire import and leaves
the prior collection intact. Search diagnostics are bounded to 200 strings of
at most 500 codepoints; unknown diagnostic text is not displayed.
Incomplete jars cannot be welcomed. Unknown and excluded observations offer only
reinspection; closed declarations stop work. Source URLs are generated from
validated GitHub repository/commit identities; imported URLs are never used.
Use the detail commands to recheck current declarations and policies, then
inspect an issue. Replace `ISSUE_NUMBER` before running the inspect command.
Welcome grants neither issue approval nor local execution/publication authority.

## Maintainer draft

Edit the status, wanted work and boundaries. The preview/download uses the exact
0.1 manifest schema (at most 16 distinct lines per list, 500 characters per line,
16 KiB JSON). Exact line content is preserved; empty lines are skipped, but
whitespace-only lines and control characters are rejected. The 32768 UTF-16-unit
input memory cap exceeds every schema-valid per-field value (at most 16015 units
including line breaks); the schema still counts Unicode codepoints. Review the downloaded `.tipjar.json`, then add it to your repository
yourself. Downloading changes no repository. A closed manifest expresses refusal.

## Optional static hosting

The `web/` contents are ready for GitHub Pages or another static host, including
project subpaths: all assets use relative URLs. In a separately authorized hosting
change, copy the contents of `web/` to the selected Pages publication root (or
upload it as a Pages artifact), and configure Pages through repository settings.
Do not select the repository root: this page is in `web/`. No deployment workflow
or Pages configuration is enabled by this contribution. Hosted copies retain the
same local-file import behavior and never query GitHub automatically. Clipboard
copy uses the browser's secure-context API; if unavailable, it selects the command
for manual copying. Browsers may prompt before downloading JSON.

## Browser checks

Verify desktop and 390px layouts, search/filter/empty states, detail dialog via
keyboard and Escape focus return, closed/unknown/excluded stops, valid/invalid
file input and drop, literal hostile HTML, preview validation and JSON download.
No receipt/impact viewer is included; its contract is a separate feature.

The repeatable DOM-event regression page is `tests/web/browser.html`. For local
QA, serve the repository root with `python3 -m http.server 8766 --bind 127.0.0.1`
and open `http://localhost:8766/tests/web/browser.html`. It exercises actual file
input, synthetic drop events, invalid-import preservation, hostile text, editor
limits, and copy/download boundaries. Clipboard and download OS boundaries are
replaced to inspect exact values; native keyboard actions and the OS clipboard /
save dialog still require manual testing. A background browser may defer the
native close event; the page reports this as a LIMIT rather than a passed check.
