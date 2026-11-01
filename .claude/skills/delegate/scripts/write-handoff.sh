#!/usr/bin/env bash
# Create a new, isolated handoff draft. Never overwrite an existing track.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SCRIPT_DIR/handoff.py" write "$@"
