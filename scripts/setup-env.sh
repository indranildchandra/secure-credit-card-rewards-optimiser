#!/bin/bash
# Shared, idempotent, non-interactive environment bootstrap.
#
# Every AI coding tool's session hook (.claude/, .gemini/, .cursor/) delegates to
# this one script, so "set up the repo" means the same thing everywhere. Safe to
# run by hand too:  ./scripts/setup-env.sh
#
# It creates the .adk_env virtualenv, installs dependencies (only when
# requirements change), and — when running under Claude Code — puts the venv on
# PATH for the session. It deliberately does NOT pull the Ollama model (that is
# large and handled by ./run.sh); this just makes tests, linters and imports work.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! command -v python3 >/dev/null 2>&1; then
  echo "setup-env: python3 not found; please install Python 3.9+." >&2
  exit 1
fi

# Create the virtualenv once; reuse the cached one afterwards.
if [ ! -d .adk_env ]; then
  python3 -m venv .adk_env
fi
# shellcheck disable=SC1091
source .adk_env/bin/activate

# Only (re)install when requirements.txt changes — keeps warm starts instant.
req_hash="$( (sha256sum requirements.txt 2>/dev/null || shasum -a 256 requirements.txt) | cut -d' ' -f1 )"
marker=".adk_env/.deps-${req_hash}"
if [ ! -f "$marker" ]; then
  python -m pip install --upgrade pip -q
  pip install -r requirements.txt -q
  rm -f .adk_env/.deps-* 2>/dev/null || true
  touch "$marker"
fi

# Persist the venv on PATH for the rest of a Claude Code session, if asked to.
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo "export PATH=\"$ROOT/.adk_env/bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"
fi

ruff --version  >/dev/null 2>&1 && echo "  ruff:  $(ruff --version)"  || true
black --version >/dev/null 2>&1 && echo "  black: $(black --version)" || true
echo "setup-env: dependencies installed (.adk_env ready)"
