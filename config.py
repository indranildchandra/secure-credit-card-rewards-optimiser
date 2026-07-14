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
  IS_REMOTE_LLM       — True when the LLM runs off-device (Gemini, or Ollama
                        pointed at Ollama Cloud). False for a local Ollama daemon.
                        Anything downstream that must know "is this offline?"
                        should read this, not IS_GEMINI.
  LLM_TIMEOUT_SECONDS — per-LLM-call timeout applied to the local (Ollama) path.
"""

import os
from urllib.parse import urlparse

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

# Hosts we recognise as Ollama Cloud — the ONLY remote Ollama endpoint we attach
# credentials to. This is an allowlist, not a loopback denylist: anything not
# matched here (loopback, LAN, RFC1918 private IPs, a self-hosted box) is treated
# as a local daemon and is NEVER sent the API key. Add your own hosted endpoint
# here if you self-host Ollama behind auth.
_OLLAMA_CLOUD_HOSTS = ("ollama.com",)


def _is_ollama_cloud(api_base: str) -> bool:
    """True only when api_base's hostname is a known Ollama Cloud host (exact
    match or a subdomain of one). Parses the URL and compares the hostname —
    no substring scanning of the whole string, so `localhost.evil.com` or
    `ollama.com.attacker.net` cannot masquerade as either class."""
    if not api_base:
        return False
    # urlparse needs a scheme to populate .hostname; add one if it's bare.
    parsed = urlparse(api_base if "://" in api_base else f"//{api_base}")
    host = (parsed.hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in _OLLAMA_CLOUD_HOSTS)


# True when inference leaves the machine: Gemini, or Ollama aimed at the cloud.
# Read THIS (not IS_GEMINI) for any "is this offline?" decision.
IS_REMOTE_LLM = IS_GEMINI or (
    _provider == "ollama" and _is_ollama_cloud(os.environ.get("OLLAMA_API_BASE", ""))
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
    # ONLY for a known cloud host, where LiteLLM sends it as `Authorization:
    # Bearer`. This is the ADK/LiteLLM-native equivalent of the raw Ollama
    # client's host=... + headers={"Authorization": "Bearer ..."} — same wire
    # result.
    _ollama_kwargs = {}
    _api_base = os.environ.get("OLLAMA_API_BASE", "").strip()
    if _api_base:
        _ollama_kwargs["api_base"] = _api_base
    if _is_ollama_cloud(_api_base):
        _api_key = (
            os.environ.get("OLLAMA_CLOUD_API_KEY")
            or os.environ.get("OLLAMA_API_KEY")
            or ""
        ).strip()
        if _api_key:
            _ollama_kwargs["api_key"] = _api_key

    # Give the model enough output tokens to finish the four-field answer.
    # Ollama's default num_predict can cut a small model off mid-generation
    # (observed: a Gemma answer truncating before "The Winner"). LiteLLM forwards
    # num_predict straight to the Ollama request options.
    _ollama_kwargs.setdefault("num_predict", 2048)

    MODEL = LiteLlm(model=f"ollama_chat/{_model_name}", **_ollama_kwargs)
else:
    MODEL = _model_name

print(f" Model config: provider={_provider}, model={_model_name}")
if IS_REMOTE_LLM:
    print("⚠ reasoning is going to a remote host — not offline")
