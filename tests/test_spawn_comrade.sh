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
eq "$(model_for claude normal)" "claude-opus-5" "Claude normal tier"
eq "$(model_for claude premium)" "claude-fable-5" "Claude premium tier"
eq "$(model_for pi cheap)" "gpt-5.5" "Pi cheap tier"
eq "$(model_for pi normal)" "gpt-5.6-terra" "Pi normal tier"
eq "$(model_for pi premium)" "gpt-5.6-sol" "Pi premium tier"
eq "$(model_for pi gpt-5.6-luna)" "gpt-5.6-luna" "raw model passes through"

if pi_model_ok 'gpt-5.6-sol[1m]' 2>/dev/null; then
  fail "Pi must reject Claude's [1m] model suffix"
else
  ok
fi

prompt="$(pi_prompt Builder cell-a captain@host:abc docs/brief.md)"
has "$prompt" "/skill:cccp-chat cell-a" "Pi prompt starts the chat skill"
has "$prompt" "@docs/brief.md" "Pi prompt references supplied docs"
has "$prompt" "captain@host:abc" "Pi prompt targets the captain"
has "$prompt" "Comrade Introduction: Builder" "Pi prompt preserves Pi alias trigger"

echo "Test results: RAN=$RAN FAIL=$FAIL"
[[ "$FAIL" -eq 0 ]]
