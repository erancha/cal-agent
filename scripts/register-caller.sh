#!/usr/bin/env bash
#
# Register an A2A caller, or replace its entry: the secret it will present in X-Caller-Secret,
# minted here and printed once, and the Google OAuth client whose ID tokens it forwards. Writes
# allowed-callers.yaml beside .env (mode 600) in the shape the agent reads:
#
#   callers:
#     - name: <caller>
#       shared_secret: <secret>
#       client_id: <Google OAuth client id>
#
#   ./scripts/register-caller.sh --name <caller> --client-id <client id>   # mints the secret
#   ./scripts/register-caller.sh ... --secret <secret>   # registers a given secret (tests)
#   ./scripts/register-caller.sh ... --file <path>       # another file (A2A_CALLERS_FILE)
#
# The secret is shown once and never again, printed with this agent's name and URLs: the four
# values the caller's operator records. start.sh repeats the public three once the agent is up. A
# caller with that name is replaced; other callers are kept. Removing an entry revokes the caller;
# the agent reads the file at startup, so restart a running one after a change.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"
# .env is optional here: it only supplies the URLs the hand-over names, which otherwise default to
# the agent's own.
[ -f "$ROOT/.env" ] && load_env

NAME="" SECRET="" CLIENT_ID="" FILE="$DEFAULT_CALLERS_FILE"
while [ $# -gt 0 ]; do
  case "$1" in
    --name)      NAME="${2:?--name needs a value}"; shift ;;
    --secret)    SECRET="${2:?--secret needs a value}"; shift ;;
    --client-id) CLIENT_ID="${2:?--client-id needs a value}"; shift ;;
    --file)      FILE="${2:?--file needs a path}"; shift ;;
    -h|--help)   print_help; exit 0 ;;
    *) echo "Usage: ./scripts/register-caller.sh --name N --client-id C [--secret S] [--file F]" >&2
       exit 2 ;;
  esac
  shift
done
[ -n "$NAME" ] && [ -n "$CLIENT_ID" ] \
  || { echo "--name and --client-id are required." >&2; exit 2; }
MINTED=0
if [ -z "$SECRET" ]; then
  # url-safe base64 of 32 random bytes: the alphabet the scalar check below admits.
  SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  MINTED=1
fi
# The file is rewritten from these values, so each must be a plain YAML scalar.
for value in "$NAME" "$SECRET" "$CLIENT_ID"; do
  [[ "$value" =~ ^[A-Za-z0-9_.-]+$ ]] \
    || { echo "Values may contain only letters, digits, '_', '.' and '-'." >&2; exit 2; }
done

clear_callers_dir "$FILE"
umask 077
# The secret reaches Python through the environment, not the command line, so no process listing
# shows it.
CALLER_SECRET="$SECRET" python3 - "$FILE" "$NAME" "$CLIENT_ID" <<'PY'
import os, re, sys

path, name, client_id = sys.argv[1:]
secret = os.environ["CALLER_SECRET"]
ENTRY = re.compile(r"^\s*- name: (\S+)$")
FIELD = re.compile(r"^\s*(shared_secret|client_id): (\S+)$")

# Reads back only the shape this script writes; anything else is refused rather than guessed at.
callers = []
if os.path.exists(path):
    current = None
    for number, line in enumerate(open(path, encoding="utf-8"), 1):
        line = line.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#") or line == "callers:":
            continue
        if entry := ENTRY.match(line):
            current = {"name": entry.group(1)}
            callers.append(current)
        elif (field := FIELD.match(line)) and current is not None:
            current[field.group(1)] = field.group(2)
        else:
            sys.exit(f"{path}:{number}: not a line register-caller.sh writes")
    for caller in callers:
        if set(caller) != {"name", "shared_secret", "client_id"}:
            sys.exit(f"{path}: entry {caller['name']} lacks shared_secret or client_id")

callers = [c for c in callers if c["name"] != name]
callers.append({"name": name, "shared_secret": secret, "client_id": client_id})
lines = ["# Registered A2A callers of this cal-agent; written by scripts/register-caller.sh.",
         "callers:"]
for caller in callers:
    lines += [f"  - name: {caller['name']}",
              f"    shared_secret: {caller['shared_secret']}",
              f"    client_id: {caller['client_id']}"]
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as out:
    out.write("\n".join(lines) + "\n")
os.chmod(tmp, 0o600)
os.replace(tmp, path)
PY
if [ "$MINTED" -eq 1 ]; then
  echo "Registered $NAME in $FILE."
  print_handover "$NAME's operator" "$SECRET"
  echo "The secret is shown once and never again."
else
  echo "Registered $NAME in $FILE with the given secret."
  print_handover "$NAME's operator" "the one given"
fi
echo "An agent already running reads the file at its next start."
