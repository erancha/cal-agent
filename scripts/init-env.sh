#!/usr/bin/env bash
#
# Create the gitignored settings files under scripts/lib/ (secrets.sh, params.sh and
# aws-config.sh) from their .example.sh files. An existing file is kept unless --force.
#
#   ./scripts/init-env.sh             # create each file that is missing
#   ./scripts/init-env.sh --force     # replace every file, hand-filled keys included
#
# Nothing is generated: AUTH_CLIENT_ID of params.sh and LLM_API_KEY of secrets.sh stay blank for
# you to fill in (docs/sign-in.md for the first), and params.sh sets LLM_MODEL to
# anthropic:claude-haiku-5-5. Each file is readable by its owner only. The secret of each A2A
# caller is minted by ./scripts/tools/register-caller.sh, not here. Then run ./scripts/deploy.sh.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

FORCE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --force)   FORCE=1 ;;
    -h|--help) print_help; exit 0 ;;
    *) echo "Usage: ./scripts/init-env.sh [--force]" >&2; exit 2 ;;
  esac
  shift
done

# Each new file is written beside its target and renamed over it only when every draft is
# complete, so a failure leaves no partial file. mktemp creates a draft readable by the owner
# only, as the files hold secrets.
drafts=()
trap 'rm -f "${drafts[@]}"' EXIT
draft_of() {  # target; prints the draft's path, or nothing when the target is kept
  local target="$1" draft
  if [ -f "$target" ] && [ "$FORCE" -eq 0 ]; then
    echo "${target#"$ROOT"/} already exists; left as it is (--force overwrites it)." >&2
    return
  fi
  draft="$(mktemp "$target.XXXXXX")"
  cat "${target%.sh}.example.sh" > "$draft"
  printf '%s' "$draft"
}

secrets_draft="$(draft_of "$SECRETS_FILE")"
[ -z "$secrets_draft" ] || drafts+=("$secrets_draft")
params_draft="$(draft_of "$PARAMS_FILE")"
[ -z "$params_draft" ] || drafts+=("$params_draft")
# Only deploy.sh --ec2 reads it, so it may stay unfilled on a machine that deploys locally.
aws_draft="$(draft_of "$AWS_CONFIG_FILE")"
[ -z "$aws_draft" ] || drafts+=("$aws_draft")

[ -z "$secrets_draft" ] || mv "$secrets_draft" "$SECRETS_FILE"
[ -z "$params_draft" ] || mv "$params_draft" "$PARAMS_FILE"
[ -z "$aws_draft" ] || mv "$aws_draft" "$AWS_CONFIG_FILE"
[ -z "$secrets_draft" ] || echo "Created scripts/lib/secrets.sh."
[ -z "$params_draft" ] || echo "Created scripts/lib/params.sh."
[ -z "$aws_draft" ] || echo "Created scripts/lib/aws-config.sh (needed for deploy.sh --ec2 only)."
# The reminder is for a file this run created; a kept file was filled in before.
if [ -n "$secrets_draft$params_draft" ]; then
  echo "Fill in the settings left blank (docs/sign-in.md for AUTH_CLIENT_ID);" \
       "./scripts/deploy.sh names each one it still needs."
  echo "Register each A2A caller: ./scripts/tools/register-caller.sh --help"
fi
