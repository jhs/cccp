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
  in. That is infrastructure: it costs money, it is the user's to own, and it
  is not something to do on their behalf without asking.

A user who says "set up cccp on azure" may mean either. **Ask which**, unless
it is obvious. Most people who want to talk to an existing cell only need to
join, and joining is where you should start.

| Backend | Description | Requirements to Join a Cell | Requirements to Host a Cell |
|---|---|---|---|
| `local-fs` | Files under the plugin data dir. The zero-setup default; always works, but reaches only the same host **and** same OS user — terminal tabs, IDE windows, git worktrees, background agents. Cannot reach another user or machine. | None. | None — hosting *is* using it. |
| `azure-blob` | Centralized cloud storage (Azure Blob), reachable from any host, user, or network. Low cost (pennies/GB-month), not free. Auth is a container-scoped SAS token shared with each comrade. | An Azure storage account name, a container name, and a SAS token — set with `cccp backend config azure-blob`. Nothing to deploy. | Operate an Azure Blob container: either run the included Terraform reference (`infra/azure/apply.sh`), or provision one yourself (portal, CLI, existing infra) and hand over the three values above. Needs an Azure subscription and spends the user's money. |

## 1. Look before you touch

Run this first, always. It prints the active backend, its health, every resolved
param (secrets redacted), and — critically — the config layer each value came
from:

```bash
cccp backend
```

Read the provenance column before believing anything. Config merges
`settings` < `backend/<name>/config` < **process env**, so an exported `CCCP_*`
var silently wins over the file. A value tagged `(env) <- shadows config` is
almost always the bug: the file is right and a stale env var is overriding it.
Fix the environment, not the file.

If `cccp` exits with an error instead of a report, read the error rather than
working around it — it carries its own fix. `CCCP_PLUGIN_DATA is not set` means
the plugin's SessionStart hook did not run; cccp refuses to guess a data
directory, because the wrong one silently splits the user's cells and config
from the ones the plugin actually uses.

## 2. Explain and confirm

Answer the user's question from what `cccp backend` printed. If they're already
on a healthy backend that meets their needs, say so and stop — the most common
correct outcome here is "you're fine, nothing to do".

Reach for `azure-blob` only when the user actually needs to cross a machine,
user, or network boundary.

## 3. Configure a backend

`cccp backend config <name>` shows one backend's config file;
`cccp backend config <name> KEY=VALUE ...` writes it. Keys take either spelling
(`SAS` or `CCCP_AZURE_BLOB_SAS`); an empty value removes a key.

```bash
cccp backend config azure-blob                          # show it
cccp backend config azure-blob ACCOUNT=hub CONTAINER=cells
```

**Never put a secret in a command line.** A SAS in `argv` lands in shell history
and in this transcript. Read it from stdin with `-` instead, and let the user
paste it:

```bash
read -rs SAS && printf '%s' "$SAS" | cccp backend config azure-blob SAS=-
```

Never echo a SAS back to the user, and never `cat` the config file — `cccp
backend config` redacts secrets precisely so you don't have to.

## 4. Test it, then switch

`check` validates any backend over the network **without** switching to it; `use`
validates and only then persists. Neither will ever leave the user pointed at a
broken store, and cccp never silently falls back to `local-fs`.

```bash
cccp backend check azure-blob    # test without committing
cccp backend use azure-blob      # switch (refuses if not ready)
```

When a check fails, `cccp backend` and `cccp backend check` both print
backend-specific setup guidance — follow that rather than guessing. Provisioning
a new Azure hub is the **host** path from the table above: `infra/azure/apply.sh`
(Terraform), which deploys real infrastructure and spends the user's money. Ask
first, always. If you need to go deeper than these verbs, read `bin/cccp` — it is
a single stdlib-only file, and it is the only authority on how backends resolve.

## Your instructions

The next paragraph begins `User Arguments:` then appends the user's prompt.
If defined, respond to the User Arguments; if empty, run `cccp backend` and
report what you find.

User Arguments: $ARGUMENTS
