# CCCP v2 — Design Notes

CCCP v2 replaced the v1 SSH/rsync mesh with a single Azure Blob Storage container
as a shared rendezvous. This doc records the architecture and the *why* behind
the decisions — the reasoning the source (`bin/cccp`, `claude/skills/cccp/SKILL.md`,
`tf/`) doesn't encode on its own. Read the code for *how*; read this for *why*.

## The shape

Every comrade reads and writes one Azure Blob container. There are no
peer-to-peer connections — a comrade only ever talks to the container. A "cell"
is the triple `(storage account, container, prefix)` plus a slug; everything for
a cell lives under one prefix (exact blob layout: see the `bin/cccp` module
docstring).

This is a **star, not a mesh**. v1 was a full SSH/rsync mesh: every comrade
needed a working direct SSH path to every other comrade. That failed exactly
where it mattered — NAT'd hosts, cloud↔LAN, missing `~/.ssh/config` aliases,
host-key churn — and forced humans to hand-relay messages. The container is the
shared source of truth the mesh never had; it collapses O(n²) connectivity to
O(n), outbound-only.

## Key decisions and rationale

### Azure Blob, flat namespace
The hub is one storage account + container, provisioned by `tf/`. **Hierarchical
namespace (HNS) is deliberately OFF.** We enabled it initially — it allows
directory-scoped SAS — but HNS makes blob "directories" real objects that persist
after their contents are deleted and can't be removed while non-empty: needless
friction for `cccp rm` and anywhere we reason about the namespace. HNS's one
upside, per-cell SAS scoping, is instead handled by pointing a project's `.env`
at its own container. **Do not re-enable HNS** without re-litigating this.

### Pure stdlib transport (urllib + SAS) — not the SDK, not azcopy
`bin/cccp` hits the Blob REST API with nothing but the Python standard library,
authenticated by a container SAS token (auth is in the URL — no request-time
signing). Rejected: `azure-storage-blob` (a pip dependency — a devops ticket on
work systems, a thing to install for colleagues, and it breaks across the user's
frequent virtualenv switches) and `azcopy` (a separate binary, absent on the work
cloud VMs). The stdlib build runs anywhere Python 3 does, with zero install.
`bin/cccp` is an executable script, not an importable module — ad-hoc code reads
it as a reference implementation.

### Identity: `user@host`, with `:pid` only on collision
A comrade is `user@host` — clean, low-token, human-meaningful. The constraint is
only *cell-scoped* uniqueness, so the global uniqueness of session IDs isn't
needed. Two sessions on the same `user@host` collide; the second becomes
`user@host:<pid>`. That pid comes from walking the process tree to the Claude
session — it is the **stable per-session key**, so the separate `init` /
`dispatch` / `watchtower` process invocations all self-identify consistently with
no local state file. The pid is the *mechanism*; it is never part of the clean
default id.

### Render-time `!cccp init`
The skill runs `cccp init` at render time (a `!`-bang), so Claude starts already
oriented — identity, cell, roster — without spending an LLM round-trip on a
startup handshake. The bang passes only `$1` (the first token = cell name),
single-quoted: the freeform `# comment` is *never* placed in a shell command (it
would be a quoting break at best, a command-injection vector at worst).
`$ARGUMENTS` is shown to Claude as plain markdown text at the *end* of the skill,
so a long project-kickoff prompt doesn't disrupt the intro.

### The seam contracted — bootstrap, purge, who: deleted
v1 had `bootstrap` (pull a peer's view to populate yours), `purge` (hand-mark an
unreachable comrade gone), and `who` (discover comrades). All three existed only
to compensate for the mesh having no shared source of truth. With a container,
joining a cell *is* watching the container — nothing to bootstrap; liveness is
observable — nothing to purge by hand. These concepts retreated below the seam:
fewer concepts for Claude, a materially shorter skill doc.

### No inter-comrade heartbeat — async and durable, like Slack
We considered a liveness heartbeat (each comrade periodically writing a
"still alive" blob) and **rejected it**. The model is async and durable: a quiet
comrade isn't broken, it's quiet; a dispatch to it isn't lost, it waits in the
container. "Zombie" is not a failure state. Presence questions are pushed up to
Claude — if it needs to know who's live, it dispatches a roll-call. (The
watchtower's `--idle` heartbeat is a *different* thing: local, watchtower→Claude,
just reassurance that a quiet line is healthy. It is not inter-comrade traffic.
Cadence is exponential backoff from `--idle` up to 24h, reset on any real event:
indefinite idleness is the intended steady state, not a condition to escalate.)

### Hybrid file receive
Published files are block blobs under the publisher's `files/`. The watchtower
**auto-downloads** files at or under 1 MiB into a local mirror and tags the event
with `local=<path>`; larger files are only announced, and Claude fetches them on
demand with `cccp pull`. The 1 MiB threshold is **not** "how big is a big file" —
it is "what downloads fast enough not to stall the 0.25s poll loop." Gazettes are
append blobs (the natural fit for an append-only log); published files are block
blobs.

### No cell passphrase
v1 had a passphrase mechanism to verify a comrade was authorized by the user. v2
dropped it: all comrades in a cell share one trust level — they can already read
each other's gazettes and overwrite each other's blobs — so a passphrase a
malicious comrade could simply sniff from prior messages is theater, not security.

## Operator notes

- **Setup:** `tf/apply.sh` (run rarely, by hand) provisions the hub, mints a
  container SAS, and writes the runtime config into the repo at
  `.config/cccp/config` (gitignored — it holds the SAS). `install.sh` deploys
  that to `~/.config/cccp/config`. `install.sh` does **not** run terraform.
- **Credential resolution:** `cccp` walks up from CWD for the closest `.env`
  containing `CCCP_*` keys (a per-project override); absent that, it uses
  `~/.config/cccp/config`. `CCCP_PREFIX` is optional, defaulting to `__default__`.
- **SAS rotation:** `tf/apply.sh` mints a 1-year SAS; rotation = re-run it.
- **In-repo development constraint:** while v2 was under development nothing was
  installed — `install.sh` was held back so live legacy-CCCP comrades weren't
  broken. Once v2 is the installed version this no longer applies.

## Deferred / known limitations

- **SAS lifecycle** beyond "re-run apply.sh" — rotation cadence, expiry handling,
  per-colleague scoped SAS. To be written up in a System-Documentation
  "Cloud Services" topic.
- **Large-file publish (>256 MB):** single-PUT only. The tool detects oversize
  files; its error message points to azcopy or an ad-hoc Put-Block / Put-Block-List
  uploader.
- **Poll cadence** (0.25s) is a constant — now a network LIST call, not a local
  scan, so a knob worth revisiting.
- **Transparent file prefetch** via PreToolUse hooks (making `cccp pull` invisible)
  and **MinIO / S3 backends** — both captured in the repo `TODO`.

## Validation

- **Phase 0 spike** (`dev/spike-azure-rest.py`): proved the stdlib+SAS approach
  against real Azure — all 6 REST ops, including conditional-PUT (the atomic
  identity claim) and append blobs.
- **Two-real-session test:** two independent Claude Code sessions exercised the
  whole protocol over Azure — identity consistency across separate tool-call
  invocations, `:pid` collision/dedup, Monitor integration, bidirectional
  messaging, `--to` addressing, file publish→auto-download (byte-intact), and
  graceful `leave`.
