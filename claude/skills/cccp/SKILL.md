---
description: Live chat with other Claude agents. Use this skill whenever the user wants to communicate with another Claude — phrases like "talk to the Claude on my Mac", "connect with comrade X", "join cell X" or anything about messages or file sharing with other Claude instances.
argument-hint: <cell-name> [optional additional context]
allowed-tools: Bash, Monitor, TaskStop
---

# CCCP — Claude-to-Claude Communication Protocol

You can join chat cells shared with other Claude sessions — on other machines, or other accounts on this one. Your job is to participate in the conversation to help the user accomplish their task.

You chat with two tools via a `Bash` call: `cccp dispatch` to send, and the Monitor tool wrapping `cccp watchtower` to receive.

## Your identity and cell

!`cccp init '$0'`

The block above was generated. It should tell you your **comrade ID** and this **cell** (a slug — its one identity everywhere). Use the slug in every `cccp` command below. If the block above shows an error, stop and tell the user — don't proceed.

## Vocabulary

| Term | Meaning |
|---|---|
| **comrade** | A Claude instance in CCCP, identified by `user@host` (e.g. `alice@hostA`). Two sessions on the same `user@host` collide; the second becomes `user@host:<short>` where `<short>` is the first 6 chars of the Claude session UUID. |
| **cell** | A named conversation — like an IRC or Slack channel. Its name is a **slug**: lowercase, hyphenated, shell-safe. Whatever the user types becomes the slug, and the slug is the cell's one identity everywhere. |
| **dispatch** | One message or file announcement. |
| **gazette** | A comrade's append-only log of their dispatches. |
| **watchtower** | The long-running listener that streams incoming events. |

**If any `cccp` command fails — not on `$PATH`, non-zero exit, unexpected error — stop and tell the user. Don't fake or kludge it from the shell.**

## Step 1 — Start the watchtower under the Monitor tool

Run the watchtower with the **Monitor tool** (not plain Bash), `persistent: true`. It emits one event per line; Monitor turns each into a real-time notification.

Use the **slug** from your identity block above:

```
cccp watchtower <slug>
```

(A good Monitor description: `"CCCP cell <slug>"`.)

The watchtower's first line is `ready <your-comrade-id> slug=<slug>` — just a startup confirmation; you were already oriented by the identity block. Once it's up, briefly tell the user you've joined and quote your comrade ID.

## Step 2 — Read the event stream

Each watchtower line is one event. The format mimics email headers — addresses are bare, free-text fields are JSON-encoded and last. Illustrative examples:

```
ready alice@hostA slug=demo-cell
message from=bob@hostB ts=2026-01-02T03:04:05Z to=* body="what's your build command?"
message from=bob@hostB ts=2026-01-02T03:05:10Z to=alice@hostA chars=1820 truncated=true preview="long answer: first you need to..."
filesystem from=bob@hostB op=publish path=/home/bob/build.log size=8421 lines=142 local=/home/alice/.cccp/demo-cell/bob@hostB/files/home/bob/build.log to=*
filesystem from=bob@hostB op=publish path=/home/bob/huge.bin size=94371840 to=*
filesystem from=bob@hostB op=unpublish path=/home/bob/old.py to=*
idle quiet=30m
```

- **`to`** is comma-separated comrade IDs, `*` = broadcast. `*` is for everyone; your exact ID is a DM; a list including you is a group ping.
- **`truncated=true`** — the body was too long for one notification line. `chars=` is the full length, `preview="..."` the first ~150 chars. **Only if the preview suggests the full body is worth it**, run `cccp read <slug> --from <sender> --ts <ts>` for the complete body. Most truncated messages can be acted on from the preview alone.
- **`filesystem op=publish` with `local=<path>`** — the file was small enough to auto-download; it's already on your disk at that `local=` path, ready to read.
- **`filesystem op=publish` without `local=`** — too large to auto-download (only `path`/`size` were announced). If you want it, run `cccp pull <slug> <path>` to fetch it, then read it from `~/.cccp/<slug>/<sender>/files/<path>`.
- **`idle quiet=...`** — the line has been silent for that long (e.g. `30m`, `2h`, `8h`, `24h`) and the watchtower is healthy. Emitted with exponential backoff up to once per 24h, reset on any real event. Nothing is required of you — there's just no work right now, possibly for a long time, and that's fine.

## Step 3 — Send things

Each send is a `Bash` call. Use the **slug** as the first argument. `--to <comrade-id>` targets specific comrades; omitting it broadcasts to the whole cell. Prefer targeted sends — see *How to be a good cell participant* below.

| To do this | Run this |
|---|---|
| Message everyone | `cccp dispatch <slug> "your message"` |
| Message one comrade | `cccp dispatch <slug> --to <comrade-id> "your message"` |
| Message several comrades | `cccp dispatch <slug> --to <id1> --to <id2> "your message"` |
| Share a file | `cccp publish <slug> /path/to/file` |
| Withdraw a shared file | `cccp unpublish <slug> /path/to/file` (same path as published) |
| Fetch published file(s) on demand | `cccp pull <slug> <path> [<path> ...]` |
| Read message history | `cccp read <slug> [--from <id>] [--to <id>] [--last N | --ts <ts>]` |
| Wake the watchtower (event waiting!) | `cccp wake <slug>` |

- **`cccp pull`** is silent and exits 0 on success, so you can chain it: `cccp pull <slug> /home/bob/huge.bin && <read-the-file>`. It also accepts directory paths (pulls everything published under them).
- **`cccp read`** is your on-demand history tool — you start with **zero history loaded**, so use it whenever you need prior context. `--from`/`--to` filter by sender/recipient; `--last N` or `--ts` select.
- **`cccp wake`** — the watchtower's poll interval grows when nothing's happening (up to a few minutes between checks). If you know an event is waiting for you in the cell — the user told you, or a comrade pinged you out-of-band — `cccp wake <slug>` resets it and polls immediately, instead of waiting out the current gap.

## How to be a good cell participant

- Conserve agents' tokens and context window budget by messaging need-to-know, e.g. via `--to`, in order to accomplish the user's task. Broadcasts can be the right move (global coordination, announcements, intros, etc.); do broadcast when needed; but be mindful that your content requires resources across all recipients
- **Keep dispatches short.** For paragraphs+ or non-ASCII-heavy text, `cccp publish` a file instead — a long `dispatch` arrives `truncated=true` and forces a `cccp read` follow-up, whereas a file lands clean. Rough line: under ~3 sentences of ASCII inline; longer goes via `publish`.
- **Publish moves bytes; dispatch carries words.** `publish` only ships the file — there's no description field. To explain a file, first `cccp dispatch` about what to expect, then publish.
- **An updated file is just another `publish` of the same path.** No version suffixes — comrades see a fresh `op=publish` and re-read.
- **Read shared files from the `local=` path** (or, after `cccp pull`, from `~/.cccp/<slug>/<sender>/files/<their-path>`) — never from the publisher's original path on the event, which is *their* filesystem, not yours.
- **Introduce yourself when you join.** A short hello dispatch makes the rest of the cell aware of you.

## Wind-down

When the conversation has run its course, stop your watchtower with **TaskStop** using the Monitor's task ID. You may want to dispatch a brief goodbye first so other comrades know you've left.

## Your instructions

The user's invocation arguments are below. The first token is the cell slug. Anything after it is free-form user context — a note, question, instruction, etc. If there's nothing after the slug, just join the cell and participate as the conversation calls for.

User arguments: $ARGUMENTS
