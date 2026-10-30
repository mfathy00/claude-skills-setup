#!/usr/bin/env bash
# Ensure handoff exists, then start Codex with it as the seed prompt.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT"

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HANDOFF=".claude/handoff-to-codex.md"

if [[ ! -f "${HANDOFF}" ]]; then
  bash "${SKILL_DIR}/scripts/write-handoff.sh" --reason "manual-launch"
fi

PROMPT="Read ${HANDOFF} carefully. Continue from 'Next concrete steps'. Do not redo 'Done already'. Keep the Goal as the definition of done. When finished, write a short summary to .claude/handoff-from-codex.md."

if ! command -v codex >/dev/null 2>&1; then
  echo "codex not found on PATH."
  echo "Handoff is ready at: ${ROOT}/${HANDOFF}"
  echo "Install/open Codex, then run:"
  echo "  codex $(printf %q "${PROMPT}")"
  exit 1
fi

echo "Starting Codex with handoff from ${HANDOFF} ..."
exec codex "${PROMPT}"
