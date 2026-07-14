---
name: foreman-with-tmux
description: This skill should be used when the user wants Claude to act as the coordinator of a cccp cell with the ability to spawn, observe, and terminate comrades as tmux windows. Phrases like "be the foreman with tmux for cell X", "coordinate cell X and manage comrades via tmux", or any foreman role where tmux-based comrade lifecycle management is needed.
argument-hint: <cell-name> [optional additional context]
allowed-tools: Bash, Monitor, TaskStop
---

!`"${CLAUDE_PLUGIN_ROOT}/bin/cccp" skill foreman-with-tmux`

User arguments: $ARGUMENTS
