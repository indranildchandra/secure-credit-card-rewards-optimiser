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

# Load .env early so OLLAMA_CLOUD_API_KEY / OLLAMA_API_KEY (git-ignored secrets)
# are available before we build the model handle. Silent no-op if python-dotenv
# is missing or .env is absent (the default local path needs no secrets).
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except Exception:
    pass


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


def _is_remote_host(api_base: str) -> bool:
    """True when the Ollama endpoint is not a loopback address — i.e. a hosted
    service like Ollama Cloud (https://ollama.com) that needs bearer auth. We
    only attach the API key for remote hosts so a stray key can never be sent to
    a local daemon (and local stays credential-free by design)."""
    host = (api_base or "").lower()
    return not any(
        local in host for local in ("localhost", "127.0.0.1", "0.0.0.0", "[::1]")
    )


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

    # LiteLLM forwards these kwargs to the Ollama chat provider. api_base points
    # at the daemon (local default) or a hosted endpoint; api_key is attached
    # ONLY for a remote host, where LiteLLM sends it as `Authorization: Bearer`.
    # This is the ADK/LiteLLM-native equivalent of the raw Ollama client's
    # host=... + headers={"Authorization": "Bearer ..."} — same wire result.
    _ollama_kwargs = {}
    _api_base = os.environ.get("OLLAMA_API_BASE", "").strip()
    if _api_base:
        _ollama_kwargs["api_base"] = _api_base
    if _is_remote_host(_api_base):
        _api_key = (
            os.environ.get("OLLAMA_CLOUD_API_KEY")
            or os.environ.get("OLLAMA_API_KEY")
            or ""
        ).strip()
        if _api_key:
            _ollama_kwargs["api_key"] = _api_key

    MODEL = LiteLlm(model=f"ollama_chat/{_model_name}", **_ollama_kwargs)
else:
    MODEL = _model_name

print(f" Model config: provider={_provider}, model={_model_name}")
