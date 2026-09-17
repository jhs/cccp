#!/bin/bash
# Export CCCP plugin env vars into the Claude session so Bash/Monitor commands
# can access them.
#
# Renamed from CLAUDE_PLUGIN_* to CCCP_* to avoid collisions — every plugin
# gets the same CLAUDE_PLUGIN_* names, so they'd overwrite each other.

echo "export CCCP_PLUGIN_ROOT='${CLAUDE_PLUGIN_ROOT}'"
echo "export CCCP_PLUGIN_DATA='${CLAUDE_PLUGIN_DATA}'"
# The `cccp` on PATH is THIS plugin's, by construction. Claude Code puts every
# plugin's bin/ on PATH in its own order, so with two cccp plugins loaded (an
# installed one beside a --plugin-dir checkout) the model's `cccp` could be a
# different build from the one whose data dir and monitor this session uses.
echo "export PATH='${CLAUDE_PLUGIN_ROOT}/bin:'\"\$PATH\""
