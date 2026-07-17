# CCCP data backends

The chat data model is transport-agnostic: a cell is just blobs under a prefix,
and any store with **list / read / append / delete** can host one. This document
is the design contract for making the backend pluggable, adding a zero-setup
`local-fs` default, and reorganizing the plugin data directory. It is the
reference the implementation checks against.

## Backends

| Name | Reach | Setup |
|---|---|---|
| `local-fs` *(default)* | Same host + same OS user only | None |
| `azure-blob` | Any host, user, or network | Azure subscription + SAS |

- **`local-fs`** — Shared files under the plugin data dir (`$CCCP_PLUGIN_DATA`).
  Zero setup, works immediately, but only connects comrades on the **same host
  and same OS user**: multiple terminal tabs, IDE windows, git worktrees,
  background agents. Cannot reach other users or machines.
- **`azure-blob`** — Centralized cloud storage (Azure Blob) reachable from **any
  host, user, or network**. Low cost (pennies/GB-month), not free; needs an
  Azure subscription. Auth is a container-scoped SAS token shared with each
  comrade. Set up an existing hub via config, or provision one with
  `infra/azure/apply.sh` (Terraform).

## Plugin data directory

One namespace, `$CCCP_PLUGIN_DATA` (`~/.claude/plugins/data/cccp-CCCP` — version-
stable, survives plugin upgrades), split by **role** the way XDG / `/var` split
data from cache. The load-bearing line is `backend/` vs. everything else:

```
$CCCP_PLUGIN_DATA/
  settings                 # global cccp state, e.g. CCCP_ACTIVE_BACKEND=... (absent ⇒ local-fs)
  backend/
    local-fs/              # DATA (authoritative): <slug>/<comrade-id>/gazette.jsonl + files/
    azure-blob/
      config               # connection params (account/container/SAS) + any backend-local locks
  mirror/                  # CACHE: pulled files, aliases, per-cell debug + watchtower logs
  telemetry/
    claude-code/           # CACHE: <session>.json, auth-status.json  (per host tool; codex/ later)
```

- **`backend/local-fs/` is the only authoritative data in the tree** — it *is*
  the local cell's message log; deleting it loses messages permanently. This is
  the exception, not the rule.
- **`backend/azure-blob/` holds only the pointer + credentials** to cloud-hosted
  data. Deleting it costs a re-`apply.sh` or a re-shared SAS — annoying, not
  destructive. Same directory *role* as `local-fs/`, very different blast radius.
- **`mirror/` and `telemetry/` are caches** — reconstructible, per-host, safe to
  wipe. A future `cccp gc` can clear them and is structurally incapable of
  touching `backend/`.

Pidfiles/locks that coordinate one backend's tools live in `backend/<name>/`.
A cross-tool `run/` dir is deferred — no pressure for it yet.

## Config model

Config comes from just two sources: the **config files** in the tree (`settings`
and `backend/<name>/config`) and **process environment variables**. There is no
`.env` walk-up — per-project config is done the standard way, by exporting
`CCCP_*` vars (direnv, a shell profile, CI). All config is flat `KEY=value`
(dotenv syntax), and every key is **fully qualified and self-namespacing**, so a
setting's identity is its key, never its file — two backends' params coexist
without collision whether they sit in separate config files or in the
environment, and resolution is a **dumb flat-dict merge**.

**Key scheme**
- Globals: `CCCP_<KEY>` — `CCCP_ACTIVE_BACKEND`, `CCCP_DEBUG`.
- Backend-scoped: `CCCP_<BACKEND>_<KEY>` (name upcased, `-`→`_`) —
  `CCCP_AZURE_BLOB_ACCOUNT`, `CCCP_AZURE_BLOB_CONTAINER`, `CCCP_AZURE_BLOB_SAS`,
  `CCCP_AZURE_BLOB_PREFIX`. `local-fs` needs none today.
- A backend name may not collide with a global key stem (reserved-name check).

**`PREFIX` is backend-scoped, and in practice azure/S3-only.** It carves
namespace room inside a single flat shared container/bucket. `local-fs` gets that
isolation from its own root dir, so it exposes no prefix key (empty prefix, no
`__default__` folder). The path-builder tolerates an empty prefix. The mirror is
already prefix-less.

**Merge layers**, low → high precedence, per-key:

```
settings                          # globals (active backend, debug)
  → backend/<active>/config       # the active backend's params
    → process env CCCP_*          # highest (per-project via direnv, CI, ad-hoc)
```

Because it's a per-key merge, you can **keep the selector public and the secret in
the tree** — set `CCCP_ACTIVE_BACKEND=azure-blob` + `CCCP_AZURE_BLOB_CONTAINER` in
the environment while the SAS lives in `backend/azure-blob/config` (which sits
under `~/.claude/plugins/data/`, outside any repo).

**Resolution** — the active backend must resolve before its config file loads:

1. Read `CCCP_ACTIVE_BACKEND` from `settings` + process env (default `local-fs`).
2. Merge `settings` + `backend/<active>/config` + env, and pull out this
   backend's `CCCP_<active>_*` params.

`~/.config/cccp/*` and the `CONFIG_PATH` constant are retired.

## Selection & validation

- Active backend = resolved `CCCP_ACTIVE_BACKEND`, default `local-fs`. **Never
  inferred from stray credentials.**
- **Never silently downgrade.** If an explicitly selected backend fails
  validation (missing config or a failed health check), that is a hard error
  with setup guidance — cccp does not fall back to `local-fs`. The implicit
  `local-fs` default validates its data dir is writable; there is nothing below
  it to downgrade to, so no surprise is possible.

