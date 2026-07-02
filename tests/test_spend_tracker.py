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
    # Scapia unlocks on the PRECEDING month's spend. Seed last month below the
    # Rs.20k bar -> lounge NOT unlocked for the current month.
    ctx = FakeToolContext()
    ctx.state[_STATE_KEY] = {
        st._preceding_month(): {
            "by_category": {},
            "by_card": {"Scapia Visa": 12000.0, "Scapia RuPay": 3000.0},
        }
    }
    status = check_cap_status(ctx, "Scapia Visa")
    assert status["period"] == "preceding_month"
    assert status["qualifying_month"] == st._preceding_month()
    assert status["spend_preceding_month"] == 15000.0
    assert status["remaining_to_unlock"] == 5000.0
    assert status["met"] is False


def test_scapia_threshold_met():
    # Rs.21k spent last month across the two Scapia cards -> unlocked this month.
    ctx = FakeToolContext()
    ctx.state[_STATE_KEY] = {
        st._preceding_month(): {
            "by_category": {},
            "by_card": {"Scapia Visa": 21000.0},
        }
    }
    status = check_cap_status(ctx, "Scapia Visa")
    assert status["met"] is True


def test_scapia_current_month_spend_counts_toward_next_month():
    # C6 regression: spending THIS month must not read as "unlocked this month";
    # it counts toward NEXT month's access.
    ctx = FakeToolContext()
    record_spend(ctx, "travel", 25000, "Scapia Visa")  # lands in current month
    status = check_cap_status(ctx, "Scapia Visa")
    assert status["met"] is False
    assert status["spend_preceding_month"] == 0.0
    assert "NEXT month" in status["note"]


def test_scapia_rupay_shares_the_threshold():
    # The shared lounge threshold is now queryable from the RuPay side too.
    ctx = FakeToolContext()
    ctx.state[_STATE_KEY] = {
        st._preceding_month(): {
            "by_category": {},
            "by_card": {"Scapia RuPay": 22000.0},
        }
    }
    status = check_cap_status(ctx, "Scapia RuPay")
    assert status["met"] is True
    assert status["spend_preceding_month"] == 22000.0


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


def test_record_spend_rejects_non_finite_amount():
    # inf/nan must be rejected like garbage — they would poison cap/threshold
    # totals if they slipped past the ``amt <= 0`` guard.
    ctx = FakeToolContext()
    for bad in (float("inf"), float("-inf"), float("nan"), "inf", "nan"):
        msg = record_spend(ctx, "dining", bad, "HSBC Live+")
        assert "Could not read the amount" in msg
    assert get_spend_summary(ctx)["by_category"] == {}  # nothing recorded


def test_check_cap_status_ambiguous_card():
    # An issuer-only reference matching >1 held card is ambiguous: the tool must
    # surface the ambiguity (ask which card) instead of guessing one.
    ctx = FakeToolContext()
    res = check_cap_status(ctx, "Axis")
    assert res.get("ambiguous") is True
    assert set(res["matches"]) == {"Axis Rewards", "Axis RuPay"}


def test_check_fee_waiver_status_ambiguous_card():
    ctx = FakeToolContext()
    res = check_fee_waiver_status(ctx, "Scapia")
    assert res.get("ambiguous") is True
    assert set(res["matches"]) == {"Scapia Visa", "Scapia RuPay"}


def test_assess_card_value_ambiguous_card():
    ctx = FakeToolContext()
    res = assess_card_value(ctx, "Axis")
    assert res.get("ambiguous") is True
    assert set(res["matches"]) == {"Axis Rewards", "Axis RuPay"}


def test_record_spend_ambiguous_card_records_nothing():
    # Critical privacy/correctness invariant: an ambiguous "record Rs.X on my Axis
    # card" must ask which card and mutate NO durable state.
    ctx = FakeToolContext()
    msg = record_spend(ctx, "dining", 1500, "Axis")
    assert isinstance(msg, str)
    # No spend recorded under any category or card.
    summary = get_spend_summary(ctx)
    assert summary["by_category"] == {}
    assert summary["by_card"] == {}
    assert ctx.state.get(_STATE_KEY) in (None, {})


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
    # ROI verdict now compares estimated rewards against the parsed fee (Rs.2,500)
    # rather than a generic "not yet waived" line.
    v = r["verdict"].lower()
    assert "rewards" in v and "vs" in v and "2,500" in v


def test_assess_card_value_roi_beats_fee():
    # R-ROI: est. YTD rewards that exceed the parsed fee produce a positive
    # rewards-vs-fee verdict (fee "Rs.2,500" parsed to 2500; not yet waived).
    ctx = FakeToolContext()
    record_spend(ctx, "misc", 300000, "HDFC Regalia Gold")  # base 1% => ~Rs.3,000
    r = assess_card_value(ctx, "HDFC Regalia Gold")
    assert r["waived"] is False  # waiver threshold is Rs.4L
    assert r["est_rewards_ytd"] == 3000.0
    v = r["verdict"].lower()
    assert "3,000" in v and "2,500" in v and "vs" in v


def test_assess_card_value_missing_fee_info():
    # R4 regression: a card with no fee_waiver block gets an honest "no info"
    # verdict, not a wrong "fee always applies".
    ctx = FakeToolContext()
    bak = CARDS["Uni GoldX"].pop("fee_waiver", None)
    try:
        r = assess_card_value(ctx, "Uni GoldX")
        assert "no annual-fee info" in r["verdict"].lower()
        assert "always applies" not in r["verdict"].lower()
    finally:
        if bak is not None:
            CARDS["Uni GoldX"]["fee_waiver"] = bak


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


def test_hsbc_cap_counts_grocery_merchant_synonyms():
    # C7 regression: quick-commerce grocery merchants that route to HSBC now
    # count toward the shared cap (previously silently missed it).
    ctx = FakeToolContext()
    record_spend(ctx, "blinkit", 8000, "HSBC Live+")
    record_spend(ctx, "zepto", 4000, "HSBC Live+")  # Rs.12k eligible @10% > cap
    status = check_cap_status(ctx, "HSBC Live+")
    assert status["eligible_spend_this_month"] == 12000.0
    assert status["exhausted"] is True
