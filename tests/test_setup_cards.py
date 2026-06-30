"""Offline smoke tests for the card-onboarding CLI (setup_cards.py).

These exercise the wiring and the --once / run_once plumbing WITHOUT calling the
model: the actual agent reply (which needs a running Ollama) is monkeypatched.
"""

import pytest

import setup_cards


def test_agent_wiring():
    assert setup_cards.root_agent.name == "card_setup"
    # ddg_search + the three config-writer tools.
    assert len(setup_cards.root_agent.tools) == 4


def test_build_runner_creates_session():
    # No model call — just constructs the runner and creates a session.
    runner = setup_cards.build_runner()
    assert runner is not None
    assert hasattr(runner, "session_service")


def test_run_once_plumbing(monkeypatch):
    monkeypatch.setattr(
        setup_cards, "_agent_reply", lambda runner, text: f"echo:{text}"
    )
    assert setup_cards.run_once("hello") == "echo:hello"


def test_main_once_flag(monkeypatch, capsys):
    monkeypatch.setattr(
        setup_cards, "_agent_reply", lambda runner, text: f"echo:{text}"
    )
    setup_cards.main(["--once", "I have an Amazon Pay ICICI card"])
    out = capsys.readouterr().out
    assert "echo:I have an Amazon Pay ICICI card" in out


def test_run_once_empty_raises(monkeypatch):
    # No model running -> empty reply -> a clear, typed error (not a traceback).
    monkeypatch.setattr(setup_cards, "_agent_reply", lambda runner, text: "")
    with pytest.raises(setup_cards.ModelUnavailable):
        setup_cards.run_once("hello")


def test_main_once_empty_exits_gracefully(monkeypatch, capsys):
    monkeypatch.setattr(setup_cards, "_agent_reply", lambda runner, text: "")
    with pytest.raises(SystemExit) as exc:
        setup_cards.main(["--once", "hello"])
    assert exc.value.code == 1
    assert "Could not get a response" in capsys.readouterr().out
