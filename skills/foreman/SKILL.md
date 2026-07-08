---
name: foreman
description: This skill should be used when the user wants Claude to act as the coordinator of a cccp cell — the one who organizes, sequences, and delegates work across the other comrades and reports up to the user. Phrases like "be the foreman/lead/coordinator for cell X", "you organize the other Claudes on X", "run the team in cell X", or taking ownership of coordinating a multi-comrade effort.
argument-hint: <cell-name> [optional additional context]
allowed-tools: Bash, Monitor, TaskStop
---

!`"${CLAUDE_PLUGIN_ROOT}/scripts/cccp" skill foreman`

User arguments: $ARGUMENTS
