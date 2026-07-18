---
name: setup
description: This skill should be used when the user wants to inspect, choose, configure, or troubleshoot the CCCP data backend. Phrases like "which cccp backend am I on", "set up cccp on azure", "switch cccp to local-fs", "why can't cccp reach the hub". NOT for joining cells or messaging — use the `chat` skill for that.
argument-hint: [what you want to do with the backend]
allowed-tools: Bash
---

# CCCP Backend setup

## CCCP Backend Skill Goal

Respond to the user's prompt (the `User Arguments` defined at the end of this
document) by understanding the CCCP plugin's **data backend** system, so that
you are able to check the current backend, change to a different backend,
configure a new backend, reconfigure an existing backend, for the cccp plugin.

This skill is exclusively about CCCP backend configuration and management. If
the user wants to chat, join a cell, send a message, etc., point them at
`/cccp:chat` and stop.

## CCCP Backend Overview

A backend is the shared data store a cell lives in.

Every backend costs two separable things, and you should always work out which
one the user is actually asking for:

- **Joining** a cell means acquiring some values and putting them in config.
  Cheap, no infrastructure, nothing to operate. You can do this for the user.
- **Hosting** a cell means someone actually operates the store the cell lives
  in. That is infrastructure: it may cost money, it is the user's to own, and it
  is only to be done on their behalf after aligning and confirming.

A user who says "set up cccp on azure" may mean either. **Ask which**, unless
it is obvious. Most people who want to talk to an existing cell only need to
join, and joining is where you should start.

| Backend | Description | Requirements to Join a Cell | Requirements to Host a Cell |
|---|---|---|---|
| `local-fs` | Files under the plugin data dir. The zero-setup default; always works, but reaches only the same host **and** same OS user — terminal tabs, IDE windows, git worktrees, background agents. Cannot reach another user or machine. | None | None — no hosting |
| `azure-blob` | Centralized cloud storage (Azure Blob), reachable from any host, user, or network. Low cost. Auth is a shared container-scoped SAS token. | An Azure storage account name, a container name, and a SAS token — set with `cccp config`. | Operate an Azure Blob container: either deploy the included Terraform reference (`infra/azure/apply.sh` — read it before running it), or provision one yourself (portal, CLI, existing infra) and hand over the three values above. Needs an Azure subscription and may spend the user's money. |

## How to See the Config

| Question | Command | Notes |
|---|---|---|
| Which backend am I on? | `cccp backend` | Prints the bare name. No network. |
| What is my whole config? | `cccp config` | The full resolved dump: globals, then every backend, `[active]`/`[inactive]`. |
| Does a backend work? | `cccp backend check [<name>]` | Hits the network. Prints setup guidance on failure. |

Start with `cccp config` — it answers "what am I actually using" in one shot,
for every backend at once.

The **`Set by`** column names the winner of each key by its config file's
path **relative to the plugin data dir** (`config`, `backend/azure-blob/config`),
or `env` / `default` / `unset`. Combine `CCCP_PLUGIN_DATA` with that path and
you are at the literal file. Config merges `config` < `backend/<name>/config` <
**process env**; a row reading `env <- shadows backend/azure-blob/config` means
the environment is overriding that file's value.

`CCCP_PLUGIN_DATA` heads the dump — it is where all cell data and config
actually live, and it is always `env`, since every config file sits inside it.

Every backend appears in the dump, tagged `[active]` or `[inactive]` — an
inactive backend keeps its stored config, which is the whole setup flow:
configure it while inactive, `cccp backend use` it when ready.

The roster of available backends is the table at the top
of this skill. Don't ask the CLI for it.

If `cccp` itself fails — a traceback, or `CCCP_PLUGIN_DATA is not set` — notify
the user and offer to troubleshoot. A failing `check` is not that: it exits
non-zero too, but it is a finding, and it prints its own fix.

## How to Set Config Values

`cccp config KEY=VALUE ...` writes; keys are automatically routed to the proper
file (`CCCP_AZURE_BLOB_*` to `backend/azure-blob/config`, globals like
`CCCP_DEBUG` to `config`), and the confirmation names the file it touched. Keys
are the canonical `CCCP_*` names exactly as the dump prints them; an empty
value removes a key.

