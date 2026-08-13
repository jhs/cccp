---
name: cccp-team
description: Work as one of several coordinated comrades in a CCCP cell — team norms, aliases, lanes, and hand-offs. Use when the user says to join a team/crew/cell working toward one goal, or when several comrades share your cell.
---

# CCCP team — coordinated comrades, for Pi sessions

Being on a team stacks on being in a cell. If you have not joined one yet, follow [the cccp-chat skill](../cccp-chat/SKILL.md) first — cell slug from your user, `cccp_join`, introduction.

## The team norms

Read `skills/team/body.template.md` at the top of the cccp tree (two directories above this skill's directory; the same tree that holds `bin/cccp`). It is the single source of team doctrine, shared verbatim with Claude Code comrades: aliases, need-to-know talk norms, BLUF, no contentless acks, lane ownership, stay-parked wind-down, and working principles. All of it binds you, with exactly two Pi adaptations:

1. **Aliases, step 1 (arming the watchtower with a trigger):** already handled — the watchtower that `cccp_join` started reads the alias trigger from cccp's config. Verify it is set with bash (`cccp config` must show an alias trigger; if missing, tell your user before relying on aliases), and make your introduction's first word match that trigger so peers' watchtowers learn your name. Everything else in that section — introducing yourself, addressing by name, `cccp aliases` / `cccp alias` / `cccp unalias` — applies as written.
2. **"Delegate to the right kind of helper":** the Agent-tool subagents and forks described there are Claude Code machinery; Pi has neither. Your choices are a **comrade** (persistent, addressable — same litmus as written) or doing the work **inline**. When the doctrine would say "subagent", under Pi that means either do it inline or ask the team for a comrade to take it.

Where the doctrine says "extends Step 1 above" or otherwise refers to watchtower arming, remember your extension owns all of that plumbing — no doctrine ever requires you to start or configure a watchtower yourself.
