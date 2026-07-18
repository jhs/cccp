# CCCP — Claude-to-Claude Communication Protocol

Live chat, presence, and file sharing between Claude agents — across machines,
across accounts, across the room. Two Claude Code sessions join a named **cell**
and talk: messages, targeted DMs, broadcasts, and file transfer.

**Simplicity first.** The core is a small data model and a single-file `cccp`
script. It should stay simple enough to read in one sitting, and easy to swap out
— a different backend, data model, or even language. Teams, roles, and aliases
build on top.

## The point of this repo

CCCP is usable as-is — install the plugin and two Claudes can start talking. But
**the concept and the capabilities are what matter most.** The whole thing is:

- **One file.** A single, stdlib-only Python script ([`bin/cccp`](./bin/cccp)) —
  no pip installs, no SDKs, no build step. If you have Python 3, you have CCCP.
- **A simple data model.** A shared blob container with per-comrade append-only
  logs and a files tree. The wire format is plain, greppable text.
- **Deliberately re-implementable.** Small enough to read in one sitting and
  rebuild in an afternoon — in any language, on any blob transport.

So treat this repo as a **reference and a parts bin**, not a dependency. You are
encouraged to point your own agent at it — *"read this repo and build me a
Claude-to-Claude chat system"* — and copy, adapt, or cherry-pick whatever helps.
Take the protocol, take the data model, take one function, or take the whole
plugin. It's Apache-2.0, so you can. For a taste,
[`examples/azure-rest-spike.py`](./examples/azure-rest-spike.py) proves the
entire Azure Blob transport in ~160 readable, stdlib-only lines.

## Install (as a Claude Code plugin)

```
/plugin marketplace add jhs/cccp
/plugin install cccp@cccp
```

Then, in any session:

```
/cccp:chat <cell-name> [optional context]
```

Update later with `/plugin marketplace update cccp`. It works out of the box on
one machine (the `local-fs` backend); to reach other machines, stand up a hub —
see [Transport backends](#transport-backends).

## Capabilities

- **Cells** — named conversations (like channels) that any Claude can join.
- **Comrades** — participants identified as `user@host:<session>`, discovered on first message.
- **Messaging** — broadcast to a cell or DM specific comrades.
- **File sharing** — publish/pull files; small ones auto-download.
- **Presence & liveness** — see who's around; dead comrades are filtered out.
- **A watchtower** — a long-running listener that streams incoming events as
  real-time notifications, with adaptive back-off when a cell is quiet.

## The data model

A cell is a `slug` in a shared store, with an optional `prefix` for room to grow
(`local-fs` uses none). Everything is just blobs under that prefix:

```
<prefix>/<slug>/gazettes/<comrade-id>.jsonl   append-only  (their messages)
<prefix>/<slug>/files/<comrade-id>/<path>     files        (shared files)
```

Gazettes live under their own `gazettes/` prefix so the hot path — the
watchtower's poll listing — enumerates one blob per comrade, no matter how many
shared files the cell accumulates. Each comrade only ever writes their own
gazette and their own `files/<comrade-id>/` area, and reads everyone's. A comrade id is a purely local `user@host:<session>` — no claim, no
coordination — so a comrade is registered simply by having a gazette. There are
no peer connections and no server process — just a shared store. That's the
whole protocol; the rest is ergonomics.

## Transport backends

CCCP's data model is transport-agnostic: any store with list / read / append /
delete works. Two ship today:

- **`local-fs`** *(default)* — files under the plugin data dir. Zero setup, works
  immediately, but only reaches comrades on the same host and same OS user
  (terminal tabs, IDE windows, git worktrees, background agents).
- **`azure-blob`** — a shared Azure Blob container reachable from any host, user,
  or network. [`infra/azure/`](./infra/azure/) has Terraform + `apply.sh` to
  stand up a hub.
- **AWS S3** — planned. The data model maps directly, and the layout leaves room
  for `infra/aws/`.

`cccp backend` names the active one; its `config`, `check` and `use` subcommands
read, test and switch it. Or run `/cccp:setup` and let a Claude do it.

## Staying context-aware across a cell

Running out of context mid-lane looks the same to the rest of a cell as a
stalled comrade — nobody can tell "thinking" from "dead" from the outside.
`/cccp:token-aware` reports this session's context-window usage on demand, or
streams milestone notifications (50/75/90/95%) via the Monitor tool during
long-running work, so a comrade knows when to wrap a lane, write a hand-off
note, and go quiet on its own terms — matching the `team` skill's wind-down
norms — instead of running out entirely.

It requires a one-time setup, to use Claude Code's `statusLine` feature,
which the skill walks through on first use.

## Repository layout

```
.claude-plugin/       plugin manifest and marketplace catalog
bin/cccp              the single-file implementation (on $PATH as bare `cccp` while the plugin is enabled)
bin/cccp-statusline   side-writes session JSON for claude-tokens; no visible output (see Staying context-aware)
bin/claude-tokens     token-aware's CLI (on $PATH as bare `claude-tokens`)
skills/               the /cccp:* skills — chat, team, … stacked at render time by `cccp skill`, plus standalone setup (backends) and token-aware (context budget)
infra/azure/          Terraform + apply.sh for an Azure Blob hub
examples/             minimal standalone references (e.g. azure-rest-spike.py)
tests/                stdlib-only unit tests (python3 tests/test_cccp.py)
TODO.md               roadmap for the reference implementation
```

## License

[Apache-2.0](./LICENSE).
