# Offline gift-session planner design and plan

Build `tipjar session DISCOVERY_JSON --max-tasks N --minutes M --output FILE`
as a standard-library-only offline planner. Consume the current packaged discovery
schema strictly, rejecting unsupported shapes/versions and conflicting identities.
Accept bounded regular UTF-8 JSON files (8 MiB), never execute their contents.
Keep the entire untrusted source snapshot and its exact file SHA-256 in the output;
this preserves provenance, digests, requested/source/target distinctions and limits.
A snapshot is consistency data, never proof of GitHub state or consent.

Preserve single-repository issue order and multi-repository candidate order. Only
complete, nonexcluded, nonoverlapping candidates from complete repository reports
are eligible. Keep all rejected/overflow candidates visible with reasons; retain
failed repositories and their errors. Absent jars are undeclared and require
manual review. Current discover has no integrated jar observation: do not invent
one or claim it was checked. Reject unsupported future discovery schemas rather
than silently ignoring new restrictions.

N is 1–20, M is 1–1440. Select at most min(N, M) issues, divide M into positive
integer stopping caps whose sum is M when any task is selected. These are not
completion estimates. Sessions are proposed and actions_authorized is always
false. Each task lists policy, ownership, preparation and separate authorization
stops. Output uses exclusive creation and supports a sanitized text summary.

Implementation sequence (native execution authorized by controller):
1. Add red-first tests in tests/test_sessions.py for ordered selection, honest
   limited/incomplete reporting, forged and duplicate identities, bounded input,
   caps and exclusive offline CLI behavior.
2. Implement agent_contribute/sessions.py using bundled schema validation and
   semantic identity/count checks; add minimal CLI wiring and text rendering.
3. Package session output schema, regenerate output reference, document a 60-minute
   workflow and responsible host-agent use. Run focused and full unittest suites,
   schema/reference checks and installed-package checks.
4. Merge latest origin/main without rebase, rerun affected/full verification and
   hand exact commit to controller for independent review; no push/PR/merge here.

Review focus: aliases resolving to duplicate tracker issues; forged URLs or
candidate flags; display counts contradicting retained entries; missing reports
or unknown versions becoming eligibility; hostile oversized/nonregular input.
