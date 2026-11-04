#!/usr/bin/env bash
# Exact bundled entry point; never eval arguments or discover user configuration.
set -euo pipefail
SKILL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
exec python3 -I -B "$SKILL/runtime/launch.py" "$@"
