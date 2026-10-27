#!/usr/bin/env bash
#
# Docker Compose helper for the stack: teardown, logs, status. Bringing it up is start.sh's job.
#
#   ./scripts/docker-helper.sh --stop [--volumes]
#       Stop and remove the stack's containers and network. The Redis volume, which holds the
#       paused tasks, is kept unless --volumes (alias -v) removes it for a clean start.
#   ./scripts/docker-helper.sh --logs [-e] [service...]
#       Follow logs (last 200 lines); -e shows only errors/exceptions. Name services (redis,
#       cal-agent, edge) after the options to show only their logs.
#   ./scripts/docker-helper.sh --ps               # container status
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

do_stop() {
  local -a down=(down --remove-orphans)
  while [ $# -gt 0 ]; do
    case "$1" in
      -v|--volumes) down+=(-v) ;;
      *) echo "Unknown --stop option '$1'" >&2; exit 1 ;;
    esac
    shift
  done
  compose "${down[@]}"
}

mode="${1:-}"
case "$mode" in
  -h|--help) print_help; exit 0 ;;
  "")        print_help; exit 1 ;;
esac
shift
case "$mode" in
  --stop)
    for arg in "$@"; do
      case "$arg" in -v|--volumes) ;; *) echo "Unknown --stop option '$arg'" >&2; exit 1 ;; esac
    done ;;
  --ps)
    [ $# -eq 0 ] || { echo "$mode takes no arguments (got: $*)" >&2; exit 1; } ;;
  --logs) ;;
  *) echo "Unknown command: $mode (expected --stop | --logs | --ps)" >&2; exit 1 ;;
esac
require_docker
case "$mode" in
  --stop) do_stop "$@" ;;
  --logs)
    if [ "${1:-}" = "-e" ]; then
      shift
      compose logs -f --tail=200 "$@" | grep -Eai '(error|exception|fatal)'
    else compose logs -f --tail=200 "$@"; fi ;;
  --ps)   compose ps ;;
esac
