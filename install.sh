#!/usr/bin/env bash
# Install only the bundled skill and four agents; preserve everything else.
set -euo pipefail
umask 077
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
DEST="${HOME:?HOME must be set}/.claude"
REPLACE=0
usage() { echo 'Usage: bash install.sh [--dest /path/to/.claude] [--replace]'; }
fail() { echo "install: $*" >&2; exit 1; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dest) [[ $# -ge 2 && -n "$2" ]] || fail '--dest needs a path'; DEST="$2"; shift 2 ;;
    --replace) REPLACE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; fail "Unknown argument: $1" ;;
  esac
done
command -v python3 >/dev/null || fail 'Python 3 is required for the handoff helpers.'
python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' || fail 'Python 3.9+ is required.'

# Validate the whole source before creating or changing destination files.
items=(skills/delegate agents/delegate-explorer.md agents/delegate-implementer.md agents/delegate-reviewer.md agents/delegate-tester.md)
required=(skills/delegate/SKILL.md skills/delegate/templates/delegate-plan.md skills/delegate/scripts/write-handoff.sh skills/delegate/scripts/handoff-to-codex.sh skills/delegate/scripts/handoff.py skills/delegate/scripts/review-git.sh "${items[@]:1}")
for rel in "${required[@]}"; do
  [[ -f "$ROOT/.claude/$rel" && -s "$ROOT/.claude/$rel" ]] || fail "Missing or empty source: $rel"
done
[[ -z "$(find "$ROOT/.claude/skills/delegate" "$ROOT/.claude/agents" -type l -print)" ]] || fail 'Source symlinks are not supported.'

# Refuse symlinked destination ancestors rather than writing through them.
DEST="$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$DEST")"
[[ "$DEST" != / && "$DEST" != "$ROOT/.claude" ]] || fail 'Choose a destination other than / or the source .claude directory.'
p="$DEST"
while [[ "$p" != / ]]; do
  [[ ! -L "$p" ]] || fail "Symlinked destination: $p"
  p="$(dirname "$p")"
done
for rel in skills agents .delegate-backups "${items[@]}"; do
  [[ ! -L "$DEST/$rel" ]] || fail "Symlinked destination: $rel"
done
mkdir -p "$DEST"
LOCK="$DEST/.delegate-install.lock"
mkdir "$LOCK" 2>/dev/null || fail "Another install may be running: $LOCK (inspect before removing a stale lock)."
TX=""
changed=()
rollback() {
  code=$?
  trap - EXIT INT TERM
  if [[ $code -ne 0 && -n "$TX" ]]; then
    echo "Install failed; restoring previous files. Recovery files: $TX" >&2
    for ((i=${#changed[@]}-1; i>=0; i--)); do
      rel="${changed[$i]}"
      # A surviving staged item means installation never completed. If no
      # backup exists either, the old target was never moved: leave it alone.
      if [[ -e "$TX/staged/$rel" && ! -e "$TX/before/$rel" ]]; then continue; fi
      if [[ -e "$DEST/$rel" || -L "$DEST/$rel" ]]; then
        if ! mkdir -p "$TX/failed/$(dirname "$rel")" || ! mv "$DEST/$rel" "$TX/failed/$rel"; then
          echo "WARNING: could not preserve failed $rel; restore manually from $TX/before" >&2
          continue
        fi
      fi
      if [[ -e "$TX/before/$rel" || -L "$TX/before/$rel" ]]; then
        mv "$TX/before/$rel" "$DEST/$rel" || echo "WARNING: restore $rel manually from $TX/before" >&2
      fi
    done
  fi
  rmdir "$LOCK" 2>/dev/null || true
  exit "$code"
}
trap rollback EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
# Recompute conflicts under the lock: a competing installer may have finished
# after the earlier source/path preflight but before we obtained the lock.
changes=()
for rel in "${items[@]}"; do
  if [[ -e "$DEST/$rel" ]]; then
    [[ -z "$(find "$DEST/$rel" -type l -print)" ]] || fail "Symlinked destination content: $rel"
    if diff -qr "$ROOT/.claude/$rel" "$DEST/$rel" >/dev/null 2>&1; then continue; fi
    [[ $REPLACE == 1 ]] || fail "Existing $rel differs. Review it, then use --replace to preserve it in a backup and install the new copy."
  fi
  changes+=("$rel")
done
[[ ${#changes[@]} -gt 0 ]] || { echo 'Already installed; no changes.'; exit 0; }
mkdir -p "$DEST/.delegate-backups"
TX="$(mktemp -d "$DEST/.delegate-backups/install-XXXXXXXX")"
mkdir -p "$TX/staged/skills" "$TX/staged/agents" "$TX/before/skills" "$TX/before/agents"
for rel in "${changes[@]}"; do cp -pR "$ROOT/.claude/$rel" "$TX/staged/$rel"; done
if [[ -d "$TX/staged/skills/delegate" ]]; then chmod +x "$TX/staged/skills/delegate/scripts/"*.sh; fi
mkdir -p "$DEST/skills" "$DEST/agents"
for rel in "${changes[@]}"; do
  # Register before either move so a signal between them can be rolled back.
  changed+=("$rel")
  if [[ -e "$DEST/$rel" ]]; then mv "$DEST/$rel" "$TX/before/$rel"; fi
  mv "$TX/staged/$rel" "$DEST/$rel"
done
printf '%s\n' "${changes[@]}" > "$TX/installed-paths.txt"
printf 'Installed /delegate in %s\nBackup / recovery directory: %s\nIn Claude Code: /delegate <your job>\n' "$DEST" "$TX"
