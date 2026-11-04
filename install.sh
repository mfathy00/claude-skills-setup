#!/usr/bin/env bash
# Install only the bundled skill and four agents; preserve everything else.
set -euo pipefail
umask 077
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
DEST="${HOME:?HOME must be set}/.claude"
REPLACE=0
CLIENT=claude
DEST_SET=0
SOURCE="$ROOT/.claude"
SOURCE_TMP=""
cleanup_source() { [[ -z "$SOURCE_TMP" ]] || rm -rf "$SOURCE_TMP"; }
trap cleanup_source EXIT
usage() { echo 'Usage: bash install.sh [--client claude|codex] [--dest /path/to/client-home] [--replace]'; }
fail() { echo "install: $*" >&2; exit 1; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dest) [[ $# -ge 2 && -n "$2" ]] || fail '--dest needs a path'; DEST="$2"; DEST_SET=1; shift 2 ;;
    --client) [[ $# -ge 2 ]] || fail '--client needs claude or codex'; CLIENT="$2"; shift 2 ;;
    --replace) REPLACE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; fail "Unknown argument: $1" ;;
  esac
done
[[ "$CLIENT" == claude || "$CLIENT" == codex ]] || fail '--client must be claude or codex'
if [[ "$CLIENT" == codex && "$DEST_SET" == 0 ]]; then DEST="$HOME/.agents"; fi
command -v python3 >/dev/null || fail 'Python 3 is required for the handoff helpers.'
python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' || fail 'Python 3.9+ is required.'

# Validate the whole source before creating or changing destination files.
items=(skills/delegate agents/delegate-explorer.md agents/delegate-implementer.md agents/delegate-reviewer.md agents/delegate-tester.md)
required=(skills/delegate/SKILL.md skills/delegate/templates/delegate-plan.md skills/delegate/scripts/write-handoff.sh skills/delegate/scripts/handoff-to-codex.sh skills/delegate/scripts/handoff.py skills/delegate/scripts/review-git.sh skills/delegate/scripts/superagent.sh skills/delegate/runtime/launch.py skills/delegate/runtime/superagent/__init__.py skills/delegate/runtime/superagent/__main__.py skills/delegate/runtime/superagent/cli.py skills/delegate/runtime/superagent/state.py skills/delegate/runtime/superagent/runtime.py skills/delegate/runtime/superagent/adapters.py skills/delegate/runtime/superagent/safety.py skills/delegate/runtime/superagent/workspace.py skills/delegate/runtime/superagent/checks_worker.py skills/delegate/runtime/superagent/factory.py skills/delegate/runtime/superagent/migration.py "${items[@]:1}")
if [[ "$CLIENT" == codex ]]; then
  [[ -s "$ROOT/.agents/skills/superagent/SKILL.md" ]] || fail 'Missing Codex skill source.'
  [[ -z "$(find "$ROOT/.agents/skills/superagent" "$ROOT/.claude/skills/delegate/runtime" -type l -print)" ]] || fail 'Source symlinks are not supported.'
  # Build a passive self-contained payload; use the same transaction/backup engine.
  SOURCE_TMP="$(mktemp -d "${TMPDIR:-/tmp}/superagent-install-source-XXXXXXXX")"
  SOURCE="$SOURCE_TMP"
  mkdir -p "$SOURCE/skills/superagent/scripts"
  cp "$ROOT/.agents/skills/superagent/SKILL.md" "$SOURCE/skills/superagent/SKILL.md"
  cp "$ROOT/.claude/skills/delegate/scripts/superagent.sh" "$SOURCE/skills/superagent/scripts/superagent.sh"
  cp -pR "$ROOT/.claude/skills/delegate/runtime" "$SOURCE/skills/superagent/runtime"
  items=(skills/superagent)
  required=(skills/superagent/SKILL.md skills/superagent/scripts/superagent.sh skills/superagent/runtime/launch.py)
  for module in __init__ __main__ cli state runtime adapters safety workspace checks_worker factory migration; do
    required+=("skills/superagent/runtime/superagent/$module.py")
  done
fi
for rel in "${required[@]}"; do
  [[ -f "$SOURCE/$rel" && -s "$SOURCE/$rel" ]] || fail "Missing or empty source: $rel"
done
for rel in "${items[@]}"; do
  [[ -z "$(find "$SOURCE/$rel" -type l -print)" ]] || fail 'Source symlinks are not supported.'
done

# Refuse symlinked destination ancestors rather than writing through them.
DEST="$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$DEST")"
[[ "$DEST" != / && "$DEST" != "$ROOT/.claude" && "$DEST" != "$ROOT/.agents" ]] || fail 'Choose a destination other than / or the source .claude directory.'
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
  cleanup_source
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
    if diff -qr "$SOURCE/$rel" "$DEST/$rel" >/dev/null 2>&1; then continue; fi
    [[ $REPLACE == 1 ]] || fail "Existing $rel differs. Review it, then use --replace to preserve it in a backup and install the new copy."
  fi
  changes+=("$rel")
done
[[ ${#changes[@]} -gt 0 ]] || { echo 'Already installed; no changes.'; exit 0; }
mkdir -p "$DEST/.delegate-backups"
TX="$(mktemp -d "$DEST/.delegate-backups/install-XXXXXXXX")"
mkdir -p "$TX/staged/skills" "$TX/staged/agents" "$TX/before/skills" "$TX/before/agents"
for rel in "${changes[@]}"; do cp -pR "$SOURCE/$rel" "$TX/staged/$rel"; done
for rel in "${changes[@]}"; do
  if [[ -d "$TX/staged/$rel/scripts" ]]; then chmod +x "$TX/staged/$rel/scripts/"*.sh; fi
done
mkdir -p "$DEST/skills" "$DEST/agents"
for rel in "${changes[@]}"; do
  # Register before either move so a signal between them can be rolled back.
  changed+=("$rel")
  if [[ -e "$DEST/$rel" ]]; then mv "$DEST/$rel" "$TX/before/$rel"; fi
  mv "$TX/staged/$rel" "$DEST/$rel"
done
printf '%s\n' "${changes[@]}" > "$TX/installed-paths.txt"
if [[ "$CLIENT" == claude ]]; then
  printf 'Installed /delegate in %s\nBackup / recovery directory: %s\nIn Claude Code: /delegate <your job>\n' "$DEST" "$TX"
else
  printf 'Installed Codex superagent skill in %s\nBackup / recovery directory: %s\n' "$DEST" "$TX"
fi
