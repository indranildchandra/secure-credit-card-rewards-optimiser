"""Offline unit tests for the config-writer tools used by scripts/setup_cards.py.

Each test points the writer at a temporary config file so the real
config/cards.config is never touched.
"""

import json

import pytest

import tools.config_writer as cw


@pytest.fixture
def temp_config(tmp_path, monkeypatch):
    cfg = tmp_path / "cards.config"
    cfg.write_text(
        json.dumps(
            {
                "cards": {
                    "Existing Card": {
                        "rewards": ["1% on all"],
                        "value_back": {
                            "top_rate": 1.0,
                            "top_keywords": [],
                            "base_rate": 1.0,
                        },
                    }
                },
                "decision_matrix": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cw, "_CONFIG_PATH", str(cfg))
    return cfg


def _read(cfg):
    return json.loads(cfg.read_text(encoding="utf-8"))


def test_list_configured_cards(temp_config):
    res = cw.list_configured_cards()
    assert res["count"] == 1
    assert res["cards"] == ["Existing Card"]


def test_save_card_adds(temp_config):
    msg = cw.save_card(
        json.dumps(
            {
                "name": "New Card",
                "rewards": ["5% on travel"],
                "value_back": {
                    "top_rate": 5.0,
                    "top_keywords": ["travel"],
                    "base_rate": 1.0,
                },
                "fee_waiver": {"lifetime_free": True},
            }
        )
    )
    assert "Added" in msg
    data = _read(temp_config)
    assert "New Card" in data["cards"]
    assert data["cards"]["New Card"]["value_back"]["top_rate"] == 5.0


def test_save_card_updates_existing(temp_config):
    msg = cw.save_card(json.dumps({"name": "Existing Card", "rewards": ["2% on all"]}))
    assert "Updated" in msg
    assert _read(temp_config)["cards"]["Existing Card"]["rewards"] == ["2% on all"]


def test_save_card_invalid_json(temp_config):
    assert "Invalid JSON" in cw.save_card("{not json")


def test_save_card_missing_name(temp_config):
    assert "name" in cw.save_card(json.dumps({"rewards": []})).lower()


def test_save_card_bad_value_back(temp_config):
    msg = cw.save_card(json.dumps({"name": "X", "value_back": {"top_rate": 2.0}}))
    assert "value_back" in msg


def test_save_card_bad_tracker_type(temp_config):
    msg = cw.save_card(json.dumps({"name": "X", "tracker": {"type": "made_up_type"}}))
    assert "tracker.type" in msg


def test_add_decision_rule(temp_config):
    msg = cw.add_decision_rule(
        json.dumps(
            {
                "category": "Fuel",
                "keywords": ["fuel", "petrol"],
                "primary": "Existing Card",
                "strategy": "surcharge waiver",
            }
        )
    )
    assert "Added" in msg
    assert _read(temp_config)["decision_matrix"][0]["category"] == "Fuel"


def test_add_decision_rule_unknown_primary(temp_config):
    msg = cw.add_decision_rule(
        json.dumps({"category": "X", "keywords": ["x"], "primary": "Ghost Card"})
    )
    assert "not a known card" in msg


def test_add_decision_rule_replaces_same_category(temp_config):
    rule = {"category": "Fuel", "keywords": ["fuel"], "primary": "Existing Card"}
    cw.add_decision_rule(json.dumps(rule))
    rule2 = dict(rule, strategy="updated")
    msg = cw.add_decision_rule(json.dumps(rule2))
    assert "Replaced" in msg
    matrix = _read(temp_config)["decision_matrix"]
    assert len(matrix) == 1 and matrix[0]["strategy"] == "updated"