```bash
cccp config                                             # read everything
cccp config CCCP_AZURE_BLOB_ACCOUNT=hub CCCP_AZURE_BLOB_CONTAINER=cells
```

Two keys refuse to be set here, each pointing at the right tool:
`CCCP_ACTIVE_BACKEND` (use `cccp backend use <name>`, which validates before
switching) and `CCCP_PLUGIN_DATA` (environment-only; the plugin's SessionStart
hook exports it).

Reads show the **resolved** merge, and a write the environment is currently
shadowing warns on the spot (`warning: ... shadows this write`) — so a write
can never silently succeed-and-be-ignored.

Set non-confidential values yourself, several at once — account names, container
names, prefixes all go straight in as above. Secrets do not.

## How to Set a Secret

A SAS token, a key, a password: **you cannot set these, and must not try.**

- **You cannot read the user's keyboard.** Commands you run do not share the
  user's stdin. `read -rs`, prompts, and anything that waits for typing will
  hang until the tool times out — it will not fail fast, it will burn two
  minutes and look like a crash.
- **You must not receive the secret at all.** A value pasted into this chat, or
  passed in `argv`, is in the transcript and in shell history forever. Do not
  ask for it.

So hand the job to the user, in a terminal you are not in. Give them all four of
these, in this order:

**1. What and why.** One or two lines: they are about to paste a SAS straight
into cccp, and they are doing it rather than you because a secret you can see is
a secret in the transcript.

**2. How to get a shell.** Name your best guess and commit to it — a new tab
(`Cmd-T` on macOS Terminal/iTerm, `Ctrl-Shift-T` on most Linux terminals), a new
tmux window (`prefix c`), or another terminal window. Guess from their OS
(`uname`) and what you have seen of their setup. Being wrong is cheap; being
vague makes them do the thinking.

**3. One copy-pastable command.** That shell has none of this session's
environment, so build it complete:

- prepend every `CCCP_*` var it needs — at minimum `CCCP_PLUGIN_DATA=<value>`,
  since cccp refuses to guess a data directory and will otherwise just error
- use the **absolute path** to the cccp binary; bare `cccp` is on `$PATH` only
  inside a Claude session
- end with `<KEY>=-`, so the value arrives on stdin and never touches `argv`

Read the real values first (`echo "$CCCP_PLUGIN_DATA"`, `command -v cccp`) and
substitute them — never hand over a command with placeholders in it:

```bash
CCCP_PLUGIN_DATA=/home/u/.claude/plugins/data/cccp-inline \
  /home/u/.claude/plugins/cache/cccp/cccp/3.0.0/bin/cccp \
  config CCCP_AZURE_BLOB_SAS=-
```

**4. How to paste and end input**, for their OS:

- **Paste:** `Cmd-V` (macOS), `Ctrl-Shift-V` (most Linux terminals), `Ctrl-V` or
  right-click (Windows Terminal).
- **Then press Enter, then `Ctrl-D`.** Both, in that order. `Ctrl-D` only means
  end-of-input at the start of an empty line: pressed right after the pasted
  text it merely flushes that text and nothing happens, so without the Enter
  first they need it twice and will think it has hung. (Windows `cmd` or
  PowerShell: `Ctrl-Z` then Enter.)

The paste is visible in their terminal — that is their scrollback, not this
transcript, which is the entire point.

Then have them tell you it is done, and verify it yourself. The value is theirs;
the checking is yours:

```bash
cccp config                        # SAS should read <set, N chars>
cccp backend check azure-blob
```

Never echo a secret back, and never `cat` a config file — `cccp config`
redacts secrets precisely so you never have to hold one.

## How to Test and Change Backends

`check` validates any backend over the network **without** switching to it; `use`
validates and only then persists. Neither will ever leave the user pointed at a
broken store, and cccp never silently falls back to `local-fs`.

```bash
cccp backend check azure-blob    # test without committing
cccp backend use azure-blob      # switch (refuses if not ready)
```

When a check fails, `cccp backend check` prints backend-specific setup guidance;
follow it rather than guessing. To go deeper than these verbs, read `bin/cccp` —
one stdlib-only file, and the only authority on how backends resolve.

## Your instructions

The next paragraph begins `User Arguments:` then appends the user's prompt.
If defined, respond to the User Arguments; if empty, run `cccp config`
and report what you find.

User Arguments: $ARGUMENTS
