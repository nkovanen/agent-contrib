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

**The CLI checks that a configured label is currently present on the issue
under the default-branch policy; it does not verify who applied it.** The policy
therefore delegates approval to every account GitHub permits to label issues.
It is suitable only if every principal who can label issues is trusted to
approve agent work. That includes triage, write and higher roles, custom roles
or grants that allow labelling, and any app or automation with label access. A
dedicated label name restricts nothing, and removing triage access alone is not
enough while an untrusted write collaborator or app can still label. If you
need narrower or signed approval, do not opt in under this policy; issues stay
candidates.

Actor verification is not available, and this project offers no
maintainer-only label policy ([#9](https://github.com/nkovanen/agent-contrib/issues/9)).
GitHub's public REST data cannot establish who may approve: `labeled` events
carry no role or author association and no durable label identity, and only a
credential with push access can read a collaborator's role. For work by your
own agents, use the schema 0.2 mandate route
([host authorization](host-authorization.md)) instead of label approval.

A malformed or unreadable policy is unknown, not an invitation to proceed.
Verification rereads current policy and labels.

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

## Check agent PRs passively (report only)

The candidate includes a report-only GitHub Action, slice 1 (#11), in
`actions/verify/`; copy [the example workflow](examples/agent-contrib-verify.yml)
and pin a reviewed commit. On `pull_request` it reads only the event payload and
the PR-head checkout, with `contents: read` and no API calls, and checks that the
contract and evidence blocks in the PR body describe this PR's route, head,
tree, base and scope. It never runs PR code and never writes to GitHub. Freshness,
overlap, approval and identity are listed as not evaluated; see the
[design](design/2026-11-02-maintainer-action.md) for the threat model.

## AI-contribution statements

Agents receive a `repository_policy` report on every `discover`, `inspect` and
`prepare`. It covers your CONTRIBUTING (including `.rst` and suffixed names such
as `CONTRIBUTING.en.md`), `AI_POLICY.md`, AGENTS.md/CLAUDE.md, PR templates, the
code of conduct and other policy files, plus your owner `.github` repository.
Lines that look like AI, agent or pull-request restrictions are quoted as hints.
The workflow requires agents to read the sources, record the result as the
contract prerequisite `ai-policy-review` (a refusal or anything unresolved
blocks implementation), stop when you refuse such contributions, treat
unreadable delegated policies as unresolved, and disclose agent assistance in
the PR.

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


## Repository jars (candidate, inspection only)

A root `.tipjar.json` can declare an invitation for useful **agent work**.
It does not accept money, approve issues, execute commands or grant publication
authority. The candidate's `agent-contrib jar owner/repo` inspects this file;
discovery, preparation and live gates enforce closed/unknown declarations on the
actual issue source, with no fork or approval override. Welcome is only an
invitation; wanted/boundaries remain policy-review data. Old clients do not
enforce it: state refusals plainly in ordinary contribution documentation.

### Two-minute setup (offline)

Use a reviewed v0.3.0 candidate containing these commands; the published v0.2.0
has no `tipjar` alias or jar commands. No GitHub authentication is needed to
create and check a local file. Choose a state explicitly:

```sh
# Welcome useful agent work; creates a new file, never overwrites one.
tipjar init --status welcome --output .tipjar.json
# Edit wanted and boundaries to match your actual policies before publishing.
tipjar jar-check .tipjar.json
```

The welcome template marks its wanted-work entry `EDIT before publishing`.
Replace it with concrete work you want, such as a broken documentation example
or a small bug with a regression. Review each boundary: keep the scope bounded,
require your contribution guide, and preserve separate human authorization for
local execution and publication. Validation checks structure, not whether these
statements accurately express your policy. It never approves an issue or task.

To decline agent contributions, start with an explicit closed template instead:

```sh
# Alternative to the welcome command, in a directory without .tipjar.json:
tipjar init --status closed --output .tipjar.json
tipjar jar-check .tipjar.json
```

An existing file or symlink is refused; edit your existing file deliberately,
then check it again. You may use a staging path with `--output` and place the
reviewed file at the repository root as `.tipjar.json` later. Init reports the
chosen state, exact byte SHA-256, path and next steps. Check reports the edited
file's state and exact byte SHA-256 without printing its contents. Neither command
reads GitHub, changes remote policy, publishes a file or grants authority.
See [offline manifest commands](cli.md#offline-manifest-setup-and-validation).
Keep refusals in CONTRIBUTING.md as well: older clients do not read or enforce
jars, and this branch's remote jar behavior is inspection only.

Copyable welcome example (replace the preferences with your own):

```json
{
  "schema_version": "0.1",
  "status": "welcome",
  "wanted": ["Documentation examples", "Small fixes with regressions"],
  "boundaries": ["Read CONTRIBUTING.md before choosing work"]
}
```

Copyable closed example:

```json
{
  "schema_version": "0.1",
  "status": "closed",
  "boundaries": ["Agent-generated contributions are not accepted; read CONTRIBUTING.md"]
}
```

Both optional arrays may be omitted. Only the four illustrated fields are allowed. Each array
has at most 16 distinct, nonblank strings of 1–500 Unicode code points without
C0 or DEL controls. Nonblank uses the explicit Unicode White_Space set in the
[manifest contract](superpowers/specs/2026-11-03-tipjar-design.md#manifest-01),
shared by parser and schema; U+0085 alone is blank and U+FEFF is nonblank.
The entire file is at most 16,384 bytes of strict UTF-8 JSON;
duplicate keys, nonfinite numbers and unsupported schemas fail closed.

There are no includes, hooks, executable configuration or owner inheritance.
The source root alone declares its invitation. A missing file is undeclared,
not a refusal or approval. A welcome cannot waive any repository or applicable
owner policy. Wanted text is a preference, never an eligibility score; boundaries
must be reviewed with the existing source-linked requirements ledger. Links and
commands in text remain data and are never automatically followed or executed.
See [jar inspection](cli.md#jar-inspection-candidate-inspection-only) for states,
provenance, fresh-read limits and current no-jar route limitations.


### Let the bounded finder observe your jar

Add the supported `.tipjar.json` to the repository root on its default branch,
alongside ordinary contribution policies. A minimal invitation is:

```json
{"schema_version":"0.1","status":"welcome"}
```

Optionally include `wanted` and `boundaries` arrays as described above. Verify
with `tipjar jar owner/repo`; direct inspection does not wait for indexing.
`tipjar find --owner owner` verifies at most ten indexed hits from public active
repositories. It does not register a project or promise index coverage.
Indexing may lag, especially for forks. No adoption or external invitation is
established by this implementation. Older clients do not enforce jars, so state
refusals in ordinary contribution docs too. An invitation never waives
contradictory policy or grants execution/publication authority.
