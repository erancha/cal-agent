#!/usr/bin/env bash
# Keeps the gitignored settings files and their values out of git. Sourced by scripts/common.sh
# and by .githooks/pre-commit, never executed; expects ROOT, the repo's root folder.
#
# Core responsibilities:
# - SECRETS_FILES / PRIVATE_FILES / PUBLISHED_SETTINGS: which files hold secrets, which hold
#   private settings, and which of those settings hold an address that is public anyway
# - assert_secrets_untracked / assert_addresses_untracked: stop when git tracks such a file or a
#   tracked file holds one of its secrets or email addresses
# - source_checked_file: runs the check, sources the file and enables the repo's git hooks

# Settings a secrets file sets that are public, so a copy in a tracked file is no leak.
PUBLIC_SETTINGS=(AWS_DEFAULT_REGION)
# The gitignored files that hold secrets; aws-config.sh exists only where the stack is deployed
# to EC2.
SECRETS_FILES=("$ROOT/scripts/lib/secrets.sh" "$ROOT/scripts/lib/aws-config.sh")
# Gitignored files of private settings that are no secret: their other values may appear in git,
# but an email address they hold may not, unless PUBLISHED_SETTINGS names the setting holding it.
PRIVATE_FILES=("$ROOT/scripts/lib/params.sh")
# Settings of a private file whose address is public anyway, so a copy in a tracked file is no
# leak: LICENSE_CONTACT is the address the README and NOTICE give for a commercial license.
PUBLISHED_SETTINGS=(LICENSE_CONTACT)

die() { echo "ERROR: $*" >&2; exit 1; }

# Fatal unless git ignores <file>.
assert_gitignored() {
  git -C "$ROOT" check-ignore -q "$1" ||
    die "$1 is tracked or not gitignored; it must stay out of git"
}

# The names of the settings <file> sets (KEY=value, with or without export).
setting_names() { grep -oP '^(?:export )?\K\w+(?==)' "$1"; }

# Fatal when <value> appears in git's files: <scope> "worktree" scans the tracked files as they are
# on disk, "index" the staged snapshot a commit records. <label> names the value in the message,
# which never holds the value itself; further arguments are git grep options.
refuse_copy_in_git() {
  local scope="$1" label="$2" value="$3" options=(-F "${@:4}") status=0
  [[ "$scope" == index ]] && options+=(--cached)
  git -C "$ROOT" grep "${options[@]}" -q -e "$value" || status=$?
  case "$status" in
    0) die "$label appears in git ($scope):" \
           "$(git -C "$ROOT" grep "${options[@]}" -l -e "$value" | tr '\n' ' ')" ;;
    1) ;;
    *) die "git grep failed while scanning for $label" ;;
  esac
}

# Fatal when git tracks or would track <file>, or when the value of a non-public setting it sets
# appears in git's files. A setting still blank, or still its example's <placeholder>, holds
# nothing to leak and is skipped. <scope> as for refuse_copy_in_git.
assert_secrets_untracked() {
  local file="$1" scope="$2" name
  assert_gitignored "$file"
  (
    # shellcheck source=/dev/null
    source "$file"
    for name in $(setting_names "$file"); do
      [[ " ${PUBLIC_SETTINGS[*]} " == *" $name "* ]] && continue
      [[ -n "${!name}" && "${!name}" != "<"*">" ]] || continue
      refuse_copy_in_git "$scope" "The value of $name (from $file)" "${!name}"
    done
  ) || exit 1
}

# Fatal when git tracks or would track <file>, or when an email address one of its settings holds
# appears in git's files, ignoring case, unless it is the value of a setting PUBLISHED_SETTINGS
# names. <scope> as for refuse_copy_in_git.
assert_addresses_untracked() {
  local file="$1" scope="$2"
  assert_gitignored "$file"
  (
    local name found address published=" "
    local pattern='[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+'
    # shellcheck source=/dev/null
    source "$file"
    for name in "${PUBLISHED_SETTINGS[@]}"; do
      [[ -v "$name" ]] || die "PUBLISHED_SETTINGS names $name, which $file does not set"
      published+="${!name,,} "
    done
    for name in $(setting_names "$file"); do
      found="$(grep -oE "$pattern" <<<"${!name}")" || [[ $? -eq 1 ]] ||
        die "grep failed while reading the addresses of $name"
      for address in $found; do
        [[ "$published" == *" ${address,,} "* ]] && continue
        refuse_copy_in_git "$scope" "An address of $name (from $file)" "$address" -i
      done
    done
  ) || exit 1
}

# Sources <file> after <check> (assert_secrets_untracked or assert_addresses_untracked), and
# points git at the repo's hooks so the pre-commit hook applies the same check to every commit
# made from a checkout that holds the file.
source_checked_file() {  # file check
  local file="$1" check="$2"
  [[ -f "$file" ]] ||
    die "${file#"$ROOT"/} not found; create it first:  ./scripts/init-env.sh"
  "$check" "$file" worktree
  # shellcheck source=/dev/null
  source "$file"
  if [[ "$(git -C "$ROOT" config --default "" core.hooksPath)" != .githooks ]]; then
    git -C "$ROOT" config core.hooksPath .githooks
    # On stderr, so a caller that captures a script's output never reads this line.
    echo "Enabled the repo's git hooks (core.hooksPath=.githooks)." >&2
  fi
}
