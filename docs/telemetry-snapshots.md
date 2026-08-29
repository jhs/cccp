# Telemetry snapshots

A **snapshot** is one JSON file describing one agent session at one moment: which
model, how full its context window is, and when that reading was taken. A session
writes its own; anything else on the machine reads them.

```
$CCCP_PLUGIN_DATA/telemetry/<v-major|inline>/<producer>/<session_id>.json
```

`bin/cccp-statusline` writes the Claude Code ones from the statusLine payload,
`integrations/pi/telemetry.ts` writes the Pi ones, and `bin/claude-tokens` reads
either. Nothing in the tree is authoritative -- it is a cache, safe to wipe
(see the plugin data map in `bin/cccp`).

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

Always present:

| Field | Type | Meaning |
|---|---|---|
| `session_id` | string | Session identity; must equal the file basename |
| `updated_at` | number | Epoch seconds when the reading was taken |

Present once the session has a reading, as `context_window`:

| Field | Type | Meaning |
|---|---|---|
| `context_window_size` | number | Window size, the denominator |
| `total_tokens` | number | Context tokens consumed, the numerator |
| `total_input_tokens` / `total_output_tokens` | number | The same numerator as a split; readers sum them |
| `used_percentage` | number | Percent used; preferred over the computed ratio when present |

Present when the producer has one -- a display label is not something every
harness can invent, and an unnamed session genuinely has no name:

| Field | Type | Meaning |
|---|---|---|
| `session_name` | string | Human display label |
| `model.display_name` | string | Model, for display |

The numerator has two spellings because harnesses genuinely differ: the Claude
Code statusLine payload reports input and output separately, while Pi measures
context as one number. A producer writes whichever it actually has --
`total_tokens` alone is a complete snapshot -- and readers accept either,
preferring `total_tokens`. Neither is faked from the other.

Absent `context_window` data is legal and means *no reading yet* -- a fresh or
just-compacted session. So is a `context_window` with a size but no numerator,
which a producer should not write and a reader must not read as zero: a
confident 0% is worse than an admitted absence. Readers say so rather than
printing a zero.

A producer that has no real value for a field **omits it**. It does not fake one,
and it does not imitate another harness payload: imitation puts invented values
in a file and re-breaks whenever the imitated harness changes shape. The Claude
Code statusLine payload already satisfies this contract as-is, which is why
`cccp-statusline` still dumps it verbatim -- the one thing it adds is
`updated_at`.

## Writing is a consent, not a side effect

A harness may leave snapshots only where the user has agreed to files being
written. Claude Code carries that consent in the statusLine the user installs
themselves; Pi carries it in `CCCP_DO_PI_TELEMETRY`, which is off by default --
loading the extension so a session can watch its own context is one decision,
leaving files on disk for other processes is another.

Deliberately not `CCCP_PLUGIN_DATA`: that variable says *where* cccp data lives
and is filled in automatically, so it cannot also mean "yes, write". And a
producer that is switched on but cannot write must say so where a human will see
it, rather than degrading to silence -- from outside, a session writing nothing
is indistinguishable from a dead one, which is the very confusion snapshots
exist to end.

## Why updated_at rather than file mtime

Staleness must travel inside the file. A snapshot is self-describing and its
session id is globally unique, so copying one between machines is a legitimate
thing to do -- and the moment it is copied, mtime records the copy, not the
reading. A stale reading that looks fresh is worse than a missing one, so readers
take the age from `updated_at` and report the age as unknown when it is absent,
rather than inventing one from the filesystem.
