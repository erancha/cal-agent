#!/usr/bin/env bash
# Verifies docker-helper.sh refuses what it does not support before touching Docker: an unknown
# command, and any argument after --stop or --ps (--stop --volumes included).
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fail() { echo "FAIL: $*" >&2; exit 1; }

refused() {  # expected-text args...
  local expected="$1" out
  shift
  out="$(bash "$SCRIPTS_DIR/docker-helper.sh" "$@" 2>&1)" && fail "accepted: $*"
  grep -q "$expected" <<<"$out" || fail "'$*' refused without naming the cause: $out"
}

refused "takes no arguments (got: --volumes)" --stop --volumes
refused "takes no arguments (got: extra)" --ps extra
refused "Unknown command: --bogus" --bogus

echo "test_docker_helper: all checks passed"
