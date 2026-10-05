#!/usr/bin/env bash
# Unit tests for spawn-comrade's implementation-neutral helpers.  The launch
# path needs tmux and a real agent; these tests deliberately do not.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$HERE/../bin/spawn-comrade"
RAN=0 FAIL=0
ok() { RAN=$((RAN + 1)); }
fail() { RAN=$((RAN + 1)); FAIL=$((FAIL + 1)); echo "FAIL $*" >&2; }
eq() { [[ "$1" == "$2" ]] && ok || fail "${3:-values differ}: expected [$2], got [$1]"; }
has() { [[ "$1" == *"$2"* ]] && ok || fail "${3:-missing text}: [$2] not in [$1]"; }

# The library guard must define helpers without trying to start tmux.
export SPAWN_COMRADE_LIB=1
# shellcheck disable=SC1090
source "$SCRIPT" || { echo "FAIL Could not source spawn-comrade" >&2; exit 1; }
set +e

eq "$(model_for claude cheap)" "claude-opus-4-8[1m]" "Claude cheap tier"
eq "$(model_for claude normal)" "claude-opus-5-5" "Claude normal tier"
eq "$(model_for claude premium)" "claude-fable-5-1" "Claude premium tier"
eq "$(model_for pi cheap)" "gpt-5.5" "Pi cheap tier"
eq "$(model_for pi normal)" "gpt-5.6-terra" "Pi normal tier"
eq "$(model_for pi premium)" "gpt-5.6-sol" "Pi premium tier"
eq "$(model_for pi gpt-5.6-luna)" "gpt-5.6-luna" "raw model passes through"

if pi_model_ok 'gpt-5.6-sol[1m]' 2>/dev/null; then
  fail "Pi must reject Claude's [1m] model suffix"
else
  ok
fi

prompt="$(pi_prompt Builder cell-a captain@host:abc 'Comrade Introduction:' docs/brief.md)"
has "$prompt" "/skill:cccp-chat cell-a" "Pi prompt starts the chat skill"
has "$prompt" "@docs/brief.md" "Pi prompt references supplied docs"
has "$prompt" "captain@host:abc" "Pi prompt targets the captain"
has "$prompt" "Comrade Introduction: Builder" "Pi prompt teaches the given trigger"
has "$(pi_prompt Builder cell-a '' 'Intro:')" 'broadcast an introduction beginning exactly "Intro: Builder"' "Pi broadcast intro uses the given trigger"

prompt="$(claude_prompt team Builder cell-a captain@host:abc 'Comrade Introduction:' docs/a.md docs/b.md)"
eq "$prompt" "/cccp:team cell-a # See docs/a.md then docs/b.md -- then introduce yourself to your Captain at captain@host:abc,\
 beginning with the literal prefix Comrade Introduction: followed by your alias Builder" "Claude prompt teaches the given trigger"
eq "$(claude_prompt team Builder cell-a '' 'Intro:')" \
  "/cccp:team cell-a -- then introduce yourself to the cell, beginning with the literal prefix Intro: followed by your alias Builder" "Claude prompt without docs or captain"

# #51: the trigger comes from cccp's config, the one source every seat on the machine introduces itself with.
data="$(mktemp -d)"
eq "$(env -u CCCP_ALIAS_TRIGGER CCCP_PLUGIN_DATA="$data" bash -c 'source "$1"; alias_trigger' _ "$SCRIPT")" "Intro:" "Trigger defaults with nothing configured"
printf 'CCCP_ALIAS_TRIGGER=Comrade Introduction:\n' >"$data/config"
eq "$(env -u CCCP_ALIAS_TRIGGER CCCP_PLUGIN_DATA="$data" bash -c 'source "$1"; alias_trigger' _ "$SCRIPT")" "Comrade Introduction:" "Trigger follows config"
rm -rf "$data"

echo "Test results: RAN=$RAN FAIL=$FAIL"
[[ "$FAIL" -eq 0 ]]
