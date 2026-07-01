"""Offline unit tests for the session-state spend/cap tracker.

A lightweight fake stands in for ADK's ToolContext — the tracker only needs a
``.state`` dict that persists between calls.
"""

import pytest

from data.cards import CARDS, CARD_ALIASES
import tools.spend_tracker as st
from tools.spend_tracker import (
    record_spend,
    get_spend_summary,
    get_spend_history,
    check_cap_status,
    check_fee_waiver_status,
    assess_card_value,
    _STATE_KEY,
    _RETENTION_MONTHS,
)


class FakeToolContext:
    """Minimal stand-in for google.adk.tools.ToolContext (just a state dict)."""

    def __init__(self):
        self.state = {}


@pytest.fixture
def custom_card():
    """Register a brand-new card defined purely via config-style data (no code
    change) so we can prove the tracker is fully config-driven."""
    name = "My Custom Cashback Card"
    CARDS[name] = {
        "rewards": ["8% on dining + entertainment up to Rs.500/month"],
        "value_back": {
            "top_rate": 8.0,
            "top_keywords": ["dining", "entertainment"],
            "base_rate": 1.0,
        },
        "tracker": {
            "type": "combined_monthly_cashback",
            "categories": ["dining", "entertainment"],
            "rate": 0.08,
            "cap_value": 500,
            "label": "combined monthly cashback (Dining + Entertainment)",
        },
    }
    CARD_ALIASES[name.lower()] = name
    try:
        yield name
    finally:
        CARDS.pop(name, None)
        CARD_ALIASES.pop(name.lower(), None)


def test_record_and_summary():
    ctx = FakeToolContext()
    record_spend(ctx, "dining", 1500, "HSBC Live+")
    record_spend(ctx, "grocery", 500, "HSBC Live+")
    summary = get_spend_summary(ctx)
    assert summary["by_category"]["dining"] == 1500.0
    assert summary["by_category"]["grocery"] == 500.0
    assert summary["by_card"]["HSBC Live+"] == 2000.0


def test_hsbc_cap_not_exhausted():
    ctx = FakeToolContext()
    record_spend(ctx, "dining", 5000, "HSBC Live+")  # 10% => Rs.500 cashback
    status = check_cap_status(ctx, "HSBC Live+")
    assert status["exhausted"] is False
    assert status["cashback_earned"] == 500.0
    assert status["cashback_remaining"] == 500.0


def test_hsbc_cap_exhausted():
    ctx = FakeToolContext()
    # Combined eligible spend of Rs.12,000 > Rs.10,000 => cap (Rs.1,000) hit.
    record_spend(ctx, "dining", 8000, "HSBC Live+")
    record_spend(ctx, "grocery", 4000, "HSBC Live+")
    status = check_cap_status(ctx, "HSBC Live+")
    assert status["exhausted"] is True
    assert status["cashback_earned"] == 1000.0
    assert status["cashback_remaining"] == 0.0


def test_hsbc_cap_counts_merchant_named_food_delivery():
    # C2 regression: a spend recorded as "swiggy"/"zomato" must count toward the
    # HSBC combined cap (config synonyms + symmetric category match).
    ctx = FakeToolContext()
    record_spend(ctx, "swiggy", 8000, "HSBC Live+")
    record_spend(ctx, "zomato", 4000, "HSBC Live+")
    status = check_cap_status(ctx, "HSBC Live+")
    assert status["eligible_spend_this_month"] == 12000.0
    assert status["exhausted"] is True


def test_hsbc_cap_rate_label_no_trailing_decimal():
    # C5 regression: 10% should render as "10%", not "10.0%".
    ctx = FakeToolContext()
    status = check_cap_status(ctx, "HSBC Live+")
    assert "@ 10%" in status["cap"]


def test_record_spend_parses_formatted_amount():
    # C3 regression: Indian-formatted / currency-prefixed amounts are accepted.
    ctx = FakeToolContext()
    record_spend(ctx, "electronics", "1,50,000", "Amex Platinum Travel")
    record_spend(ctx, "electronics", "₹ 50,000", "Amex Platinum Travel")
    summary = get_spend_summary(ctx)
    assert summary["by_card"]["Amex Platinum Travel"] == 200000.0


def test_record_spend_rejects_non_numeric_amount():
    ctx = FakeToolContext()
    msg = record_spend(ctx, "dining", "a lot", "HSBC Live+")
    assert "Could not read the amount" in msg
    assert get_spend_summary(ctx)["by_category"] == {}  # nothing recorded


def test_record_spend_rejects_non_positive_amount():
    # F5 regression: a negative amount must not be recorded (it could un-exhaust
    # a cap). Zero is rejected too.
    ctx = FakeToolContext()
    assert "positive" in record_spend(ctx, "dining", "-5000", "HSBC Live+")
    assert "positive" in record_spend(ctx, "dining", 0, "HSBC Live+")
    assert get_spend_summary(ctx)["by_category"] == {}


def test_scapia_threshold_progress():
    ctx = FakeToolContext()
    record_spend(ctx, "travel", 12000, "Scapia Visa")
    record_spend(ctx, "upi", 3000, "Scapia RuPay")  # both count toward Rs.20k
    status = check_cap_status(ctx, "Scapia Visa")
    assert status["spend_this_month"] == 15000.0
    assert status["remaining_to_unlock"] == 5000.0
    assert status["met"] is False


