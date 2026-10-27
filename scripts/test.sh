#!/usr/bin/env bash
#
# Run the checks and tests of the Cal card agent.
#
#   ./scripts/test.sh            # all: ruff, mypy, lint-imports, pytest (integration included),
#                                # then the shell tests of scripts/tests
#   ./scripts/test.sh unit       # the same without -m integration (no Docker)
#   ./scripts/test.sh it         # all, explicitly
#
# Integration tests start containers through Testcontainers, so Docker must be running for all
# and it.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

PYTEST_ARGS=()
case "${1:-all}" in
  -h|--help) print_help; exit 0 ;;
  all|it) ;;
  unit) PYTEST_ARGS=(-m "not integration") ;;
  *) print_help >&2; exit 2 ;;
esac

ensure_venv
cd "$ROOT"
echo "--> lint (ruff)"
"$VENV/bin/ruff" check src tests
"$VENV/bin/ruff" format --check src tests
echo "--> typecheck (mypy)"
"$VENV/bin/mypy"
echo "--> import-linter (layer contracts)"
"$VENV/bin/lint-imports"
echo "--> pytest"
"$VENV/bin/pytest" "${PYTEST_ARGS[@]}"
echo "--> shell tests"
for shell_test in "$SCRIPT_DIR"/tests/*.sh; do bash "$shell_test"; done
echo "All requested tests passed."
