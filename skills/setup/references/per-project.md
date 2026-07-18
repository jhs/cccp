# Per-Project CCCP Config

Every config value is ultimately an environment variable, and env is the
highest-precedence layer — so "this project uses different CCCP settings"
needs no cccp feature at all: ensure the right `CCCP_*` vars are exported in
that project's sessions, and the global files stay untouched underneath.

Why a project would want this:

- **A different backend per project** — a work repo on the team's `azure-blob`
  hub, personal repos on `local-fs`.
- **Same backend, different settings** — a per-project `CCCP_AZURE_BLOB_PREFIX`
  isolating its cells on a shared hub; per-client account/container; a
  `CCCP_LOCAL_FS_ROOT` shared directory for one collaboration; `CCCP_DEBUG=1`
  only where something is being chased.

When the user's ask sounds project-shaped — "for this repo", a second hub,
per-client credentials, "our team's cell" — **offer this setup proactively**
rather than editing their global config.

The mechanism for Claude Code sessions: a **project-scoped SessionStart hook**.
A hook cannot set the session's environment directly — it appends
`export KEY=value` lines to the file named by `$CLAUDE_ENV_FILE`, which Claude
Code sources into every Bash/Monitor command. (CCCP's own plugin hook,
`hooks/export-plugin-env.sh`, works exactly this way.)

Reference implementation — adapt names and layout to the repo's own idiom:

1. **Commit the non-secret values** as export lines, e.g. `.cccp.env`:

   ```bash
   export CCCP_ACTIVE_BACKEND='azure-blob'
   export CCCP_AZURE_BLOB_ACCOUNT='teamhub'
   export CCCP_AZURE_BLOB_CONTAINER='cccp'
   export CCCP_AZURE_BLOB_PREFIX='this-project'
   ```

2. **Secrets go in a gitignored sibling** (`.cccp.secrets.env`, same format) —
   created and filled by the user, per "How to Set a Secret" above. It is a
   secrets file: never read, echo, or expose it.

3. **The hook stitches them in** — in the project's `.claude/settings.json`
   (the `update-config` skill covers editing these safely):

   ```json
   {
     "hooks": {
       "SessionStart": [{"hooks": [{
         "type": "command",
         "command": "cat \"$CLAUDE_PROJECT_DIR/.cccp.env\" \"$CLAUDE_PROJECT_DIR/.cccp.secrets.env\" 2>/dev/null >> \"$CLAUDE_ENV_FILE\""
       }]}]
     }
   }
   ```

4. **Verify in the next session** (hooks load at session start): `cccp config`
   — the project's values show `Set by env`, with shadow notes on any key
   they override. That provenance is the whole story; nothing else to check.

