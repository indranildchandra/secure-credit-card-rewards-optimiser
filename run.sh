#!/bin/bash

# Launch the Credit Card Optimiser in the ADK Web UI with persistent sessions.
# Boots a local Ollama server (if configured) and starts `adk web .` on :8080.

# Catch unset variables and pipeline failures (not -e: some checks expect a
# non-zero exit and handle it inline).
set -uo pipefail

# Parse flags
CLEAN=0
for arg in "$@"; do
    case $arg in
        --clean) CLEAN=1 ;;
    esac
done

echo " Starting Credit Card Optimiser (ADK Web UI)..."

# Cleanup trap — only kills the Ollama process THIS script started.
cleanup() {
    if [ -n "${OLLAMA_PID:-}" ]; then
        kill "$OLLAMA_PID" 2>/dev/null && echo " Ollama stopped"
    fi
}
trap cleanup EXIT SIGINT SIGTERM

# Load environment variables from .env so `adk web` inherits them.
if [ -f "$(dirname "$0")/.env" ]; then
    set -a
    source "$(dirname "$0")/.env"
    set +a
    echo " Loaded .env"
else
    echo "  No .env found (fine for the default Ollama/offline setup)"
fi

# Check ADC when using Vertex AI mode.
if [ "${GOOGLE_GENAI_USE_VERTEXAI:-}" = "TRUE" ]; then
    if ! gcloud auth application-default print-access-token > /dev/null 2>&1; then
        echo "ERROR: Vertex AI mode requires Application Default Credentials."
        echo "Run: gcloud auth application-default login"
        exit 1
    fi
    echo "ADC: configured"
fi

# Start Ollama in the background if config/model.config specifies the ollama provider.
MODEL_CONFIG="$(dirname "$0")/config/model.config"
if [ -f "$MODEL_CONFIG" ]; then
    _provider=$(grep -E "^MODEL_PROVIDER=" "$MODEL_CONFIG" | cut -d= -f2 | tr -d '[:space:]')
    _model_name=$(grep -E "^MODEL_NAME=" "$MODEL_CONFIG" | cut -d= -f2 | tr -d '[:space:]')
    if [ "$_provider" = "ollama" ]; then
        if ! command -v ollama > /dev/null 2>&1; then
            echo "ERROR: MODEL_PROVIDER=ollama but ollama is not installed."
            echo "  Install Ollama:  https://ollama.com  (e.g. brew install ollama)"
            echo "  Then pull model: ollama pull $_model_name"
            exit 1
        fi
        if curl -s http://localhost:11434 > /dev/null 2>&1; then
            echo " Ollama already running on port 11434"
        else
            ollama serve &
            OLLAMA_PID=$!
            echo " Ollama started (pid $OLLAMA_PID) on port 11434"
            sleep 2  # give it time to bind before agents load
        fi

        # Pull the model if it isn't available locally.
        if ! ollama list 2>/dev/null | grep -qF "$_model_name"; then
            echo " Model '$_model_name' not found locally — pulling now (this may take a few minutes)..."
            ollama pull "$_model_name"
            echo " Model '$_model_name' ready"
        else
            echo " Model '$_model_name' already available"
        fi
    fi
fi

# SQLite session persistence (caps/spend tracking survive across turns/restarts).
# Kept inside the repo under db/ (gitignored — never committed). Resolve to an
# absolute path so it stays correct after the later `cd` and regardless of how
# the script was invoked.
SESSIONS_DIR="$(cd "$(dirname "$0")" && pwd)/db"
mkdir -p "$SESSIONS_DIR"
DB_FILE="$SESSIONS_DIR/optimizer_sessions.db"
SESSION_URI="sqlite:///$DB_FILE"

# --clean: wipe session DB before starting.
if [ "$CLEAN" = "1" ]; then
    if [ -f "$DB_FILE" ]; then
        rm "$DB_FILE"
        echo " Session database cleared: $DB_FILE"
    else
        echo " No session database found to clear"
    fi
fi

echo " Session database: $DB_FILE"

# Start the ADK Web UI (auto-discovers the `optimizer` agent package in cwd).
echo " Starting ADK Web UI on http://localhost:8080  (pick the 'optimizer' agent)"
cd "$(dirname "$0")"
adk web \
    --session_service_uri="$SESSION_URI" \
    --host=127.0.0.1 \
    --port=8080 \
    --log_level=warning \
    --reload \
    .

echo " ADK Web UI stopped"
