"""Tests for local CSV spend import: pure parsing + the ADK persist round-trip."""

import asyncio

from google.adk.sessions import InMemorySessionService

from tools.spend_import import parse_spends_csv, import_rows
from tools.spend_tracker import _STATE_KEY


def test_parse_maps_flexible_headers():
    csv_text = (
        "Date,Merchant,Amount,Card\n"
        '2026-06-01,Swiggy order,"1,200",HSBC Live+\n'
        "2026-06-02,Amazon,4000,ICICI AmazonPay\n"
    )
    parsed = parse_spends_csv(csv_text)
    assert parsed["skipped"] == 0
    rows = parsed["rows"]
    assert rows[0]["amount"] == 1200.0 and rows[0]["month"] == "2026-06"
    assert (
        rows[0]["category"] == "swiggy order" or "swiggy" in rows[0]["category"].lower()
    )
    assert rows[1]["amount"] == 4000.0


def test_parse_skips_bad_amounts():
    csv_text = "amount,category\n,dining\nabc,grocery\n-50,fuel\n900,dining\n"
    parsed = parse_spends_csv(csv_text)
    assert parsed["skipped"] == 3
    assert len(parsed["rows"]) == 1 and parsed["rows"][0]["amount"] == 900.0


def test_import_rows_persists_user_state():
    rows = [
        {
            "month": "2026-06",
            "category": "dining",
            "amount": 8000.0,
            "card": "HSBC Live+",
        },
        {
            "month": "2026-06",
            "category": "grocery",
            "amount": 4000.0,
            "card": "HSBC Live+",
        },
    ]
    svc = InMemorySessionService()

    async def run():
        summary = await import_rows(svc, "optimizer", "user", rows)
        s = await svc.create_session(app_name="optimizer", user_id="user")
        return summary, s.state.get(_STATE_KEY)

    summary, log = asyncio.run(run())
    assert summary["imported"] == 2
    # User-scoped state is shared across the user's sessions, so a fresh session
    # still sees the imported totals.
    assert log["2026-06"]["by_card"]["HSBC Live+"] == 12000.0


def test_import_prunes_to_retention_window():
    # R1 regression: importing many historical months must not grow the store
    # without bound — the importer prunes like record_spend.
    from tools.spend_tracker import _RETENTION_MONTHS

    rows = [
        {"month": f"20{yy:02d}-{mm:02d}", "category": "x", "amount": 100.0, "card": ""}
        for yy in (0, 1)
        for mm in range(1, 13)
    ]  # 24 months
    svc = InMemorySessionService()

    async def run():
        await import_rows(svc, "optimizer", "user", rows)
        s = await svc.create_session(app_name="optimizer", user_id="user")
        return s.state.get(_STATE_KEY)

    log = asyncio.run(run())
    assert len(log) <= _RETENTION_MONTHS
