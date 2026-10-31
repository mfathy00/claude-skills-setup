#!/usr/bin/env bash
# Validate an explicitly approved handoff, then invoke Codex once.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SCRIPT_DIR/handoff.py" launch "$@"
