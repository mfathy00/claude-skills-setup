#!/usr/bin/env bash
# Write .claude/handoff-to-codex.md with live git context.
set -euo pipefail

REASON="unspecified"
GOAL=""
OUT_DIR=".claude"
OUT_FILE="${OUT_DIR}/handoff-to-codex.md"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --reason) REASON="${2:-}"; shift 2 ;;
    --goal) GOAL="${2:-}"; shift 2 ;;
    --out) OUT_FILE="${2:-}"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

mkdir -p "$(dirname "$OUT_FILE")"

BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
HEAD="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  if [[ -n "$(git status --porcelain 2>/dev/null)" ]]; then
    TREE="dirty"
  else
    TREE="clean"
  fi
  STATUS="$(git status -sb 2>/dev/null || true)"
  DIFF_STAT="$(git diff --stat HEAD 2>/dev/null || true)"
else
  TREE="not-a-git-repo"
  STATUS="(not a git repository)"
  DIFF_STAT=""
fi

TS="$(date -Iseconds 2>/dev/null || date)"

{
  echo "# Handoff: Claude Code → Codex"
  echo
  echo "- Written: ${TS}"
  echo "- Reason: ${REASON}"
  echo "- Claude usage: session=unknown weekly=unknown (fill from /usage if known)"
  echo "- Complexity score: (fill from skill)"
  echo "- Last Claude model: (fill from skill)"
  echo "- Branch: ${BRANCH}"
  echo "- HEAD: ${HEAD}"
  echo "- Working tree: ${TREE}"
  echo
  echo "## Goal"
  if [[ -n "${GOAL}" ]]; then
    echo "${GOAL}"
  else
    echo "(describe what done looks like)"
  fi
  echo
  echo "## Done already"
  echo "- (fill from session)"
  echo
  echo "## In progress"
  echo "- (fill from session)"
  echo
  echo "### Git status"
  echo '```'
  echo "${STATUS}"
  echo '```'
  if [[ -n "${DIFF_STAT}" ]]; then
    echo
    echo "### Diff stat"
    echo '```'
    echo "${DIFF_STAT}"
    echo '```'
  fi
  echo
  echo "## Next concrete steps (ordered)"
  echo "1. (fill from session)"
  echo
  echo "## Key files"
  echo "- (path — why)"
  echo
  echo "## Commands already run (and results)"
  echo "- (fill from session)"
  echo
  echo "## Constraints / do not"
  echo "- Do not redo work listed under Done already."
  echo
  echo "## Open questions"
  echo "- (none yet)"
} > "${OUT_FILE}"

echo "Wrote ${OUT_FILE}"
