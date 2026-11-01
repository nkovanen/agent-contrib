# Architecture and contributor workflow

Agent Contrib separates a small portable adapter from a versioned protocol.

- **Skill:** asks the installed CLI for its workflow, then uses the host agent's
  normal tools. One canonical source is packaged and exported without overwrite.
- **CLI (`agent_contribute.cli`):** fixed commands and JSON output; exclusive
  local draft/Skill writes; no model, task executor or GitHub write operations.
- **Library (`agent_contribute.core`):** GitHub GETs through `gh`, bounded discovery,
  repository resolution, policy evaluation, contract/evidence validation and
  defensive Git reads. The agent still judges feasibility and implements work.
- **Schemas and instructions:** release resources read through Python's package
  resource API, not a source-checkout path. No LightCraft imports or build system.

The installed workflow from `agent-contrib instructions` is authoritative. This
page is an overview, not a second independently maintained execution protocol.

1. Discover the requested repository's tracker, resolving one parent when needed.
2. Rank feasible work; inspect requirements, repository policies, ownership and
   PR overlap. Manually check timeline claims and recently merged work.
3. Prepare and review a scoped contract. Candidate issues remain candidates
   until the source's explicit approval policy says otherwise.
4. Verify execution gates and the user's actual scope. A bare help request stops
   at a reviewable draft; existing explicit authority is honored.
5. Use an isolated branch/worktree and the agent's own implementation tools.
   Inspect build/test commands before running them.
6. Record real revision-bound validation and artifacts. Obtain independent
   adversarial review and final-revision human sign-off.
7. Verify supplied evidence. Prepare a PR description following the discovered
   repository template and policies. Publication remains a separately authorized
   host action; never merge automatically.

GitHub is the source of truth. Task/evidence JSON is portable but not trusted
executable instruction. There is no central service, database, model credential,
agent subscription or automatic update channel.

CLI versions use semantic versioning; schema support is an explicit exact set
(currently `0.1`). The closed schemas and bundled validator reject unknown
versions/properties and malformed JSON. A schema migration requires a future
reviewed release; it is never guessed from a contract.
