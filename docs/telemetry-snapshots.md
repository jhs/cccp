# Telemetry snapshots

A **snapshot** is one JSON file describing one agent session at one moment: which
model, how full its context window is, and when that reading was taken. A session
writes its own; anything else on the machine reads them.

```
$CCCP_PLUGIN_DATA/telemetry/<v-major|inline>/<producer>/<session_id>.json
```

`bin/cccp-statusline` writes the Claude Code ones from the statusLine payload;
`bin/claude-tokens` reads them. Nothing in the tree is authoritative -- it is a
cache, safe to wipe (see the plugin data map in `bin/cccp`).

## The producer directory is not part of a snapshot identity

Session ids are globally unique, so `<producer>` -- `claude-code/`, `pi/`, a
harness not written yet -- records only which program happened to write the file.
Readers **glob** the producer level:

```
telemetry/<seg>/*/<session_id>.json
```

Adding a harness therefore costs the reader nothing: it writes into its own
directory and is found. A reader that hardcodes `claude-code/` cannot see any
other harness, which is the whole reason for the glob.

The `<v-major|inline>` partition above it is different, and stays: one data root
receives writes from every version installed from one marketplace, so two
installed majors with different payload expectations must not share a directory.
The writer, the reader, and `bin/cccp` all derive that segment from the same
`plugin.json` by the same rule -- major digits before the first dot, a `.git`
directory means `inline`. A divergence strands the reader silently, which is
exactly the failure of #14.

## Required fields

A snapshot is a **field contract, not a file format**. A producer may write any
JSON object it likes as long as these fields are present and mean what the table
says. Everything else is optional and ignored by readers.

| Field | Type | Meaning |
|---|---|---|
| `session_id` | string | Session identity; must equal the file basename |
| `session_name` | string | Human display label |
| `model.display_name` | string | Model, for display |
| `context_window.context_window_size` | number | Window size, the denominator |
| `context_window.total_input_tokens` | number | Input tokens consumed |
| `context_window.total_output_tokens` | number | Output tokens consumed |
| `context_window.used_percentage` | number | Percent used; preferred over the computed ratio when present |
| `updated_at` | number | Epoch seconds when the reading was taken |

Absent `context_window` data is legal and means *no reading yet* -- a fresh or
just-compacted session. Readers say so rather than printing a zero.

A producer that has no real value for a field **omits it**. It does not fake one,
and it does not imitate another harness payload: imitation puts invented values
in a file and re-breaks whenever the imitated harness changes shape. The Claude
Code statusLine payload already satisfies this contract as-is, which is why
`cccp-statusline` still dumps it verbatim -- the one thing it adds is
`updated_at`.

## Why updated_at rather than file mtime

Staleness must travel inside the file. A snapshot is self-describing and its
session id is globally unique, so copying one between machines is a legitimate
thing to do -- and the moment it is copied, mtime records the copy, not the
reading. A stale reading that looks fresh is worse than a missing one, so readers
take the age from `updated_at` and report the age as unknown when it is absent,
rather than inventing one from the filesystem.
