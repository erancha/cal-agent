#!/usr/bin/env bash
# Verifies load_env from scripts/common.sh: .env supplies defaults, a variable already exported by
# the caller wins, one pair of surrounding quotes is stripped, and a malformed line aborts.
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

mkdir -p "$WORK/scripts"
cp "$SCRIPTS_DIR/common.sh" "$WORK/scripts/common.sh"

fail() { echo "FAIL: $*" >&2; exit 1; }

cat > "$WORK/.env" <<'ENV'
# a comment

PLAIN=plain
DOUBLE="two words"
SINGLE='single quoted'
KEPT=from-env-file
ENV

# Runs in a subshell so the sourced helpers and exported values do not leak between cases.
run_load_env() { (export KEPT=from-caller; . "$WORK/scripts/common.sh"; load_env; "$@"); }

[[ "$(run_load_env bash -c 'echo "$KEPT"')" == "from-caller" ]] || fail "caller value overwritten"
[[ "$(run_load_env bash -c 'echo "$PLAIN"')" == "plain" ]] || fail "plain value not loaded"
[[ "$(run_load_env bash -c 'echo "$DOUBLE"')" == "two words" ]] || fail "double quotes kept"
[[ "$(run_load_env bash -c 'echo "$SINGLE"')" == "single quoted" ]] || fail "single quotes kept"

for bad in "export FOO=1" "BAD LINE"; do
  printf 'OK=1\n%s\n' "$bad" > "$WORK/.env"
  if run_load_env true 2>"$WORK/err"; then fail "accepted malformed line: $bad"; fi
  grep -q '\.env:2:' "$WORK/err" || fail "no line number reported for: $bad"
done

echo "test_load_env: all checks passed"
