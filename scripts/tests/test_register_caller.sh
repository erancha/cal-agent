#!/usr/bin/env bash
# Verifies register-caller.sh: without --secret it mints one and prints it once, with the agent's
# name and URLs the caller's operator records; with --secret it registers the given one; an entry
# is replaced by name and others are kept; the file is mode 600 and the minted secret appears in
# nothing but that file and the one hand-over line; an empty directory at the path, as a Docker
# start without the file leaves, is replaced by the file, and a directory with content is refused
# by name.
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
FILE="$WORK/allowed-callers.yaml"
fail() { echo "FAIL: $*" >&2; exit 1; }
register() { bash "$SCRIPTS_DIR/register-caller.sh" --file "$FILE" "$@"; }

out="$(register --name test-caller --client-id 123.apps.googleusercontent.com)"
secret="$(sed -n 's/^  secret: *//p' <<<"$out")"
[[ "$secret" =~ ^[A-Za-z0-9_-]{43}$ ]] || fail "no minted secret in: $out"
grep -q "to test-caller's operator:" <<<"$out" || fail "hand-over not addressed: $out"
grep -qE "name: +cal$" <<<"$out" || fail "agent name not printed: $out"
grep -qE "A2A URL: +http" <<<"$out" || fail "advertised URL not printed: $out"
grep -qE "statements page: +http://localhost:" <<<"$out" || fail "page URL not printed: $out"
grep -q "shared_secret: $secret" "$FILE" || fail "minted secret not written"
[ "$(grep -c -- "$secret" <<<"$out")" = "1" ] || fail "minted secret shown more than once: $out"
[ "$(grep -rl -- "$secret" "$WORK")" = "$FILE" ] || fail "minted secret written beyond the file"
[ "$(stat -c %a "$FILE")" = "600" ] || fail "callers file is not mode 600"

register --name other --secret s3cret-9 --client-id 999.apps.googleusercontent.com >/dev/null
register --name test-caller --secret s3cret-1 --client-id 123.apps.googleusercontent.com \
  >/dev/null
[ "$(grep -c 'name:' "$FILE")" = "2" ] || fail "entry not replaced by name"
grep -q 'shared_secret: s3cret-1' "$FILE" || fail "given secret not written"
grep -q 'shared_secret: s3cret-9' "$FILE" || fail "other caller lost"
if grep -q "shared_secret: $secret" "$FILE"; then fail "replaced entry still holds the old secret"; fi

mkdir "$WORK/empty.yaml"
register --file "$WORK/empty.yaml" --name x --client-id 1.apps.googleusercontent.com >/dev/null \
  || fail "an empty directory at the path was not replaced"
[ -f "$WORK/empty.yaml" ] || fail "callers file not written in place of the empty directory"
mkdir "$WORK/full.yaml" && touch "$WORK/full.yaml/keep"
if err="$(register --file "$WORK/full.yaml" --name x --client-id 1.apps.googleusercontent.com 2>&1)"
then fail "a directory with content was not refused"; fi
grep -q "directory with content" <<<"$err" || fail "refusal does not name the cause: $err"

echo "test_register_caller: all checks passed"
