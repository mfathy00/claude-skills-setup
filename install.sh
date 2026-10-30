#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
DEST="${HOME}/.claude/skills/delegate"
mkdir -p "$(dirname "$DEST")"
rm -rf "$DEST"
cp -R "$ROOT/.claude/skills/delegate" "$DEST"
chmod +x "$DEST/scripts/"*.sh 2>/dev/null || true
echo "Installed to $DEST"
echo "In Claude Code, run: /delegate"
