#!/usr/bin/env bash
#
# Run the checks and tests of the Cal card agent.
#
#   ./scripts/test.sh                # every target (default)
#   ./scripts/test.sh all            # every target (explicit; alias: it)
#   ./scripts/test.sh unit           # the same without the integration tests (no Docker)
#
# Every target runs: the scripts' syntax check (bash -n), lint and formatting (ruff), typecheck
# (mypy), import-linter layer contracts, pytest, then the shell tests of scripts/tests/. The
# integration tests, pytest's -m integration, start Redis through Testcontainers, so Docker must be
# running for all.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

usage() {
  echo "Usage: ./scripts/test.sh [all|unit] (alias of all: it)" >&2
  exit 2
}

PYTEST_ARGS=()
for arg in "$@"; do
  case "$(printf '%s' "$arg" | tr '[:upper:]' '[:lower:]')" in
    -h|--help) print_help; exit 0 ;;
    all|it)    ;;
    unit)      PYTEST_ARGS=(-m "not integration") ;;
    *) usage ;;
  esac
done

echo "--> scripts (bash -n)"
for script in "$ROOT"/scripts/*.sh "$ROOT"/scripts/lib/*.sh "$ROOT"/scripts/tools/*.sh \
    "$ROOT"/scripts/tests/*.sh "$ROOT/.githooks/pre-commit"; do
  bash -n "$script"
done
ensure_venv
cd "$ROOT"
echo "--> lint (ruff)"
"$VENV/bin/ruff" check src tests
echo "--> format (ruff format --check)"
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
