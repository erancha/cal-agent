#!/usr/bin/env bash
# Verifies ensure_statements_dir from scripts/common.sh: start.sh creates the statements root
# before any launch, a relative STATEMENTS_DIR resolved against the repo whatever the working
# directory, an absolute one as given, and an unset one stops naming the variable.
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

mkdir -p "$WORK/repo/scripts" "$WORK/elsewhere"
cp "$SCRIPTS_DIR/common.sh" "$WORK/repo/scripts/common.sh"

fail() { echo "FAIL: $*" >&2; exit 1; }

# Runs in a subshell from another directory so a cwd-relative mkdir would miss the repo.
check() { (unset STATEMENTS_DIR; [ $# -eq 0 ] || export "$@"; cd "$WORK/elsewhere"
           . "$WORK/repo/scripts/common.sh"; ensure_statements_dir) 2>&1; }

check STATEMENTS_DIR=./statements >/dev/null || fail "relative folder not created"
[ -d "$WORK/repo/statements" ] || fail "relative folder not created under the repo"
[ -e "$WORK/elsewhere/statements" ] && fail "relative folder created under the working directory"
check STATEMENTS_DIR=./statements >/dev/null || fail "existing folder refused"

check STATEMENTS_DIR="$WORK/absolute/nested" >/dev/null || fail "absolute folder not created"
[ -d "$WORK/absolute/nested" ] || fail "absolute folder not created where named"

out="$(check)" && fail "unset STATEMENTS_DIR accepted"
grep -q "STATEMENTS_DIR" <<<"$out" || fail "unset variable not named: $out"

ensure_line="$(grep -n '^ensure_statements_dir$' "$SCRIPTS_DIR/start.sh" | cut -d: -f1)"
compose_line="$(grep -n 'compose up' "$SCRIPTS_DIR/start.sh" | cut -d: -f1)"
[ -n "$ensure_line" ] && [ "$ensure_line" -lt "$compose_line" ] \
  || fail "start.sh does not create the statements root before compose up"

echo "test_statements_dir: all checks passed"
