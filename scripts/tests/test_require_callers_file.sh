#!/usr/bin/env bash
# Verifies require_callers_file from scripts/common.sh: start.sh stops before any launch when no
# callers file exists, removes an empty directory standing in its place and refuses one with
# content, and passes with the file present or with access not required.
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

mkdir -p "$WORK/scripts"
cp "$SCRIPTS_DIR/common.sh" "$WORK/scripts/common.sh"

fail() { echo "FAIL: $*" >&2; exit 1; }

# Runs in a subshell so the sourced helpers and exported values do not leak between cases.
check() { (unset A2A_CALLERS_FILE A2A_AUTH_REQUIRED; [ $# -eq 0 ] || export "$@"
           . "$WORK/scripts/common.sh"; require_callers_file) 2>&1; }

out="$(check)" && fail "missing file accepted"
grep -q "register-caller.sh" <<<"$out" || fail "missing file not pointed at the script: $out"

mkdir "$WORK/allowed-callers.yaml"
out="$(check)" && fail "empty directory accepted as a callers file"
[ -e "$WORK/allowed-callers.yaml" ] && fail "empty directory not removed"
grep -q "register-caller.sh" <<<"$out" || fail "after removal not pointed at the script: $out"
mkdir "$WORK/allowed-callers.yaml" && touch "$WORK/allowed-callers.yaml/keep"
out="$(check)" && fail "directory with content accepted"
grep -q "directory with content" <<<"$out" || fail "content not named as the cause: $out"
rm -r "$WORK/allowed-callers.yaml"

check A2A_AUTH_REQUIRED=false >/dev/null || fail "refused with access not required"

touch "$WORK/allowed-callers.yaml"
check >/dev/null || fail "refused the default file"
mkdir "$WORK/other" && touch "$WORK/other/callers.yaml"
check A2A_CALLERS_FILE=other/callers.yaml >/dev/null || fail "relative file not resolved"

echo "test_require_callers_file: all checks passed"
