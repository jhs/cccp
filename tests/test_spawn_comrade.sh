#!/usr/bin/env bash
# test_spawn_comrade.sh — unit tests for spawn-comrade's PURE-BASH surface (#1577): the impl/tier
# model map, the fail-closed Pi preflight (NONPROD declaration + extension + the cccp-current symlink
# refresh), and the Pi-refusal guards. No tmux, no claude/pi launch — the script is SOURCED and its
# functions are called directly against a sandbox HOME, the ssh-prod.test.sh pattern.
#
# RAN= discipline: every assertion increments RAN; a silent match-nothing is a fail, not a pass. The
# RAN count + the fail total are the signal, not the absence of red.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$HERE/../bin/spawn-comrade"
RAN=0; FAIL=0
ok()   { RAN=$((RAN+1)); }
fail() { RAN=$((RAN+1)); FAIL=$((FAIL+1)); echo "FAIL: $*" >&2; }
eq()   { if [[ "$1" == "$2" ]]; then ok; else fail "${3:-eq}: expected [$2] got [$1]"; fi; }
ne()   { if [[ "$1" != "$2" ]]; then ok; else fail "${3:-ne}: unexpected [$1]"; fi; }

# Source the script for its functions only — SPAWN_COMRADE_LIB=1 must make it define + return before
# the main body (no tmux/launch on source). If sourcing runs main, that itself is the first failure.
export SPAWN_COMRADE_LIB=1
# shellcheck disable=SC1090
source "$SCRIPT" || { echo "FAIL: could not source $SCRIPT (is the SPAWN_COMRADE_LIB guard present?)" >&2; echo "RAN=0"; exit 1; }
set +e  # spawn-comrade sets -euo pipefail; we test nonzero returns deliberately, so drop -e here

# ── map_tier: tier language → per-impl model, raw ids pass through ──────────────
eq "$(map_tier claude cheap)"   "claude-opus-4-8[1m]" "claude/cheap"
eq "$(map_tier claude normal)"  "claude-opus-5"       "claude/normal"
eq "$(map_tier claude premium)" "claude-fable-5"      "claude/premium"
eq "$(map_tier pi cheap)"       "gpt-5.5"             "pi/cheap"
eq "$(map_tier pi normal)"      "gpt-5.6-terra"       "pi/normal"
eq "$(map_tier pi premium)"     "gpt-5.6-sol"         "pi/premium"
# Raw ids pass through unchanged for either impl (no ambient default; #798).
eq "$(map_tier pi gpt-5.6-luna)"        "gpt-5.6-luna"        "pi/raw-luna-passthrough"
eq "$(map_tier pi gpt-5.6-sol)"         "gpt-5.6-sol"         "pi/raw-passthrough"
eq "$(map_tier claude claude-opus-5)"   "claude-opus-5"       "claude/raw-passthrough"
# A claude tier is NOT silently valid as a pi model and vice-versa is only via raw id — tiers are the
# only cross-impl vocabulary; a raw id is echoed verbatim regardless of impl.
eq "$(map_tier pi claude-opus-5)"       "claude-opus-5"       "pi/raw-claude-id-verbatim"

# ── pi_refuse: claude-only flags rejected under --impl pi ──────────────────────
# A [1m] context suffix is claude-only; refuse it on a pi model.
if pi_refuse_model "gpt-5.6-sol[1m]" 2>/dev/null; then fail "pi_refuse_model should reject [1m] suffix"; else ok; fi
if pi_refuse_model "gpt-5.6-sol"     2>/dev/null; then ok; else fail "pi_refuse_model rejected a clean pi model"; fi

# ── pi_preflight: fail-closed on missing NONPROD declaration / missing extension ─
SANDBOX="$(mktemp -d)"; trap 'rm -rf "$SANDBOX"' EXIT
export HOME="$SANDBOX"
mkdir -p "$SANDBOX/.pi/agent"
# (a) no AGENTS.md symlink, no extension install → fail closed, nonzero, names the fix.
out="$(pi_preflight 2>&1)"; rc=$?
ne "$rc" "0" "preflight/no-agents rc"
if grep -qiE "AGENTS\.md|NONPROD|symlink" <<<"$out"; then ok; else fail "preflight should name the AGENTS.md/NONPROD fix"; fi

# (b) AGENTS.md present but NO installed cccp plugin → still fail closed on the extension.
ln -s /dev/null "$SANDBOX/.pi/agent/AGENTS.md"
out="$(pi_preflight 2>&1)"; rc=$?
ne "$rc" "0" "preflight/no-extension rc"
if grep -qiE "install|extension|plugins/cache/CCCP" <<<"$out"; then ok; else fail "preflight should name the extension install fix"; fi

# (c) both present → succeeds AND refreshes ~/.pi/agent/cccp-current to the NEWEST installed version.
mkdir -p "$SANDBOX/.claude/plugins/cache/CCCP/cccp/3.2.0/integrations/pi" \
         "$SANDBOX/.claude/plugins/cache/CCCP/cccp/3.3.0/integrations/pi" \
         "$SANDBOX/.claude/plugins/cache/CCCP/cccp/3.10.0/integrations/pi"
touch "$SANDBOX/.claude/plugins/cache/CCCP/cccp/3.10.0/integrations/pi/cccp-comrade.ts"
out="$(pi_preflight 2>&1)"; rc=$?
eq "$rc" "0" "preflight/ok rc"
# version-sort: 3.10.0 > 3.3.0 > 3.2.0 (NOT lexical, where 3.3.0 > 3.10.0)
target="$(readlink "$SANDBOX/.pi/agent/cccp-current" 2>/dev/null)"
eq "$target" "$SANDBOX/.claude/plugins/cache/CCCP/cccp/3.10.0" "cccp-current → newest version"

echo "RAN=$RAN FAIL=$FAIL"
[[ "$FAIL" -eq 0 ]]
