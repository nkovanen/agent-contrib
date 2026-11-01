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
