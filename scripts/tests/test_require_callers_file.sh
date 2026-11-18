#!/usr/bin/env bash
# Verifies require_callers_file from scripts/common.sh: deploy.sh stops before any launch when no
# callers registry exists, naming the tool that writes one, and passes with the registry present,
# a relative A2A_CALLERS_FILE resolved against the repo, or with access not required.
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

mkdir -p "$WORK/scripts/lib"
cp "$SCRIPTS_DIR/common.sh" "$WORK/scripts/common.sh"
cp "$SCRIPTS_DIR/lib/settings-guard.sh" "$SCRIPTS_DIR/lib/ec2.sh" "$WORK/scripts/lib/"

fail() { echo "FAIL: $*" >&2; exit 1; }

# Runs in a subshell so the sourced helpers and exported values do not leak between cases.
check() { (unset A2A_CALLERS_FILE A2A_AUTH_REQUIRED; [ $# -eq 0 ] || export "$@"
           . "$WORK/scripts/common.sh"; require_callers_file) 2>&1; }

out="$(check)" && fail "missing file accepted"
grep -q "tools/register-caller.sh" <<<"$out" || fail "missing file not pointed at the tool: $out"

check A2A_AUTH_REQUIRED=false >/dev/null || fail "refused with access not required"

touch "$WORK/allowed-callers.yaml"
check >/dev/null || fail "refused the default file"
mkdir "$WORK/other" && touch "$WORK/other/callers.yaml"
check A2A_CALLERS_FILE=other/callers.yaml >/dev/null || fail "relative file not resolved"

echo "test_require_callers_file: all checks passed"
