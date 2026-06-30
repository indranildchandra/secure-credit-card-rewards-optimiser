#!/bin/bash
# Cursor sessionStart hook — prepares the Python environment for the session.
# Delegates to the shared bootstrap so every AI coding tool sets the repo up the
# same way. Registered in .cursor/hooks.json.
#
# Cursor hooks talk to the agent via JSON on stdout, so the bootstrap's
# human-readable output is sent to stderr and we emit an empty JSON object.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
"$ROOT/scripts/setup-env.sh" 1>&2 || true
printf '{}\n'
