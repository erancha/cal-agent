#!/usr/bin/env bash
#
# Recompile requirements.txt, the exact pins the image installs, from pyproject.toml.
#
#   ./scripts/lock.sh
#
# pip-compile resolves the markers of the Python it runs on, so the lock is compiled inside the
# same python image the Dockerfile builds on, whatever Python this machine has. The container runs
# as the current user so the rewritten lock stays theirs. Extras are resolved into plain pins
# because the test venv takes the lock as a pip constraints file, which admits no extras. Run it
# after editing the dependency list.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

case "${1:-}" in -h|--help) print_help; exit 0 ;; "") ;; *) print_help >&2; exit 2 ;; esac
require_docker

# The runtime image is the Dockerfile's, read from it rather than repeated here.
PYTHON_IMAGE="$(sed -n 's/^FROM \(python:[^ ]*\).*/\1/p' "$ROOT/Dockerfile")"
[ -n "$PYTHON_IMAGE" ] || { echo "no python image in $ROOT/Dockerfile" >&2; exit 1; }

echo "Compiling requirements.txt in $PYTHON_IMAGE..."
# A non-root pip installs into the user site, so pip-compile is reached through its module.
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
  --mount "type=bind,source=$ROOT,target=/repo" --workdir /repo "$PYTHON_IMAGE" \
  sh -ec 'pip install --quiet --disable-pip-version-check --no-warn-script-location pip-tools \
          && python -m piptools compile --quiet --strip-extras \
               --output-file=requirements.txt pyproject.toml'
