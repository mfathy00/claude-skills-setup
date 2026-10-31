#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
SKILL_DEST="${HOME}/.claude/skills/delegate"
AGENTS_DEST="${HOME}/.claude/agents"

mkdir -p "$(dirname "$SKILL_DEST")" "$AGENTS_DEST"
rm -rf "$SKILL_DEST"
cp -R "$ROOT/.claude/skills/delegate" "$SKILL_DEST"
chmod +x "$SKILL_DEST/scripts/"*.sh 2>/dev/null || true

for f in "$ROOT/.claude/agents/"delegate-*.md; do
  [[ -f "$f" ]] || continue
  cp "$f" "$AGENTS_DEST/$(basename "$f")"
done

echo "Installed skill → $SKILL_DEST"
echo "Installed agents → $AGENTS_DEST/delegate-*.md"
echo "In Claude Code: /delegate <your job>"
