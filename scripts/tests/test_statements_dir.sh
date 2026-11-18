#!/usr/bin/env bash
# Verifies ensure_statements_dir from scripts/common.sh: deploy.sh creates the statements root
# before it starts the local stack, a relative STATEMENTS_DIR resolved against the repo whatever
# the working directory, an absolute one as given, and an unset one stops naming the variable.
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

mkdir -p "$WORK/repo/scripts/lib" "$WORK/elsewhere"
cp "$SCRIPTS_DIR/common.sh" "$WORK/repo/scripts/common.sh"
cp "$SCRIPTS_DIR/lib/settings-guard.sh" "$SCRIPTS_DIR/lib/ec2.sh" "$WORK/repo/scripts/lib/"

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

local_stack="$(sed -n '/^deploy_local() {$/,/^}$/p' "$SCRIPTS_DIR/deploy.sh")"
ensure_line="$(grep -n '^ *ensure_statements_dir$' <<<"$local_stack" | cut -d: -f1)"
compose_line="$(grep -n 'compose up' <<<"$local_stack" | cut -d: -f1)"
[ -n "$ensure_line" ] && [ -n "$compose_line" ] && [ "$ensure_line" -lt "$compose_line" ] \
  || fail "deploy.sh does not create the statements root before the local compose up"

echo "test_statements_dir: all checks passed"
