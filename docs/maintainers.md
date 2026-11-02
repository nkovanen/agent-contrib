# Maintainer integration

Discovery works without installing anything in your repository. Agent Contrib
reads Issues, open PRs, root contribution policies, nested AGENTS.md/CLAUDE.md
and specification/architecture indexes from the observed default-branch commit.
Agents must also read relevant specification contents and obey your actual
contribution rules. Existing labels alone do not authorize AI-generated work.

## Explicit opt-in policy

If your project accepts this authority model, commit `.agent-contrib.json` on
your default branch:

```json
{
  "schema_version": "0.1",
  "agent_approved_labels": ["agent-approved"],
  "label_authority": "repository-label-permission"
}
```

Apply a designated label only to tasks with clear scope, acceptance criteria,
validation and prohibited changes. Generic triage labels such as `bug`,
`help wanted` and `good first issue` cannot be used as approval labels.

**This policy delegates to every account GitHub permits to apply labels,
including triagers.** v0 does not inspect the labeling actor's maintainer status.
If you need narrower or signed approval, do not opt in under this policy yet;
issues will remain candidates. A malformed or unreadable policy is unknown,
not an invitation to proceed. Verification rereads current policy and labels.

Repository approval identifies eligible work; it does not authorize the
contributor's local execution, open a PR, replace human review or promise
acceptance. User authorization must independently cover the implementation and
publication target. Resolving a fork's parent never grants either permission.

## See what an agent sees

`agent-contrib audit owner/repo` is a read-only report that uses exactly the
reads `discover` makes. It shows the policy state and why a policy is invalid
or unknown, approval labels the policy names but the repository lacks, generic
labels used as approval labels, malformed label names (which make the report
incomplete), instruction files agents load, and for each expected kind
(contributing guide, AGENTS.md/CLAUDE.md, pull request template,
architecture/spec index) whether it is `loaded`, `present_unread` (in the tree
but not among the files agents read), `missing` or `unknown` (tree incomplete),
the 60-file instruction cap and whether the tree read was complete. It also counts open issues by ambiguity and approval
state, excluded and overlapping issues, open PRs and overlap density, and shows
fork/tracker resolution. Suggestions are non-binding. `--print-policy` adds a
valid policy template to the JSON output; nothing is written to the repository.
Exit 1 means some read was incomplete.

## AI-contribution statements

Agents receive a `repository_policy` report on every `discover`, `inspect` and
`prepare`. It covers your CONTRIBUTING (including `.rst`), `AI_POLICY.md`,
AGENTS.md/CLAUDE.md, PR templates, the code of conduct and other policy files,
plus your owner `.github` repository. Lines that look like AI, agent or
pull-request restrictions are quoted as hints, and the workflow requires agents
to read the sources, stop when you refuse such contributions, and treat
unreadable delegated policies as unresolved.

Plain, explicit sentences in a Markdown, reStructuredText or text file in the
repository are easiest to find. Policies only on a website, wiki, image or PDF
are listed as not assessed. A machine-readable opt-out in `.agent-contrib.json`
is not supported yet; until it is, state refusals clearly in CONTRIBUTING.md.

## Practical guidance

Keep contribution policy and agent instructions consistent. State permitted
changes, required tests and how to report failures/skips. A portable reviewed
contract should include explicit allowed/prohibited paths, prerequisites,
acceptance criteria and evidence requirements. Avoid commands in issue text
that encourage agents to execute arbitrary downloaded code.

No GitHub App, webhook, hosted service or additional CI integration is required.
You may add repository-native checks later; this release supplies a passive
local verifier, not a trusted admission controller. Review actual diffs, logs
and provenance because evidence and reviewer identities are self-attested.

## Authorize one candidate without repository-wide opt-in

The v0.3.0 candidate adds an explicit schema 0.2 route for a same-repository task.
The human/host approves a reviewed contract and exact actions, while GitHub
independently confirms the personal credential's admin/maintain role. The issue
stays a candidate whether the opt-in policy is absent or simply lacks a matching
label. An unreadable or malformed policy still blocks.

Review the scope and retain your actual approval event and mandate hash outside
the worker. Do not let the worker fill an approval field on your behalf. Pending
final human sign-off need not prevent an authorized tested draft; it always
prevents final completion. See [the host handoff](host-authorization.md).
