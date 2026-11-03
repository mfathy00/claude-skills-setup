#!/usr/bin/env bash
# Fixed read-only Git views for the lead to supply to a shell-less reviewer.
set -euo pipefail
if [[ $# != 1 ]]; then
  echo 'Usage: bash review-git.sh status|diff|staged|log' >&2
  exit 2
fi
# Use system Git, reject executable filters before every view, and never lazily
# fetch missing promisor objects or inherit Git configuration/environment overrides.
GIT_BIN="$(PATH=/usr/bin:/bin command -v git)" || { echo 'System Git not found.' >&2; exit 2; }
git_command() {
  env -i PATH=/usr/bin:/bin LC_ALL=C GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null \
    GIT_TERMINAL_PROMPT=0 GIT_NO_LAZY_FETCH=1 GIT_ALLOW_PROTOCOL= GIT_NO_REPLACE_OBJECTS=1 \
    "$GIT_BIN" --no-pager --no-optional-locks -c core.fsmonitor=false -c core.hooksPath=/dev/null \
    -c core.untrackedCache=false -c protocol.allow=never -c color.ui=false "$@"
}
git_read() {
  local code=0
  git_command config --includes --name-only --get-regexp '^filter\..*\.(clean|process|smudge)$' >/dev/null || code=$?
  [[ "$code" == 1 ]] || { echo 'Git filters configured or configuration unreadable; inspection refused.' >&2; return 2; }
  git_command "$@"
}
case "$1" in
  status) git_read status --short --untracked-files=normal --ignore-submodules=all ;;
  diff) git_read diff --no-ext-diff --no-textconv --ignore-submodules=all -- ;;
  staged) git_read diff --cached --no-ext-diff --no-textconv --ignore-submodules=all -- ;;
  log) git_read log -20 --format='%h %s' --no-decorate --no-show-signature ;;
  *) echo 'Choose only status, diff, staged or log; arbitrary Git options are not accepted.' >&2; exit 2 ;;
esac
