#!/bin/bash

# Credit Card Optimiser — virtual environment setup (Ollama / offline focused).
# Creates .adk_env, installs dependencies, and ensures the local model is pulled.

set -e

handle_error() { echo "Error: $1"; exit 1; }

echo " Setting up the Credit Card Optimiser environment..."

# --- Python check ---
if ! command -v python3 &> /dev/null; then
    handle_error "Python 3 is required but not installed (need 3.8+)."
fi
python_version=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
required_version="3.8"
if [ "$(printf '%s\n' "$required_version" "$python_version" | sort -V | head -n1)" != "$required_version" ]; then
    handle_error "Python $required_version or higher is required. Current: $python_version"
fi
echo " Python $python_version detected"

if [ "$(printf '%s\n' "3.10" "$python_version" | sort -V | head -n1)" = "3.10" ]; then
    echo " Python >= 3.10 → will install google-adk==1.33.0"
elif [ "$(printf '%s\n' "3.9" "$python_version" | sort -V | head -n1)" = "3.9" ]; then
    echo " Python >= 3.9  → will install google-adk==1.15.1"
else
    echo "  Python < 3.9  → will install google-adk==0.3.0 (consider upgrading)"
fi

# --- Virtual environment ---
echo " Creating virtual environment (.adk_env)..."
python3 -m venv .adk_env
# shellcheck disable=SC1091
source .adk_env/bin/activate

echo "⬆  Upgrading pip..."
pip install --upgrade pip

echo " Installing dependencies..."
pip install -r requirements.txt

# --- Ollama check / model pull ---
_provider=$(grep -E "^MODEL_PROVIDER=" config/model.config | cut -d= -f2 | tr -d '[:space:]')
_model_name=$(grep -E "^MODEL_NAME=" config/model.config | cut -d= -f2 | tr -d '[:space:]')
if [ "$_provider" = "ollama" ]; then
    if ! command -v ollama > /dev/null 2>&1; then
        echo "  Ollama is not installed. Install it from https://ollama.com"
        echo "   Then run: ollama pull $_model_name"
    else
        echo " Ensuring Ollama model '$_model_name' is available..."
        if ! ollama list 2>/dev/null | grep -q "$_model_name"; then
            ollama pull "$_model_name"
        else
            echo " Model '$_model_name' already available"
        fi
    fi
fi

echo ""
echo " Setup complete!"
echo "   Activate:  source .adk_env/bin/activate"
echo "   Run:       ./run.sh        (then open http://localhost:8080)"
echo "   Test:      python -m pytest tests/ -q"
