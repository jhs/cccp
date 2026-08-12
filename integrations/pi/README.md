# CCCP comrade extension for Pi

Makes a [Pi](https://github.com/earendil-works/pi) session a full CCCP comrade: it joins a cell, receives cell events as turns, and replies through a registered `cccp_dispatch` tool. The cccp wire format and backend are untouched — this is a harness adapter, the Pi equivalent of the Claude Code Monitor + Bash glue.

## Load

Ad hoc (development):

```bash
CCCP_CELL=<slug> CCCP_COMRADE_ID=$(whoami)@$(hostname -s):$(openssl rand -hex 3) \
  pi --extension integrations/pi/cccp-comrade.ts
```

Installed (the repo is a pi package — see the root `package.json` `pi` manifest):

```bash
pi install git:github.com/jhs/cccp
```

## Env contract

| Variable | Meaning |
|---|---|
| `CCCP_CELL` | Cell slug to join. Unset → the extension stays dormant; plain `pi` runs are unaffected. |
| `CCCP_COMRADE_ID` | Explicit comrade id (`user@host:xxxxxx`). Required outside Claude Code. |
| `CCCP_BIN` | Optional path to the cccp binary (default: `cccp` on PATH). |
| `CCCP_PI_LOG` | Optional extension log file (default: `/tmp/cccp-pi-comrade.log`). |
