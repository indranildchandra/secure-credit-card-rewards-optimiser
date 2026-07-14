#!/usr/bin/env bash
# Demo pre-flight for the Credit Card Optimiser.
#
# Run this ~10 minutes before going on stage. It verifies Ollama, the model, the
# offline test suite, and — crucially — PRE-WARMS the model so your first live
# query on stage is fast (not a cold model load). Safe to run repeatedly.
#
#   ./scripts/demo-preflight.sh
#
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

MODEL=$(grep -E "^MODEL_NAME=" config/model.config | cut -d= -f2 | tr -d '[:space:]')
PROVIDER=$(grep -E "^MODEL_PROVIDER=" config/model.config | cut -d= -f2 | tr -d '[:space:]')
ok()   { printf "  \033[32m✓\033[0m %s\n" "$1"; }
warn() { printf "  \033[33m!\033[0m %s\n" "$1"; }
fail() { printf "  \033[31m✗ %s\033[0m\n" "$1"; }

echo "── Demo pre-flight ─────────────────────────────────"
echo "Provider=$PROVIDER  Model=$MODEL"

# 1. venv + offline suite (proves the deterministic engine is green)
if [ -d .adk_env ]; then
  # shellcheck disable=SC1091
  source .adk_env/bin/activate
  ok ".adk_env activated"
else
  warn "No .adk_env — run ./scripts/setup-env.sh first"
fi

# `adk` MUST resolve inside the venv, or the ADK Web UI crashes on agent load
# with "LiteLLM support requires: pip install google-adk[extensions]" (a
# system-installed adk has no litellm). This is the exact on-stage failure to
# catch here, not at showtime.
if ! command -v adk >/dev/null 2>&1; then
  fail "'adk' not found on PATH — run ./setup_venv.sh (or activate .adk_env)"; exit 1
fi
_ADK_PATH="$(command -v adk)"
case "$_ADK_PATH" in
  "$ROOT/.adk_env/"*)
    ok "adk resolves to the venv ($_ADK_PATH)" ;;
  *)
    fail "adk resolves OUTSIDE the venv: $_ADK_PATH"
    echo "     The ADK Web UI would crash with the 'google-adk[extensions]' error"
    echo "     (a system adk has no litellm). Fix before demoing:"
    echo "       source .adk_env/bin/activate     # then re-run this script"
    echo "       (./run.sh also forces the venv automatically)"
    exit 1 ;;
esac

echo "── Running offline test suite ──"
if python -m pytest tests/ -q >/tmp/preflight_tests.log 2>&1; then
  ok "$(tail -1 /tmp/preflight_tests.log)"
else
  fail "offline tests FAILED — see /tmp/preflight_tests.log"; tail -5 /tmp/preflight_tests.log
fi

if [ "$PROVIDER" != "ollama" ]; then
  warn "Provider is '$PROVIDER' (cloud). Skipping Ollama checks."
  echo "── Pre-flight done ──"; exit 0
fi

# 2. Ollama installed + running
if ! command -v ollama >/dev/null 2>&1; then
  fail "ollama not installed — https://ollama.com (brew install ollama)"; exit 1
fi
ok "ollama installed"
if ! curl -sS -m 3 http://localhost:11434/api/tags >/dev/null 2>&1; then
  warn "Ollama server not responding — starting it in the background…"
  (ollama serve >/tmp/ollama.log 2>&1 &) ; sleep 3
fi
if curl -sS -m 3 http://localhost:11434/api/tags >/dev/null 2>&1; then
  ok "Ollama server responding on :11434"
else
  fail "Ollama server not reachable on :11434"; exit 1
fi

# 3. model present (pull if missing — do this on GOOD wifi, not at the venue)
if ollama list 2>/dev/null | grep -q "${MODEL%%:*}"; then
  ok "model '$MODEL' present"
else
  warn "model '$MODEL' not found — pulling now (do NOT do this on venue wifi!)"
  ollama pull "$MODEL" || { fail "pull failed — is the tag '$MODEL' correct?"; exit 1; }
fi

# 4. PRE-WARM: load the model into memory + confirm it tool-calls, so the first
#    on-stage query is instant. Runs one real query through the agent.
echo "── Pre-warming the model (one real query) ──"
python - <<'PY'
import time, sys
t0 = time.time()
try:
    from evals.harness import ask
    ans = ask("I am spending Rs.4,000 on Amazon. Which card?")
    dt = time.time() - t0
    hit = "ICICI AmazonPay" in ans
    print(f"  first-query latency: {dt:.1f}s")
    print("  \033[32m✓\033[0m model answered and named the expected card"
          if hit else
          "  \033[33m!\033[0m model answered but did NOT name ICICI AmazonPay — "
          "rehearse / consider gemma4:e4b or the Gemini fallback")
    print("\n  --- sample answer ---")
    print("  " + ans.replace("\n", "\n  ")[:600])
except Exception as e:
    print(f"  \033[31m✗ pre-warm query failed: {e}\033[0m")
    sys.exit(1)
PY

echo "── Pre-flight done. You're warm. Break a leg. ──"
