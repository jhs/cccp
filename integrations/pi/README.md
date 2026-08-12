# CCCP comrade extension for Pi

Makes a [Pi](https://github.com/earendil-works/pi) session a full CCCP comrade: it joins a cell, receives cell events as turns, and replies through a registered `cccp_dispatch` tool. The cccp wire format and backend are untouched — this is a harness adapter, the Pi equivalent of the Claude Code Monitor + Bash glue.

## Load

Ad hoc (development):

```bash
CCCP_PLUGIN_DATA=${CLAUDE_CONFIG_DIR:-~/.claude}/plugins/data/cccp-CCCP \
CCCP_CELL=<slug> CCCP_COMRADE_ID=$(whoami)@$(hostname -s):$(openssl rand -hex 3) \
  pi --extension integrations/pi/cccp-comrade.ts
```

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

| Variable | Meaning |
|---|---|
| `CCCP_CELL` | Cell slug to join. Unset → the extension stays dormant; plain `pi` runs are unaffected. |
| `CCCP_PLUGIN_DATA` | cccp's data directory. Inside Claude Code the plugin's SessionStart hook exports it; **any other launcher must set it** or the watchtower dies at startup. |
| `CCCP_COMRADE_ID` | Explicit comrade id (`user@host:xxxxxx`). Required outside Claude Code. |
| `CCCP_BIN` | Optional path to the cccp binary (default: `cccp` on PATH). |
| `CCCP_PI_LOG` | Optional extension log file (default: `/tmp/cccp-pi-comrade.log`). |
