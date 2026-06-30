"""Offline unit tests for the session-state spend/cap tracker.

A lightweight fake stands in for ADK's ToolContext — the tracker only needs a
``.state`` dict that persists between calls.
"""

from tools.spend_tracker import (
    record_spend,
    get_spend_summary,
    check_cap_status,
)


class FakeToolContext:
    """Minimal stand-in for google.adk.tools.ToolContext (just a state dict)."""

    def __init__(self):
        self.state = {}


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
