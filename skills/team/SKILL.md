---
name: team
description: This skill should be used when the user wants Claude agents to collaborate as a coordinated team in a cccp cell — dividing work, staying in sync, and following shared team norms. Phrases like "start a team in cell X", "coordinate with the other Claudes on X", "work as a cell/crew", or joining a cell where several comrades are working toward one goal.
argument-hint: <cell-name> [optional additional context]
allowed-tools: Bash, Monitor, TaskStop
---

!`"${CLAUDE_PLUGIN_ROOT}/scripts/cccp" skill team`

User arguments: $ARGUMENTS
