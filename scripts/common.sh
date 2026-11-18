#!/usr/bin/env bash
# Shared helpers for the cal-agent scripts: repo paths, help text, the settings files under
# scripts/lib/, compose access, the callers-registry and statements-folder checks, the hand-over
# lines a caller's operator records, and venv provisioning.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv"
# The stack's settings: stack-params.sh is committed; params.sh (this deployment's own settings)
# and secrets.sh are gitignored and created by init-env.sh from their .example.sh files.
STACK_PARAMS_FILE="$ROOT/scripts/lib/stack-params.sh"
PARAMS_FILE="$ROOT/scripts/lib/params.sh"
SECRETS_FILE="$ROOT/scripts/lib/secrets.sh"
# The deploying user's AWS credentials and region, read only for the EC2 target.
AWS_CONFIG_FILE="$ROOT/scripts/lib/aws-config.sh"
# The Compose files of the target: docker-compose.yml alone on this machine; use_ec2 of
# lib/ec2.sh adds the instance's override.
COMPOSE_FILES=("$ROOT/docker-compose.yml")
# Print the calling script's header comment block as --help text (single source of usage docs).
print_help() { awk 'NR==1 {next} /^#/ {sub(/^# ?/, ""); print; next} {exit}' "$0"; }

# shellcheck source=lib/settings-guard.sh
source "$ROOT/scripts/lib/settings-guard.sh"
# shellcheck source=lib/ec2.sh
source "$ROOT/scripts/lib/ec2.sh"

# Exports every setting of the three files into this shell, which is where docker compose takes
# the ${...} values and each service's keys from. Stops when a gitignored file is missing, when
# git tracks it, or when a tracked file holds one of its secrets or addresses.
load_settings() {
  # shellcheck source=lib/stack-params.sh
  source "$STACK_PARAMS_FILE"
  source_checked_file "$PARAMS_FILE" assert_addresses_untracked
  source_checked_file "$SECRETS_FILE" assert_secrets_untracked
}

# Adds each listed setting that is blank or still its example's <placeholder> to
# MISSING_SETTINGS, with the file under scripts/lib/ that sets it, so one run names them all.
MISSING_SETTINGS=()
collect_missing_settings() {  # file key...
  local file="$1" key
  shift
  for key in "$@"; do
    [[ -n "${!key:-}" && "${!key}" != "<"*">" ]] || MISSING_SETTINGS+=("$key ($file)")
  done
}

# Stops when collect_missing_settings found any, listing every one of them.
require_collected_settings() {
  [ "${#MISSING_SETTINGS[@]}" -eq 0 ] && return
  echo "Fill in these settings under scripts/lib/, then run the script again:" >&2
  printf '  %s\n' "${MISSING_SETTINGS[@]}" >&2
  exit 1
}

require_docker() {
  docker info >/dev/null 2>&1 \
    || { echo "Docker is not reachable; start it and retry." >&2; exit 1; }
}

# The callers registry on this machine: A2A_CALLERS_FILE when stack-params.sh sets it, else the
# file tools/register-caller.sh writes by default, resolved against the repo.
callers_file() {
  local file="${A2A_CALLERS_FILE:-allowed-callers.yaml}"
  [[ "$file" = /* ]] || file="$ROOT/$file"
  printf '%s' "$file"
}

# Compose copies the registry's content into every replica rather than bind-mounting the file,
# since a bind mount names a path on the daemon's machine, which on the EC2 target is not this
# one. Its digest labels the replicas, so a changed registry recreates them on the next deploy.
# Only a stack with access off may run without a registry; its content is then empty.
export_callers_registry() {
  local file
  file="$(callers_file)"
  A2A_CALLERS_YAML=""
  if [[ -f "$file" ]]; then A2A_CALLERS_YAML="$(<"$file")"; fi
  A2A_CALLERS_DIGEST="$(sha256sum <<<"$A2A_CALLERS_YAML" | cut -d' ' -f1)"
  export A2A_CALLERS_YAML A2A_CALLERS_DIGEST
}

# Compose reads the ${...} values and the keys each service lists in its environment from this
# shell, so the settings are loaded first. A replica runs as the caller on this machine, so the
# files it writes into the statements mount are theirs. On the EC2 target the card advertises the
# stack's CloudFront address, which resolve_ec2_host of lib/ec2.sh sets.
compose() {
  load_settings
  export_callers_registry
  HOST_UID="$(id -u)"
  HOST_GID="$(id -g)"
  export HOST_UID HOST_GID
  if [[ " ${COMPOSE_FILES[*]} " == *" $EC2_COMPOSE_FILE "* ]]; then export EC2_URL; fi
  local file
  local -a files=()
  for file in "${COMPOSE_FILES[@]}"; do files+=(-f "$file"); done
  (cd "$ROOT" && docker compose "${files[@]}" "$@")
}

# Waits up to about a minute until the URL answers with any HTTP status.
wait_for_http() {  # url
  curl -s --retry 60 --retry-all-errors --retry-delay 1 --max-time 2 -o /dev/null "$1"
}

# With access required the agent refuses to start without a registered caller, so the registry
# is checked before any launch.
require_callers_file() {
  [ "${A2A_AUTH_REQUIRED:-true}" = false ] && return 0
  local file
  file="$(callers_file)"
  [ -f "$file" ] || { echo "No A2A caller registered ($file is missing); register one first:" \
    " ./scripts/tools/register-caller.sh --help" >&2; exit 1; }
}

# Docker turns a missing mount source into a root-owned directory the agent, running as the
# caller, cannot write uploads into, so the statements root is created first. A relative path is
# resolved against the repo, as compose resolves the mount source.
ensure_statements_dir() {
  local dir="${STATEMENTS_DIR:?set STATEMENTS_DIR in scripts/lib/stack-params.sh}"
  [[ "$dir" = /* ]] || dir="$ROOT/$dir"
  mkdir -p "$dir"
}

# The name a caller's operator registers this agent under.
AGENT_NAME=cal

# The URLs the hand-over names: on the EC2 target both are the stack's CloudFront address; on
# this machine the page is on EDGE_HOST_PORT and the card advertises AGENT_URL, or the agent's own
# default when it is unset.
page_url() { echo "${EC2_URL:-http://localhost:${EDGE_HOST_PORT}}"; }
advertised_url() { echo "${EC2_URL:-${AGENT_URL:-$(page_url)}}"; }

# The four values a caller's operator registers this agent with. tools/register-caller.sh prints
# them with the secret it minted; deploy.sh repeats them once the agent is up. A localhost card
# reaches only a caller on this host outside Docker, so that case is flagged while the value can
# change.
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
      "to http://host.docker.internal:$EDGE_HOST_PORT in scripts/lib/stack-params.sh before" \
      "handing the URL over."
  fi
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
