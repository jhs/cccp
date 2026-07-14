#!/bin/bash
# Export CCCP plugin env vars into the Claude session so Bash/Monitor commands
# can access them.
#
# Renamed from CLAUDE_PLUGIN_* to CCCP_* to avoid collisions — every plugin
# gets the same CLAUDE_PLUGIN_* names, so they'd overwrite each other.

echo "export CCCP_PLUGIN_ROOT='${CLAUDE_PLUGIN_ROOT}'"
echo "export CCCP_PLUGIN_DATA='${CLAUDE_PLUGIN_DATA}'"
