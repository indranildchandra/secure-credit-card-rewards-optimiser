#!/bin/bash
# Claude Code SessionStart hook.
#
# On Claude Code on the web (remote) sessions, prepare the Python environment so
# tests and linters run out-of-the-box. Delegates to the shared bootstrap so all
# AI coding tools set the repo up identically. Local sessions are skipped (the
# developer already has their environment).
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

exec "${CLAUDE_PROJECT_DIR:-.}/scripts/setup-env.sh"
