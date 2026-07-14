"""Offline tests for the opt-in conversation-history compaction callback."""

from types import SimpleNamespace

from google.genai import types

from optimizer.context_window import trim_history_before_model, _ENV_VAR


def _req(n):
    return SimpleNamespace(
        contents=[
            types.Content(role="user", parts=[types.Part(text=f"m{i}")])
            for i in range(n)
        ]
    )


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv(_ENV_VAR, raising=False)
    req = _req(100)
    assert trim_history_before_model(None, req) is None
    assert len(req.contents) == 100  # untouched when disabled


def test_trims_to_window_when_enabled(monkeypatch):
    monkeypatch.setenv(_ENV_VAR, "10")
    req = _req(50)
    trim_history_before_model(None, req)
    assert len(req.contents) == 11  # 1 summary note + last 10
    assert "omitted" in req.contents[0].parts[0].text.lower()
    assert req.contents[-1].parts[0].text == "m49"  # most recent kept


def test_noop_under_limit(monkeypatch):
    monkeypatch.setenv(_ENV_VAR, "10")
    req = _req(5)
    trim_history_before_model(None, req)
    assert len(req.contents) == 5


def test_invalid_env_is_disabled(monkeypatch):
    monkeypatch.setenv(_ENV_VAR, "not-a-number")
    req = _req(100)
    trim_history_before_model(None, req)
    assert len(req.contents) == 100
