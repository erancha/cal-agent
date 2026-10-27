#!/usr/bin/env bash
#
# Run cal-agent. Docker is the default; --host runs it as one local process for fast restarts
# and debugger attach. Either way the agent answers on http://localhost:${SERVER_PORT:-8030} and,
# once /health is green, prints its Agent Card URL and the values a caller's operator registers
# it with: its name, AGENT_URL and the page URL.
#
#   ./scripts/start.sh            # build the image and run two replicas behind the edge
#   ./scripts/start.sh --host     # uvicorn from the venv, attached to this terminal (Ctrl-C stops)
#
# Requires .env (./scripts/init-env.sh) and, while access is required, a registered caller
# (./scripts/register-caller.sh). Stop or inspect the Docker run with docker-helper.sh.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

HOST=0
for arg in "$@"; do
  case "$arg" in
    --host)    HOST=1 ;;
    -h|--help) print_help; exit 0 ;;
    *) echo "Usage: ./scripts/start.sh [--host]" >&2; exit 2 ;;
  esac
done

require_env
load_env
require_callers_file
ensure_statements_dir
BASE="$(page_url)"

print_card_url() {
  echo "cal-agent -> $BASE   card: $BASE/.well-known/agent-card.json"
  print_handover "each A2A caller's operator" \
    "the one register-caller.sh printed when it registered that caller"
}

if [ "$HOST" -eq 0 ]; then
  require_docker
  compose up -d --build
  wait_for_health "$BASE" \
    || { echo "agent did not become healthy; see ./scripts/docker-helper.sh --logs" >&2; exit 1; }
  print_card_url
  echo "stop or tail logs:  ./scripts/docker-helper.sh --stop | --logs"
  exit 0
fi

ensure_venv
echo "Starting cal-agent on $BASE (statements: $STATEMENTS_DIR)"
(cd "$ROOT" && exec "$VENV/bin/uvicorn" calagent.platform.app:create_app --factory \
  --host 0.0.0.0 --port "${SERVER_PORT:-8030}") &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null' INT TERM
wait_for_health "$BASE" "$SERVER_PID" \
  || { echo "agent did not become healthy; see the output above" >&2;
       kill "$SERVER_PID" 2>/dev/null; exit 1; }
print_card_url
wait "$SERVER_PID"
