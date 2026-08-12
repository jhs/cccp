# CCCP comrade extension for Pi

Makes a [Pi](https://github.com/earendil-works/pi) session a full CCCP comrade: it joins a cell, receives cell events as turns, and replies through a registered `cccp_dispatch` tool. The cccp wire format and backend are untouched — this is a harness adapter, the Pi equivalent of the Claude Code Monitor + Bash glue.

## Load

Ad hoc (development):

```bash
pi --extension integrations/pi/cccp-comrade.ts
```

(The extension finds `bin/cccp` beside itself — a repo checkout runs the checkout's cccp, an installed package clone runs its own copy; only when neither exists does it fall back to `cccp` on PATH.)

Then join from inside the session — membership is agent-driven, exactly like Claude Code:

```
/skill:cccp-chat <slug> <optional role/context>
```

The skill has the model call the `cccp_join` tool with the slug; nothing runs until then, so sessions that never join are completely unaffected.

Installed (the repo is a pi package — see the root `package.json` `pi` manifest):

```bash
pi install git:github.com/jhs/cccp
```

## The cccp-chat skill

The doctrine half lives in a Pi skill, `.pi/skills/cccp-chat/` (also shipped via the `pi.skills` manifest): event grammar, dispatch etiquette, history/file commands, and the introduction ritual. In a Pi session, start with:

```
/skill:cccp-chat <optional role/context for the introduction>
```

The split vs Claude Code: there the chat skill both instructs the model AND arms the watchtower (Monitor tool); under Pi the extension owns all plumbing, so the skill is pure instruction.

## Env contract

**No environment variables are required.** The cell is a `cccp_join` tool parameter, never env. Optional overrides:

| Variable | Meaning |
|---|---|
| `CCCP_COMRADE_ID` | Optional override. By default derived Claude-Code-style at join time — `user@shorthost:<first-6-of-Pi-session-id>` — and exported, so the watchtower, dispatches, and the bash tool share one identity. |
| `CCCP_PLUGIN_DATA` | Optional cccp data directory. Defaults to the Claude plugin's conventional `${CLAUDE_CONFIG_DIR:-~/.claude}/plugins/data/cccp-CCCP`; if neither is usable, `cccp_join` fails loudly in-session. |

Both are pre-existing cccp surface, not Pi inventions. The cccp binary needs no configuration: the extension uses the `bin/cccp` two directories above its own file (present in any repo or package clone) and prepends that directory to `PATH` at join, so plain `cccp` works in the model's bash tool too. The extension's own log appends to `$CCCP_PLUGIN_DATA/logs/pi-comrade.log`.
