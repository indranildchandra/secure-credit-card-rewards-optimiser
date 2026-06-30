"""
Central model configuration for the Credit Card Optimiser agent.
Edit config/model.config to switch models — no code changes needed.

Default is Ollama (fully local / offline) so transaction reasoning never leaves
the machine. Gemini remains available for those who want it.

Exports:
  MODEL               — the model handle the agents use.
  IS_GEMINI           — True when the provider is not Ollama (selects the web-
                        search backend in optimizer/agent.py: Google Search
                        grounding for Gemini vs DuckDuckGo for Ollama).
  LLM_TIMEOUT_SECONDS — per-LLM-call timeout applied to the local (Ollama) path.
"""

import os


def _safe_int(value, default: int) -> int:
    """int(value) with a fallback — a bad config value must not crash startup."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# Parse config/model.config (simple KEY=VALUE, ignores blank lines and comments)
_config = {}
_config_path = os.path.join(os.path.dirname(__file__), "config", "model.config")
with open(_config_path, encoding="utf-8") as _f:
    for _line in _f:
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _key, _, _val = _line.partition("=")
            _config[_key.strip()] = _val.strip()

_provider = _config.get("MODEL_PROVIDER", "ollama").lower().strip()
_model_name = _config.get("MODEL_NAME", "gemma4:e2b").strip()
IS_GEMINI = _provider != "ollama"

# Per-LLM-call timeout for the local path (seconds). Safe-parsed with a fallback.
LLM_TIMEOUT_SECONDS = _safe_int(_config.get("LLM_TIMEOUT_SECONDS"), 180)

# Set OLLAMA_API_BASE in env if specified in model.config
if "OLLAMA_API_BASE" in _config:
    os.environ.setdefault("OLLAMA_API_BASE", _config["OLLAMA_API_BASE"])

if _provider == "ollama":
    from google.adk.models.lite_llm import LiteLlm

    try:
        import litellm

        # Quieten LiteLLM's verbose error banner (e.g. when Ollama isn't running)
        # and cap how long a single call may block.
        litellm.suppress_debug_info = True
        litellm.request_timeout = LLM_TIMEOUT_SECONDS
    except Exception:
        pass

    MODEL = LiteLlm(model=f"ollama_chat/{_model_name}")
else:
    MODEL = _model_name

print(f" Model config: provider={_provider}, model={_model_name}")
