#!/bin/bash
# SessionStart hook: prepare the Python environment so tests and linters run
# out-of-the-box. Creates a virtualenv (.adk_env), installs dependencies
# (including the ruff linter and black formatter), and puts the venv on PATH for
# the session. Web (remote) sessions only.
set -euo pipefail

# Only run in Claude Code on the web (remote) sessions.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-.}"

# Create the virtualenv once; reuse the cached one on subsequent runs (idempotent).
if [ ! -d .adk_env ]; then
  python3 -m venv .adk_env
fi

# shellcheck disable=SC1091
source .adk_env/bin/activate
python -m pip install --upgrade pip -q
pip install -r requirements.txt -q

# Persist the venv on PATH for the rest of the session so `pytest`/`python`
# resolve to the installed dependencies.
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo "export PATH=\"${CLAUDE_PROJECT_DIR:-.}/.adk_env/bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"
fi

# Confirm the lint/format tools are available (non-fatal — never blocks startup).
ruff --version || true
black --version || true

echo "session-start hook: dependencies installed (.adk_env ready; ruff + black available)"
