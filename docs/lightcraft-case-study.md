# LightCraft case study and provenance

Agent Contrib began as an isolated experiment in
[LightCraft fork PR #1](https://github.com/nkovanen/lightcraft/pull/1), developed
against public issues in `storytold/lightcraft`. This distribution extracts the
reusable components from PR head
[`b736531c92d4493594191434180df018e218a50b`](https://github.com/nkovanen/lightcraft/tree/b736531c92d4493594191434180df018e218a50b/experiments/agent-contribute),
not LightCraft's main branch. The standalone project uses the original MIT license option and retains
its copyright notice and attribution. Application code, Rust dependencies, pilot logs, screenshots and
session transcripts are excluded.

The pilot first rejected issue #3457 because an existing PR addressed it. A
separate Calibration reset experiment became
[fork draft PR #2](https://github.com/nkovanen/lightcraft/pull/2); its product CI
and completion status remain separate from this protocol release.

A fresh-agent trial using “Go help nkovanen/lightcraft.” exposed a practical
problem: the fork had Issues disabled. CLI 0.2.0 resolves that relationship from
GitHub metadata, reads the parent's tasks and policies, and retains the fork as
a proposed target without granting write authority. A subsequent trial scanned
654 open issues, evaluated candidates, prepared a draft for upstream #3479 and
stopped for execution authorization. The agent made the final feasibility
ranking; the CLI supplied discovery and overlap checks.

This trial was not fully blind: a public PR description mentioned an earlier
#3479 trial. It demonstrates the workflow and permission boundary, not an
unbiased task-selection benchmark. See the original
[trial report](https://github.com/nkovanen/lightcraft/blob/b736531c92d4493594191434180df018e218a50b/experiments/agent-contribute/pilot/fork-resolution-2026-11-01/REPORT.md)
for revision-bound evidence and limitations. Both LightCraft PRs remain drafts;
this extraction neither merges them nor publishes anything upstream.
