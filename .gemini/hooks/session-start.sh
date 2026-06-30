#!/bin/bash
# Gemini CLI SessionStart hook — prepares the Python environment for the session.
# Delegates to the shared bootstrap so every AI coding tool sets the repo up the
# same way. Registered in .gemini/settings.json.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec "$ROOT/scripts/setup-env.sh"
