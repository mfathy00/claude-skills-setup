#!/usr/bin/env bash
# Repo-local Codex entry point uses the same canonical runtime as /delegate.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd -P)"
exec bash "$ROOT/.claude/skills/delegate/scripts/superagent.sh" "$@"
