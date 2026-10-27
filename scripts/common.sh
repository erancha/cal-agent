#!/usr/bin/env bash
# Shared helpers for the cal-agent scripts: repo paths, help text, the compose wrapper, the
# callers-file checks, .env loading, venv provisioning, the health wait every launcher uses and
# the hand-over lines start.sh prints for a caller's operator.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv"
COMPOSE_FILE="$ROOT/docker-compose.yml"

# Print the calling script's header comment block as --help text (single source of usage docs).
print_help() { awk 'NR==1 {next} /^#/ {sub(/^# ?/, ""); print; next} {exit}' "$0"; }

# The container runs as the caller so files it writes into the statements mount are theirs.
compose() {
  (cd "$ROOT" && HOST_UID="$(id -u)" HOST_GID="$(id -g)" \
    docker compose -f "$COMPOSE_FILE" "$@")
}

require_docker() {
  docker info >/dev/null 2>&1 \
    || { echo "Docker is not reachable; start it and retry." >&2; exit 1; }
}

# The venv holds the runtime dependencies at the exact pins the image installs (requirements.txt
# as a constraint), so the suite runs on what ships; the dev tools float within pyproject.toml. It
# is current only when installed from both files as they stand now: the stamp is a copy taken
# after the last successful install, so editing either forces a reinstall.
ensure_venv() {
  [ -d "$VENV" ] || python3 -m venv "$VENV"
  local stamp="$VENV/.dependencies.stamp"
  if ! cat "$ROOT/pyproject.toml" "$ROOT/requirements.txt" | cmp -s - "$stamp" \
     || ! { "$VENV/bin/python" -c "import calagent" 2>/dev/null \
            && [ -x "$VENV/bin/pytest" ]; }; then
    echo "Installing dependencies into .venv..."
    ( cd "$ROOT" && "$VENV/bin/pip" install --quiet --disable-pip-version-check \
        --constraint requirements.txt -e ".[dev]" )
    cat "$ROOT/pyproject.toml" "$ROOT/requirements.txt" > "$stamp"
  fi
}

# Where register-caller.sh writes the callers and the agent reads them unless A2A_CALLERS_FILE
# names another file.
DEFAULT_CALLERS_FILE="$ROOT/allowed-callers.yaml"

# Docker turns a missing mount source into an empty root-owned directory. Its parent is the
# repo, so the owner may remove it: an empty one goes quietly, a directory holding anything is
# refused by name rather than guessed about.
clear_callers_dir() {  # path
  [ -d "$1" ] || return 0
  if [ -n "$(ls -A "$1")" ]; then
    echo "$1 is a directory with content where the callers file belongs; move it away first." >&2
    exit 1
  fi
  rmdir "$1"
  echo "Removed the empty directory $1 that a Docker start without a callers file left."
}

# With access required the agent refuses to start without a registered caller, so the file is
# checked before any launch.
require_callers_file() {
  [ "${A2A_AUTH_REQUIRED:-true}" = false ] && return 0
  local file="${A2A_CALLERS_FILE:-$DEFAULT_CALLERS_FILE}"
  [[ "$file" = /* ]] || file="$ROOT/$file"
  clear_callers_dir "$file"
  [ -f "$file" ] || { echo "No A2A caller registered ($file is missing); register one first:" \
    " ./scripts/register-caller.sh --help" >&2; exit 1; }
}

# Docker turns a missing mount source into a root-owned directory the agent, running as the
# caller, cannot write uploads into, so the statements root is created first. A relative path is
# resolved against the repo, as compose resolves the mount source.
ensure_statements_dir() {
  local dir="${STATEMENTS_DIR:?set STATEMENTS_DIR in .env}"
  [[ "$dir" = /* ]] || dir="$ROOT/$dir"
  mkdir -p "$dir"
}

require_env() {
  [ -f "$ROOT/.env" ] \
    || { echo ".env not found; create it first:  ./scripts/init-env.sh" >&2; exit 1; }
}

# Export the keys of .env as defaults: a variable the caller already exported keeps its value.
# Accepts blank lines, # comments and KEY=value (one matching pair of quotes is stripped); any
# other line is rejected rather than executed.
load_env() {
  local line key value lineno=0
  while IFS= read -r line || [[ -n "$line" ]]; do
    lineno=$((lineno + 1))
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    if [[ ! "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]]; then
      echo "$ROOT/.env:$lineno: expected KEY=value, got: $line" >&2
      exit 1
    fi
    key="${line%%=*}"
    value="${line#*=}"
    if [[ "$value" =~ ^\"(.*)\"$ || "$value" =~ ^\'(.*)\'$ ]]; then
      value="${BASH_REMATCH[1]}"
    fi
    if [[ -z "${!key+x}" ]]; then
      export "$key=$value"
    fi
  done < "$ROOT/.env"
}

is_healthy() { curl -fs --max-time 2 -o /dev/null "$1/health"; }  # base-url

# The name a caller's operator registers this agent under.
AGENT_NAME=cal

# The URLs the hand-over names, with the agent's defaults when .env leaves them unset, so
# the printed values are the running agent's.
page_url() { echo "http://localhost:${SERVER_PORT:-8030}"; }
advertised_url() { echo "${AGENT_URL:-$(page_url)}"; }

# The four values a caller's operator registers this agent with. register-caller.sh prints them
# with the secret it minted; start.sh repeats them once the agent is up. A localhost card reaches
# only a caller on this host outside Docker, so that case is flagged while the value can change.
print_handover() {  # audience secret-text
  local url
  url="$(advertised_url)"
  echo "Hand these to $1:"
  echo "  name:            $AGENT_NAME"
  echo "  A2A URL:         $url"
  echo "  statements page: $(page_url)"
  echo "  secret:          $2"
  if [[ "$url" == http://localhost* ]]; then
    echo "A caller running in Docker on this machine cannot reach localhost; set AGENT_URL" \
      "to http://host.docker.internal:8030 in .env before handing the URL over."
  fi
}

# Poll the health endpoint until it answers or 60 seconds pass. Given a pid, fail as soon as that
# process exits, so a dead launch is reported at once instead of after the full wait.
wait_for_health() {  # base-url [pid]
  local attempt
  for attempt in $(seq 60); do
    is_healthy "$1" && return 0
    if [ -n "${2:-}" ] && ! kill -0 "$2" 2>/dev/null; then
      return 1
    fi
    sleep 1
  done
  return 1
}
