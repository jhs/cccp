---
name: chat
description: This skill should be used when the user wants to communicate with another Claude — phrases like "talk to the Claude on my Mac", "connect with comrade X", "join cell X" or anything about messages or file sharing with other Claude instances.
argument-hint: <cell-name> [optional additional context]
allowed-tools: Bash, Monitor, TaskStop
---

!`"${CLAUDE_PLUGIN_ROOT}/scripts/cccp" skill`

User arguments: $ARGUMENTS
