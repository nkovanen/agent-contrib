---
name: agent-contribute
description: Use when asked to help an open-source GitHub repository, select contribution work, or prepare an agent contribution handoff.
---

First run `agent-contrib --format text instructions` and read the workflow it
prints (an older CLI without `--format`: `agent-contrib instructions`, field
`workflow_markdown`). Start with its "Quick path" section: the command sequence
and the points where you must stop. The installed CLI/library owns the protocol,
schemas, compatibility checks and guidance. Follow that workflow for the
repository the user identifies. Build its required
source-linked repository requirements ledger before implementation and have an
independent reviewer check compliance before publication. Passing tests or CLI
gates alone does not establish compliance.

Use `agent-contrib --help` for the installed command surface. Delegate discovery,
inspection, contract preparation and evidence verification to `agent-contrib discover`, `inspect`, `prepare` and `verify` as directed by the workflow.
Perform implementation through your ordinary tools within the user's actual
authority. Report the CLI's observed results and unresolved gates.

If the installed command or required schema is unavailable, report that blocker.
Do not invent a substitute workflow. Installation and updates are explicit user
choices; this adapter does not update the CLI or run a model.
