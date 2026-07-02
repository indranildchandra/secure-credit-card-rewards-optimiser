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
    # Empty and non-numeric amounts are skipped; a bare negative is NOT a bad
    # amount any more — it's a credit/refund (see test_parse_signed_negative...).
    csv_text = "amount,category\n,dining\nabc,grocery\n-50,fuel\n900,dining\n"
    parsed = parse_spends_csv(csv_text)
    assert parsed["skipped"] == 2
    amounts = sorted(r["amount"] for r in parsed["rows"])
    assert amounts == [-50.0, 900.0]


def test_parse_signed_negative_is_a_credit():
    # A signed-negative amount (or accounting parentheses) is a refund/credit,
    # carried through as a negative amount rather than silently dropped.
    csv_text = "amount,category\n-300,fuel\n(200),dining\n1000,shopping\n"
    parsed = parse_spends_csv(csv_text)
    assert parsed["skipped"] == 0
    by_cat = {r["category"]: r["amount"] for r in parsed["rows"]}
    assert by_cat["fuel"] == -300.0
    assert by_cat["dining"] == -200.0
    assert by_cat["shopping"] == 1000.0


def test_parse_separate_credit_column_is_negative():
    # Statements with distinct Debit/Credit columns: the credit row nets out.
    csv_text = (
        "Date,Merchant,Debit,Credit\n"
        "2026-06-01,Amazon,4000,\n"
        "2026-06-05,Amazon refund,,1500\n"
    )
    parsed = parse_spends_csv(csv_text)
    assert parsed["skipped"] == 0
    amounts = sorted(r["amount"] for r in parsed["rows"])
    assert amounts == [-1500.0, 4000.0]


def test_parse_drcr_indicator_flips_sign():
    # A single unsigned amount column plus a dr/cr indicator column.
    csv_text = "Amount,Category,Type\n" "500,fuel,DR\n" "800,dining,CR\n"
    parsed = parse_spends_csv(csv_text)
    by_cat = {r["category"]: r["amount"] for r in parsed["rows"]}
    assert by_cat["fuel"] == 500.0
    assert by_cat["dining"] == -800.0


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


def test_import_skips_ambiguous_card_row():
    # An issuer-only card value ("Axis") that maps to >1 held card must NOT be
    # booked to whichever card iterates first — it is skipped and reported.
    rows = [
        {"month": "2026-06", "category": "shopping", "amount": 5000.0, "card": "Axis"},
        {
            "month": "2026-06",
            "category": "dining",
            "amount": 2000.0,
            "card": "HSBC Live+",
        },
    ]
    svc = InMemorySessionService()

    async def run():
        summary = await import_rows(svc, "optimizer", "user", rows)
        s = await svc.create_session(app_name="optimizer", user_id="user")
        return summary, s.state.get(_STATE_KEY)

    summary, log = asyncio.run(run())
    assert summary["imported"] == 1
    assert summary["skipped_ambiguous"] == 1
    skipped = summary["skipped"]
    assert len(skipped) == 1 and skipped[0]["reason"] == "ambiguous_card"
    assert skipped[0]["row"] == 0
    # The candidate cards are surfaced so the caller can re-import specifically.
    assert set(skipped[0]["matches"]) >= {"Axis Rewards", "Axis RuPay"}
    # Nothing from the ambiguous row leaked into durable state.
    bucket = log["2026-06"]
    assert "shopping" not in bucket["by_category"]
    assert "Axis Rewards" not in bucket["by_card"]
    assert "Axis RuPay" not in bucket["by_card"]
    assert bucket["by_card"]["HSBC Live+"] == 2000.0


def test_import_nets_credits_so_ytd_is_not_inflated():
    # A refund on the same card/category/month reduces net spend (floored at 0),
    # so YTD stays correct — a debits-only importer would over-count and fire a
    # false fee-waiver / milestone.
    rows = [
        {
            "month": "2026-06",
            "category": "dining",
            "amount": 60000.0,
            "card": "HSBC Live+",
        },
        {
            "month": "2026-06",
            "category": "dining",
            "amount": -10000.0,  # refund
            "card": "HSBC Live+",
        },
    ]
    svc = InMemorySessionService()

    async def run():
        summary = await import_rows(svc, "optimizer", "user", rows)
        s = await svc.create_session(app_name="optimizer", user_id="user")
        return summary, s.state.get(_STATE_KEY)

    summary, log = asyncio.run(run())
    assert summary["debits_total"] == 60000.0
    assert summary["credits_total"] == 10000.0
    assert summary["net_total"] == 50000.0
    bucket = log["2026-06"]
    assert bucket["by_card"]["HSBC Live+"] == 50000.0
    assert bucket["by_category"]["dining"] == 50000.0


def test_import_credit_floors_bucket_at_zero():
    # A credit larger than the matching debit can't drive a bucket negative.
    rows = [
        {
            "month": "2026-06",
            "category": "fuel",
            "amount": 1000.0,
            "card": "HSBC Live+",
        },
        {
            "month": "2026-06",
            "category": "fuel",
            "amount": -4000.0,
            "card": "HSBC Live+",
        },
    ]
    svc = InMemorySessionService()

    async def run():
        await import_rows(svc, "optimizer", "user", rows)
        s = await svc.create_session(app_name="optimizer", user_id="user")
        return s.state.get(_STATE_KEY)

    log = asyncio.run(run())
    bucket = log["2026-06"]
    assert bucket["by_category"]["fuel"] == 0.0
    assert bucket["by_card"]["HSBC Live+"] == 0.0


def test_import_skips_future_dated_rows():
    # A far-future date would sort highest, survive pruning and evict real
    # months, or inflate YTD — reject it.
    rows = [
        {
            "month": "2099-01",
            "category": "dining",
            "amount": 9999.0,
            "card": "HSBC Live+",
        },
        {
            "month": "2026-06",
            "category": "dining",
            "amount": 2000.0,
            "card": "HSBC Live+",
        },
    ]
    svc = InMemorySessionService()

    async def run():
        summary = await import_rows(svc, "optimizer", "user", rows)
        s = await svc.create_session(app_name="optimizer", user_id="user")
        return summary, s.state.get(_STATE_KEY)

    summary, log = asyncio.run(run())
    assert summary["skipped_future_date"] == 1
    assert summary["imported"] == 1
    assert "2099-01" not in log
    assert log["2026-06"]["by_card"]["HSBC Live+"] == 2000.0
