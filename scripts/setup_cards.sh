#!/bin/bash
# Launch the card-onboarding assistant from the shell.
#   ./scripts/setup_cards.sh                 # interactive
#   ./scripts/setup_cards.sh --once "TEXT"   # one-shot
# Activates the project virtualenv if present, then runs scripts/setup_cards.py.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ -d .adk_env ]; then
  # shellcheck disable=SC1091
  source .adk_env/bin/activate
fi

exec python scripts/setup_cards.py "$@"
