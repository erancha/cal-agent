#!/usr/bin/env bash
#
# Prove the agent alone, without any real caller. Starts it on the host against the test
# statement with the keyword table (no model) and a throwaway signing key standing in for Google,
# then drives it from the client side as a registered caller forwarding a person's token: card, a
# streaming task for 2026-10 (19 transactions, completed), a task for 2026-09 (input-required),
# continue (asks again), cancel rules, a call without the person's token and one with a token for
# another client (auth-required), a wrong secret (401), and the statements API with and without
# the person's token.
# Then boots the agent once per real provider (anthropic, openai) with a placeholder key: the
# provider's HTTP client is built at startup, so a runtime library missing from the dependency
# pins fails here rather than on the first real deployment.
#
#   ./scripts/validate.sh          # the client-side checks above
#   ./scripts/validate.sh --tck    # additionally run the official A2A TCK (MUST level, JSON-RPC)
#
# --tck clones or updates github.com/a2aproject/a2a-tck under .tck/, starts a second agent with
# A2A_EXECUTOR=tck (scenario executor, auth off) and fails on any MUST failure. It needs network
# access for the first run. Everything else needs Python 3.14+ and openssl. Nothing is left
# running; the run's files live under .validate/ and .tck/, both ignored by git.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

TCK=0
for arg in "$@"; do
  case "$arg" in
    --tck)     TCK=1 ;;
    -h|--help) print_help; exit 0 ;;
    *) echo "Usage: ./scripts/validate.sh [--tck]" >&2; exit 2 ;;
  esac
done

ensure_venv
PORT=8031
BASE="http://localhost:$PORT"
WORK="$ROOT/.validate"

# A key pair of this run's own stands in for Google: the agent verifies against the public half,
# check_agent.py signs with the private one. The person is user 1000, whose folder holds the test
# statement; the caller is registered the way an operator registers a real one.
rm -rf "$WORK" && mkdir -p "$WORK/statements/1000"
openssl genpkey -quiet -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out "$WORK/private.pem"
openssl pkey -in "$WORK/private.pem" -pubout -out "$WORK/public.pem"
cp "$ROOT/tests/statements/2026-10.pdf" "$WORK/statements/1000/2026-10.pdf"
ISSUER=validate
PAGE_CLIENT_ID=validate-page
CALLER_CLIENT_ID=validate-caller
CALLER_SECRET="validate-$(date +%s)"
"$SCRIPT_DIR/register-caller.sh" --name validate --secret "$CALLER_SECRET" \
  --client-id "$CALLER_CLIENT_ID" --file "$WORK/allowed-callers.yaml" >/dev/null

pids=()
cleanup() { [ ${#pids[@]} -gt 0 ] && kill "${pids[@]}" 2>/dev/null || true; }
trap cleanup INT TERM EXIT

# A health answer before launch means another agent (often an orphan of an interrupted run)
# owns the port; checking against it would prove nothing about this build. The settings of the
# caller's shell that change what the agent is (a shared Redis, a slow classifier, another
# executor) are dropped; the rest of the environment is passed through.
run_agent() {  # port model [executor]
  local url="http://localhost:$1" log="$WORK/agent-$1.log"
  # The tck executor refuses to start beside a callers file; this path is never created.
  local callers="$WORK/allowed-callers.yaml"
  [ "${3:-card}" = tck ] && callers="$WORK/no-callers.yaml"
  if is_healthy "$url"; then
    echo "port $1 already serves an agent; stop it first (lsof -ti tcp:$1 | xargs kill)" >&2
    exit 1
  fi
  (cd "$ROOT" && exec env -u TASKS_REDIS_URL -u CAL_TEST_SLOW_MS -u A2A_AUTH_REQUIRED \
    SERVER_PORT="$1" AGENT_URL="$url" LLM_MODEL="$2" LLM_API_KEY=placeholder \
    A2A_EXECUTOR="${3:-card}" STATEMENTS_DIR="$WORK/statements" \
    AUTH_CLIENT_ID="$PAGE_CLIENT_ID" AUTH_ISSUER="$ISSUER" \
    AUTH_PUBLIC_KEY_FILE="$WORK/public.pem" A2A_CALLERS_FILE="$callers" \
    LOG_LEVEL=WARNING "$VENV/bin/uvicorn" calagent.platform.app:create_app --factory \
    --port "$1" >"$log" 2>&1) &
  local pid=$!
  pids+=("$pid")
  wait_for_health "$url" "$pid" \
    || { echo "agent on $1 exited or did not become healthy; see $log" >&2; exit 1; }
}

stop_last_agent() {
  local last=$((${#pids[@]} - 1))
  kill "${pids[$last]}" && wait "${pids[$last]}" 2>/dev/null || true
  pids=("${pids[@]:0:$last}")
}

run_agent "$PORT" keyword
echo "==> client-side checks against $BASE"
"$VENV/bin/python" "$SCRIPT_DIR/validate/check_agent.py" "$BASE" \
  --private-key "$WORK/private.pem" --issuer "$ISSUER" --caller-secret "$CALLER_SECRET" \
  --caller-client-id "$CALLER_CLIENT_ID" --page-client-id "$PAGE_CLIENT_ID" \
  --covered 2026-10 --count 19 --uncovered 2026-09
stop_last_agent

PROVIDER_PORT=8033
for provider in anthropic openai; do
  run_agent "$PROVIDER_PORT" "$provider:placeholder"
  echo "==> $provider provider boots"
  stop_last_agent
done

if [ "$TCK" -eq 1 ]; then
  TCK_DIR="$ROOT/.tck"
  if [ -d "$TCK_DIR/.git" ]; then (cd "$TCK_DIR" && git pull -q --ff-only)
  else git clone -q https://github.com/a2aproject/a2a-tck.git "$TCK_DIR"; fi
  [ -x "$TCK_DIR/.venv/bin/python" ] || python3 -m venv "$TCK_DIR/.venv"
  "$TCK_DIR/.venv/bin/pip" install --quiet --disable-pip-version-check -e "$TCK_DIR"
  TCK_PORT=8032
  run_agent "$TCK_PORT" keyword tck
  echo "==> A2A TCK (MUST, jsonrpc) against http://localhost:$TCK_PORT"
  (cd "$TCK_DIR" && .venv/bin/python ./run_tck.py --sut-host "http://localhost:$TCK_PORT" \
    --transport jsonrpc --level must)
  stop_last_agent
  echo "TCK reports: $TCK_DIR/reports/"
fi
echo "validate: OK"