The four management verbs are the whole operator surface, and the `setup` skill
adds no capability of its own — it only drives these:

| Verb | Does |
|---|---|
| `cccp backend` | Active selection + health + description + resolved params (secrets redacted) with the config layer that won each, then the backend list. Setup guidance too, when the active one is not ready. |
| `cccp backend use <name>` | Validates, then writes `settings`. Refuses on failure. |
| `cccp backend check [<name>]` | Validates **any** backend over the network without switching to it. Exits non-zero when not ready. |
| `cccp backend config <name> [KEY=VALUE ...]` | Shows or writes `backend/<name>/config`. |

- **Params print with their provenance.** Each value is tagged with the layer that
  won it (`settings` / `config` / `env`, or `default` / `unset`), and a key set in
  more than one layer is flagged as shadowed. An exported `CCCP_*` silently
  outranking a config file is the failure mode the merge makes possible, so the
  status output names it rather than leaving it to be discovered.
- **Secrets are never printed** — only whether a param is set, and its length.
  `secrets` in the registry names them (`SAS` today), so `cccp backend` output is
  safe to paste into an issue. Config files are written `0600`.
- **`config` takes either key spelling** (`SAS` or `CCCP_AZURE_BLOB_SAS`) and
  refuses an unknown one — a typo'd key is invisible until the backend
  mysteriously fails to validate. A `VALUE` of `-` reads the value from stdin
  (the `cccp dispatch` idiom), keeping a SAS out of shell history and out of an
  agent's transcript; an empty `VALUE` removes the key.
- **`local-fs` has no config keys at all.** It is isolated by its own root dir
  rather than a prefix, which is what makes it the zero-setup default.

## Backend abstraction

The seam already exists as the verbs every higher-level function calls on its
`client`: `put_block`, `get`, `get_range`, `get_head`, `ensure_append_blob`,
`append_block`, `list`, `delete`. Implementation:

- `BlobClient` → `AzureBlobBackend` (same seven methods).
- Add `LocalFilesBackend` (append blob = `O_APPEND` write, `list` = dir walk,
  `get_range` = seek+read), rooted at `backend/local-fs/`.
- `make_backend(cfg)` factory replaces the seven `BlobClient(cfg[...])` sites.

## Dynamic skill content

The backend status is a template **variable**, `@@BACKEND@@`, substituted by
`render_skill_body` alongside `@@COMRADE_ID@@` — so a template drops it wherever it
reads best (the `chat` base puts it in a `## CCCP Data Backend` section). Its value
is `backend_status_block()`, computed once per render from the resolved config +
`CCCP_PLUGIN_DATA` (read from the environment, exported by the SessionStart hook).
Because every skill (`chat`, `team`, `foreman`, `foreman-with-tmux`) stacks the
`chat` base through `compose_skill`, one variable covers all four — no SKILL.md
edits. `backend_status_block()` is read-only and swallows any config error into a
helpful line, so skill rendering can never fail on it. Mirrors token-aware's
`data-setup` DONE/START split:

- **Healthy** (one line): `Current backend: \`local-fs\` — <summary>. To list all
  backends or switch, run \`cccp backend\`.` Its presence *is* the "set up
  correctly" signal.
- **Not ready**: the reason + backend-specific setup + a pointer to `cccp backend`
  (and to escalate to the user if unresolved).

Keep the healthy line to one line; expand only when broken. While here, the args
outro is no longer a special case either — it renders as an **implied final part**
of every stack, through the same `render_skill_body` substitution as the body
templates.

## The `setup` skill

`@@BACKEND@@` and the `setup` skill are the **reactive and proactive halves of the
same job**, not an overlap. `@@BACKEND@@` catches you mid-`chat` when the store is
already broken; `/cccp:setup` is where you land when you want to inspect or change
a backend *before* joining anything — in practice, the `local-fs` → `azure-blob`
move. Both point at the same `cccp backend`.

It is deliberately **not** in `SKILL_STACK`. Every entry there stacks the `chat`
base, which would drag in cells, comrades, and the watchtower — the exact opposite
of a skill whose only job is the backend. So it is a standalone static `SKILL.md`,
shaped like `token-aware` rather than `chat`, and it carries **no `!`-include**: a
render-time `cccp backend` would fire the network healthcheck behind a 30s urlopen
timeout and block skill render. It tells Claude to run `cccp backend` as its first
action instead, which costs one turn and cannot hang a render.

The skill holds no backend knowledge of its own — it only knows which verbs to run
and how to read them. That is what keeps it correct as the backend framework
continues to grow underneath it.

## Migration

No data migration anywhere — everything relocated is a cache or re-derivable.

- **`~/.cccp` retired.** `LOCAL_MIRROR` → `$CCCP_PLUGIN_DATA/mirror` (fallback
  `$XDG_STATE_HOME/cccp` for non-Claude callers where the env var is unset). The
  mirror is a cache; `mv ~/.cccp <backup>` and forget it. The only non-
  reconstructible item there is `aliases.json` — losing it just resets aliases
  to auto-generated.
- **`~/.config/cccp/*` retired.** Azure config → `backend/azure-blob/config`.
- **statusline files** → `telemetry/claude-code/`; `claude-auth-status.json` →
  `auth-status.json` (the `claude-` prefix is redundant under the folder).

## Implementation slices

- **(a) Plumbing.** Backend abstraction + `local-fs` default + settings/config
  resolution + mirror & telemetry relocation + `cccp backend` + dynamic skill
  header. `local-fs` works out of the box with zero config.
- **(b) Azure official flow.** Config under the tree, `apply.sh` integration,
  `cccp backend use azure-blob`, Terraform reference, and end-to-end
  setup→verify debugging against a live hub.
