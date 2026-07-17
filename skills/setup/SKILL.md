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
| `azure-blob` | Centralized cloud storage (Azure Blob), reachable from any host, user, or network. Low cost. Auth is a shared container-scoped SAS token. | An Azure storage account name, a container name, and a SAS token — set with `cccp backend config azure-blob`. | Operate an Azure Blob container: either deploy the included Terraform reference (`infra/azure/apply.sh` — read it before running it), or provision one yourself (portal, CLI, existing infra) and hand over the three values above. Needs an Azure subscription and may spend the user's money. |

## How to See Backend Settings

| Question | Command | Notes |
|---|---|---|
| Which backend am I on? | `cccp backend` | Prints the bare name. No network. |
| What is its config? | `cccp backend config [<name>]` | Resolved values + where each came from. Defaults to the active backend. |
| Does it work? | `cccp backend check [<name>]` | Hits the network. Prints setup guidance on failure. |

Start with `cccp backend config` — it answers "what am I actually using" in one
shot.

The **`Set by`** column in `cccp backend config` output names the config
layer each value actually came from. Config merges `settings` <
`backend/<name>/config` < **process env**. A row reading `env <- shadows config` means
the environment variable is overriding a config file value.

`CCCP_PLUGIN_DATA` heads the table on every backend — it is where all cell data
and config actually live, and it is always `env`, since every config file sits
inside it.

`cccp backend config <name>` works for a backend you are **not** on, and its
values look identical to the active one's — so check the `[active]` /
`[not active; active is ...]` marker in the header. Configuring `azure-blob`
while `local-fs` is active is a real thing to do (it is the whole setup flow),
but so is doing it by accident and wondering why nothing changed.

The roster of available backends is the table at the top
of this skill. Don't ask the CLI for it.

If `cccp` itself fails — a traceback, or `CCCP_PLUGIN_DATA is not set` — notify
the user and offer to troubleshoot. A failing `check` is not that: it exits
non-zero too, but it is a finding, and it prints its own fix.

## How to Configure a Backend

`cccp backend config <name> KEY=VALUE ...` writes config; the same command with
no assignments reads it back. Keys take either spelling (`SAS` or
`CCCP_AZURE_BLOB_SAS`); an empty value removes a key.

```bash
cccp backend config azure-blob                          # read it
cccp backend config azure-blob ACCOUNT=hub CONTAINER=cells
```

Writes always land in that backend's config file, but reads show the **resolved**
merge — so a value you just wrote can come back tagged `env`, meaning the
environment is overriding what you wrote, revealed by the `Set by` column:
the write succeeded and is still being ignored.

**Never put a secret in a command line.** A SAS in `argv` lands in shell history
and in this transcript. Read it from stdin with `-` instead, and let the user
paste it:

```bash
read -rs SAS && printf '%s' "$SAS" | cccp backend config azure-blob SAS=-
```

Never echo a SAS back to the user, and never `cat` the config file — `cccp
backend config` redacts secrets precisely so you don't have to.

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
If defined, respond to the User Arguments; if empty, run `cccp backend config`
and report what you find.

User Arguments: $ARGUMENTS
