#!/bin/bash

# Credit Card Optimiser — full first-time setup.
#
# This is the human entry point. It delegates the Python environment (virtualenv
# + dependencies) to the shared bootstrap `scripts/setup-env.sh` — the SAME
# script every AI-tool session hook uses — and then additionally pulls the local
# Ollama model named in config/model.config (the one thing the lightweight
# bootstrap deliberately skips).

set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "Setting up the Credit Card Optimiser environment..."

# --- Python environment (venv + dependencies) ---
./scripts/setup-env.sh

# --- Ollama model pull (the bit setup-env.sh skips) ---
_provider=$(grep -E "^MODEL_PROVIDER=" config/model.config | cut -d= -f2 | tr -d '[:space:]')
_model_name=$(grep -E "^MODEL_NAME=" config/model.config | cut -d= -f2 | tr -d '[:space:]')
if [ "$_provider" = "ollama" ]; then
    if ! command -v ollama > /dev/null 2>&1; then
        echo "  Ollama is not installed. Install it from https://ollama.com"
        echo "   Then run: ollama pull $_model_name"
    else
        echo "Ensuring Ollama model '$_model_name' is available..."
        if ! ollama list 2>/dev/null | grep -q "$_model_name"; then
            ollama pull "$_model_name"
        else
            echo "Model '$_model_name' already available"
        fi
    fi
fi

echo ""
echo "Setup complete!"
echo "   Activate:  source .adk_env/bin/activate"
echo "   Run:       ./run.sh                  (then open http://localhost:8080)"
echo "   Onboard:   ./scripts/setup_cards.sh  (configure your cards by chatting)"
echo "   Test:      python -m pytest tests/ -q"