def test_scapia_threshold_met():
    ctx = FakeToolContext()
    record_spend(ctx, "travel", 21000, "Scapia Visa")
    status = check_cap_status(ctx, "Scapia Visa")
    assert status["met"] is True


def test_amex_milestone_progress():
    ctx = FakeToolContext()
    record_spend(ctx, "electronics", 150000, "Amex Platinum Travel")
    status = check_cap_status(ctx, "Amex Platinum Travel")
    assert status["spend_ytd"] == 150000.0
    assert status["remaining_to_target"] == 550000.0
    assert status["met"] is False


def test_card_without_cap():
    ctx = FakeToolContext()
    status = check_cap_status(ctx, "Uni GoldX")
    assert "note" in status and "No machine-trackable" in status["note"]


def test_unknown_card():
    ctx = FakeToolContext()
    assert "error" in check_cap_status(ctx, "totally fake card")


def test_state_key_is_user_scoped():
    # Memory: user-scoped so spends persist across sessions, not just one chat.
    assert _STATE_KEY.startswith("user:")


def test_assess_card_value_lifetime_free():
    ctx = FakeToolContext()
    r = assess_card_value(ctx, "ICICI AmazonPay")
    assert r.get("lifetime_free") is True
    assert "keep it" in r["verdict"].lower()


def test_assess_card_value_fee_waived():
    ctx = FakeToolContext()
    record_spend(ctx, "misc", 250000, "HSBC Live+")  # > Rs.2L waiver
    r = assess_card_value(ctx, "HSBC Live+")
    assert r["waived"] is True
    assert "waived" in r["verdict"].lower()


def test_assess_card_value_fee_not_waived():
    ctx = FakeToolContext()
    record_spend(ctx, "misc", 50000, "HDFC Regalia Gold")  # < Rs.4L waiver
    r = assess_card_value(ctx, "HDFC Regalia Gold")
    assert r["waived"] is False
    assert "not yet waived" in r["verdict"].lower()


def test_spend_history_recall_across_months():
    ctx = FakeToolContext()
    ctx.state[_STATE_KEY] = {
        "2026-05": {
            "by_category": {"dining": 3000.0},
            "by_card": {"HSBC Live+": 3000.0},
        },
        "2026-06": {
            "by_category": {"dining": 1000.0, "grocery": 2000.0},
            "by_card": {"HSBC Live+": 3000.0},
        },
    }
    res = get_spend_history(ctx, months_back=2)
    assert res["months"] == ["2026-06", "2026-05"]  # most recent first
    assert res["totals"]["by_category"]["dining"] == 4000.0
    assert res["totals"]["by_card"]["HSBC Live+"] == 6000.0
    assert set(res["per_month"]) == {"2026-05", "2026-06"}


def test_spend_history_months_back_clamped():
    ctx = FakeToolContext()
    ctx.state[_STATE_KEY] = {"2026-06": {"by_category": {"x": 1.0}, "by_card": {}}}
    assert get_spend_history(ctx, months_back=0)["months"] == ["2026-06"]


def test_retention_prunes_old_months():
    ctx = FakeToolContext()
    # Seed 24 old months (well over the retention window).
    ctx.state[_STATE_KEY] = {
        f"20{yy:02d}-{mm:02d}": {"by_category": {"x": 1.0}, "by_card": {}}
        for yy in (0, 1)
        for mm in range(1, 13)
    }
    record_spend(ctx, "dining", 100, "HSBC Live+")  # triggers prune
    stored = ctx.state[_STATE_KEY]
    assert len(stored) <= _RETENTION_MONTHS
    assert st._current_month() in stored  # current month always kept


def test_fee_waiver_lifetime_free():
    ctx = FakeToolContext()
    status = check_fee_waiver_status(ctx, "ICICI AmazonPay")
    assert status.get("lifetime_free") is True


def test_fee_waiver_progress_not_yet_waived():
    ctx = FakeToolContext()
    record_spend(ctx, "grocery", 50000, "HSBC Live+")  # threshold is Rs.2,00,000
    status = check_fee_waiver_status(ctx, "HSBC Live+")
    assert status["waived"] is False
    assert status["spend_ytd"] == 50000.0
    assert status["remaining_to_waiver"] == 150000.0


def test_fee_waiver_reached():
    ctx = FakeToolContext()
    record_spend(ctx, "misc", 200000, "HSBC Live+")
    status = check_fee_waiver_status(ctx, "HSBC Live+")
    assert status["waived"] is True


def test_fee_waiver_no_spend_based_waiver():
    ctx = FakeToolContext()
    status = check_fee_waiver_status(ctx, "Amex Platinum Travel")
    assert status["waived"] is False
    assert "no spend-based waiver" in status["note"].lower()


def test_config_driven_custom_card(custom_card):
    """A card defined only through config data (no Python edit) is tracked."""
    ctx = FakeToolContext()
    record_spend(ctx, "dining", 4000, custom_card)
    record_spend(ctx, "entertainment", 3000, custom_card)
    status = check_cap_status(ctx, custom_card)
    # Rs.7,000 eligible @ 8% = Rs.560 > Rs.500 cap => exhausted.
    assert status["exhausted"] is True
    assert status["cashback_earned"] == 500.0
