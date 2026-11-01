---
name: agent-contribute
description: Use when asked to help an open-source GitHub repository, select contribution work, or prepare an agent contribution handoff.
---

Run `agent-contrib instructions` first and read its JSON workflow. The installed
CLI/library owns the protocol, schemas, compatibility checks and guidance.
Follow that workflow for the repository the user identifies.

Use `agent-contrib --help` for the installed command surface. Delegate discovery,
inspection, contract preparation and evidence verification to `agent-contrib discover`, `inspect`, `prepare` and `verify` as directed by the workflow.
Perform implementation through your ordinary tools within the user's actual
authority. Report the CLI's observed results and unresolved gates.

If the installed command or required schema is unavailable, report that blocker.
Do not invent a substitute workflow. Installation and updates are explicit user
choices; this adapter does not update the CLI or run a model.
