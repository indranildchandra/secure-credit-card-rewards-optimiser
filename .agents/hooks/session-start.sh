#!/bin/bash
# Tool-agnostic SessionStart hook.
#
# A standard, well-known location any AI coding tool, editor, or CI step can call
# to prepare the repo (mirrors .claude/ and .gemini/). Delegates to the shared
# bootstrap. Run directly:  ./.agents/hooks/session-start.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec "$ROOT/scripts/setup-env.sh"
