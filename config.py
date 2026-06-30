"""
Central model configuration for the Credit Card Optimiser agent.
Edit config/model.config to switch models — no code changes needed.

Default is Ollama (fully local / offline) so transaction reasoning never leaves
the machine. Gemini remains available for those who want it.
"""

import os

# Parse config/model.config (simple KEY=VALUE, ignores blank lines and comments)
_config = {}
_config_path = os.path.join(os.path.dirname(__file__), "config", "model.config")
with open(_config_path) as _f:
    for _line in _f:
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _key, _, _val = _line.partition("=")
            _config[_key.strip()] = _val.strip()

_provider = _config.get("MODEL_PROVIDER", "ollama").lower().strip()
_model_name = _config.get("MODEL_NAME", "gemma4:e2b").strip()

# Set OLLAMA_API_BASE in env if specified in model.config
if "OLLAMA_API_BASE" in _config:
    os.environ.setdefault("OLLAMA_API_BASE", _config["OLLAMA_API_BASE"])

if _provider == "ollama":
    from google.adk.models.lite_llm import LiteLlm

    MODEL = LiteLlm(model=f"ollama_chat/{_model_name}")
else:
    MODEL = _model_name

# SEARCH_TOOLS — the live web-search tool the agent uses to check for the latest
# offers / devaluations.
#
# Ollama:  uses DuckDuckGo (free, no API key, plain Python function tool)
# Gemini:  uses google_search (server-side grounding, best quality)
if _provider == "ollama":
    from tools.duckduckgo_search import ddg_search

    SEARCH_TOOLS = [ddg_search]
else:
    from google.adk.tools import google_search

    SEARCH_TOOLS = [google_search]

IS_GEMINI = _provider != "ollama"

print(f" Model config: provider={_provider}, model={_model_name}")

# Per-LLM-call cap for Ollama (litellm.request_timeout). Increase for slow models.
LLM_TIMEOUT_SECONDS = int(_config.get("LLM_TIMEOUT_SECONDS", 180))
