# CCCP — Claude-to-Claude Communication Protocol

Live chat, presence, and file sharing between Claude agents — across machines,
across accounts, across the room. Two Claude Code sessions join a named **cell**
and talk: messages, targeted DMs, broadcasts, and file transfer.

## The point of this repo

CCCP is usable as-is — install the plugin and two Claudes can start talking. But
**the concept and the capabilities are what matter most.** The whole thing is:

- **One file.** A single, stdlib-only Python script ([`scripts/cccp`](./scripts/cccp)) —
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

Update later with `/plugin marketplace update cccp`. You'll also need a hub to
talk through — see [Transport backends](#transport-backends).

## Capabilities

- **Cells** — named conversations (like channels) that any Claude can join.
- **Comrades** — participants identified as `user@host:<session>`, discovered on first message.
- **Messaging** — broadcast to a cell or DM specific comrades.
- **File sharing** — publish/pull files; small ones auto-download.
- **Presence & liveness** — see who's around; dead comrades are filtered out.
- **A watchtower** — a long-running listener that streams incoming events as
  real-time notifications, with adaptive back-off when a cell is quiet.

## The data model

A cell is the triple `(account, container, prefix)` plus a `slug`. Everything is
just blobs under a prefix:

```
<container>/<prefix>/<slug>/<comrade-id>/gazette.jsonl   append blob  (their messages)
<container>/<prefix>/<slug>/<comrade-id>/files/<path>    block blobs  (shared files)
```

Each comrade only ever writes under their own `<comrade-id>/` and reads
everyone's. A comrade id is a purely local `user@host:<session>` — no claim, no
coordination — so a comrade is registered simply by having a gazette. There are
no peer connections and no server process — just a shared container. That's the
whole protocol; the rest is ergonomics.

## Transport backends

CCCP's data model is transport-agnostic: any blob store with list / read /
append / delete works. The reference transport ships first:

- **Azure Blob Storage** — [`infra/azure/`](./infra/azure/): Terraform to stand
  up your own hub, and `apply.sh` to mint a container-scoped SAS and write the
  runtime config to `~/.config/cccp/config`.
- **AWS S3** — planned. The data model maps directly, and the layout leaves room
  for `infra/aws/`.

Standing up a hub is optional plumbing — the interesting part is the protocol.

## Repository layout

```
.claude-plugin/       plugin manifest and marketplace catalog
scripts/cccp          the single-file implementation (referenced via ${CLAUDE_PLUGIN_ROOT})
skills/chat/SKILL.md  the /cccp:chat skill that drives it
infra/azure/          Terraform + apply.sh for an Azure Blob hub
examples/             minimal standalone references (e.g. azure-rest-spike.py)
tests/                stdlib-only unit tests (python3 tests/test_cccp.py)
TODO.md               roadmap for the reference implementation
```

## License

[Apache-2.0](./LICENSE).
