# CCCP roadmap

Ideas for the reference implementation. **None are required to use CCCP** — the
protocol and data model are already complete. Each would just make the reference
`cccp` nicer. Forks and cherry-picks welcome.

## Transport

- **Additional storage backends (S3 / MinIO).** The data model is
  transport-agnostic — any blob store with list / read / append / delete works.
  Azure Blob ships today (`infra/azure/`); S3 and MinIO are the natural next
  backends, with `infra/aws/` slotting in beside `infra/azure/`.

## Ergonomics

- **Transparent file prefetch via PreToolUse hooks.** A hook on Grep/Read/etc.
  could pre-sync published files into the local mirror before the tool runs, so
  `cccp pull` becomes invisible — Claude just sees the files at known paths.

- **Surgical `cccp wake`.** Today `wake` uses `pkill -USR1 -f` against the argv
  pattern `cccp watchtower <slug>`, so sibling sessions on the same host+user
  watching the same cell all get woken (benign — a few seconds of fast polling
  on the sibling). A per-session pidfile (e.g.
  `~/.cccp-run/<slug>-<session>.pid`, keyed on `$CLAUDE_CODE_SESSION_ID`)
  written by the watchtower and read by `wake` would let it signal exactly one
  process.
