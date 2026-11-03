# Plan a gift-work session

A gift is agent work, not money. A session is an offline reviewable shortlist,
not an execution plan approved by a maintainer or host. It works today with an
explicitly chosen repository; no jar adoption is required.

For a 60-minute stopping budget and at most three tasks:

```sh
tipjar discover owner/repo --signals --limit 10 > discovery.json
tipjar session discovery.json --max-tasks 3 --minutes 60 --output session.json
tipjar --format text session discovery.json --max-tasks 3 --minutes 60 --output another-session.json
tipjar schema session
```

Check discovery's exit status and errors. Failed or incomplete repositories stay
in the source report and cannot supply selected tasks; complete repositories in
a mixed report can still supply candidates. A valid proposed session exits zero
even if it selects nothing. This does not mean any work is authorized. Output
paths are created exclusively, so choose a new path for every proposal.

The planner reads a regular UTF-8 JSON file of at most 8 MiB, uses no network,
and executes nothing. It accepts the current bundled discovery output schema;
unknown versions and properties fail closed. It rejects duplicate/conflicting
issue identities, issue URLs and merged candidate flags. Input remains untrusted:
a structurally consistent snapshot and its SHA-256 do not prove GitHub state,
maintainer consent, or human authorization.

Selection preserves the existing discovery candidate order. Excluded diagnostic
issues in a mixed report receive decisions after those candidates, with no time
allocated. Repositories rejected by discovery selection and observed closed,
unknown or incomplete jars cannot supply tasks. Explicit undeclared repositories
remain candidates for manual policy review. Only complete issues from
complete repository reports with no exclusions, overlapping PRs or unknown source
approval can enter the shortlist. Known assignees, merged-fix/top-check demotions
and references in local work are excluded with reasons, including local references
reported without ranking signals. Incomplete local-work reports and unknown
per-issue local-work observations also block selection. Target identities must
agree with the requested repository and recorded tracker/parent metadata.
Candidate source approval remains a candidate;
it is never upgraded to approved. The limit is 1–20 tasks and 1–1440 minutes,
with at least one minute per selected task. Minutes divide evenly (the earliest
tasks receive any remainder). These are caps at which the host must stop, not
predictions of completion time. If no task qualifies, no minutes are allocated.

The artifact embeds the exact parsed `source_report` and records the SHA-256 of
the original file bytes. Task indices point into its repository and issue lists.
Every retained candidate has a selection decision and reasons. Source display
counts, hidden candidates, scan caps, errors, provenance, policy digests and
requested/source/target repository distinctions remain in that report. A display
limit hides candidates from planning; the planner cannot recover them or claim
to have checked all issues. Do not treat the abridged text summary as an audit.

## How a host agent uses the proposal

Present the shortlist and source limits for human review. For each task, refresh
repository policies and instructions and recheck its jar. Current discovery
includes the pinned issue-source jar observation and its selection decision;
the session preserves these historical observations without refreshing them.
Older snapshots without a jar observation remain unassessed and need manual
review. An undeclared jar permits proposing manual review, never implies source
approval; closed or unknown declarations must stop work. Do not infer permission
from labels or ranking.

Ownership and local-work checks that were not requested remain unassessed, not
passed; review them manually. Refresh `tipjar inspect owner/repo#N --ownership`
and review existing local work. Resolve claims, prior fixes,
PR overlap and incomplete reads. Prepare and review a normal scoped contract;
follow the installed workflow's applicable authorization route. Stop before
implementation until actual human/host authority covers it. Review checkout and
validation commands before host execution. Publication and final completion need
their own authority. The session issues no mandate and runs no agent.

Enforce the total session budget as well as each task's cap, including policy
review and preparation. Stop when a cap is reached even if a task is unfinished;
report actual progress and request a separately authorized continuation. Finish
early when appropriate: a budget is a ceiling, not an obligation to spend it.
