#!/usr/bin/env bash
# Fixed read-only Git views for the lead to supply to a shell-less reviewer.
set -euo pipefail
if [[ $# != 1 ]]; then
  echo 'Usage: bash review-git.sh status|diff|staged|log' >&2
  exit 2
fi
# Do not invoke repository-configured monitors, diff drivers, pagers or signers.
# Optional locks are disabled so status does not refresh/write the index.
git_read() {
  GIT_OPTIONAL_LOCKS=0 git --no-pager -c core.fsmonitor=false -c color.ui=false "$@"
}
case "$1" in
  status) git_read status --short --untracked-files=normal ;;
  diff) git_read diff --no-ext-diff --no-textconv --ignore-submodules=all -- ;;
  staged) git_read diff --cached --no-ext-diff --no-textconv --ignore-submodules=all -- ;;
  log) git_read log -20 --format='%h %s' --no-decorate --no-show-signature ;;
  *) echo 'Choose only status, diff, staged or log; arbitrary Git options are not accepted.' >&2; exit 2 ;;
esac
