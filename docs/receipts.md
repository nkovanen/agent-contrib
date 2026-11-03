# Receipts and recorded impact

A Tipjar gift is useful agent work. A receipt makes the PR you want to record
visible in your own files. It records a public GitHub observation, with numeric
repository and PR identities, author, exact canonical URL, head/base SHAs and
refs, draft/open/closed/merged state and merge facts. It does not establish agent
involvement, authenticated contribution, consent, quality, tests or permission.

For example, after a separately authorized PR has been published, replace these
example references with your public PR:

```sh
tipjar receipt 'owner/repo#123' --output first-observation.json
tipjar --format text impact first-observation.json
# Later, observe again into a different file (nothing is overwritten):
tipjar receipt 'owner/repo#123' --output later-observation.json
tipjar impact first-observation.json later-observation.json
```

Capture reads two fixed GitHub REST GET endpoints: repository metadata, then PR
detail. Both responses must explicitly report `private: false` and
`visibility: public` for the base repository. Private repositories are not
supported. Use the exact current canonical repository spelling; renamed or
redirected references fail closed. Missing, malformed or contradictory metadata
produces a structured error and no receipt. This is a non-atomic snapshot, not a
live status monitor. No GitHub comments, writes, payments or tasks are executed.

Receipts use their own schema version `0.1`, independent of task/evidence schemas
and the CLI version. The receipt file schema is packaged as
`agent_contribute/receipt.schema.json`. `tipjar schema receipt` describes the
command's response (including the saved receipt); `tipjar schema impact` describes
the summary. JSON is canonical; `--format text` gives a short summary.

`impact` is fully offline. It reads 1–100 explicitly named UTF-8 JSON regular
files, at most 64 KiB each. Symlinks in receipt paths, nonregular files, duplicate
keys, unknown schema versions/properties, invalid timestamps and future
observations fail closed. An invalid file rejects the entire summary; it never
silently contributes a count. There is no global database or automatic refresh.

For each numeric repository/PR identity, the latest valid `observed_at` wins,
independent of argument order. Identical repeated files count once. Equal-time
snapshots with differing facts reject. Conflicting repository IDs/names, PR
IDs/numbers or author IDs also reject, including inconsistent snapshots across a
repository rename/transfer. In that case use a consistently refreshed collection.
The JSON lists selected receipts in numeric identity order for future local UIs.

The summary labels its input **self-reported recorded observations**: anyone can
edit a local file, so it cannot authenticate contributions. `open` includes
drafts; `closed` means unmerged; `merged` comes from the recorded merge facts.
`repositories_represented` counts distinct repositories represented by supplied PR
observations, including open/closed PRs. Representation establishes neither
acceptance nor benefit. No LOC, quality scores, validation results or invented
achievement metrics are calculated. Old observations remain old even after a PR changes on GitHub;
refresh explicitly into a new file to record its later state.
