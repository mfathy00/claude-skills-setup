#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
bash -n "$ROOT/install.sh" "$ROOT/tests/run.sh" "$ROOT/.claude/skills/delegate/scripts/"*.sh
(cd "$ROOT" && python3 -m unittest discover -s "$ROOT/tests" -p 'test_*.py' -v)
