"""
Local CSV / statement import for the spend tracker.

Reads a transactions CSV entirely on-device (no mailbox access) and writes the
aggregated totals into the same ADK user-scoped state the optimiser reads
(``user:spend_log``), so cap/milestone tracking works without logging every
purchase by hand.

Split into a pure parser (``parse_spends_csv`` — no ADK, easily tested) and a
persistence step (``import_rows`` — writes via an ADK SessionService event).
"""

import csv
import io
from copy import deepcopy
from datetime import datetime, timezone

from tools.spend_tracker import _parse_amount, apply_spend_to_log, _STATE_KEY

# Flexible header mapping — first matching column (case-insensitive) wins.
_AMOUNT_COLS = ("amount", "amt", "value", "debit", "spent")
_CATEGORY_COLS = ("category", "merchant", "description", "narration", "details", "name")
_CARD_COLS = ("card", "account", "instrument")
_DATE_COLS = ("date", "txn date", "transaction date", "posting date")


def _pick(row: dict, names) -> str:
    for n in names:
        if n in row and row[n] not in (None, ""):
            return str(row[n]).strip()
    return ""


def _month_from_date(text: str) -> str:
    """Best-effort YYYY-MM from a date string; '' if unparseable."""
    text = (text or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y", "%d %b %Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m")
        except ValueError:
            continue
    return ""


def parse_spends_csv(text: str) -> dict:
    """Parse CSV text into normalised spend rows.

    Returns {"rows": [{month, category, amount, card}], "skipped": <int>}.
    Rows with a missing/non-positive/unparseable amount are counted in ``skipped``.
    """
    reader = csv.DictReader(io.StringIO(text))
    rows, skipped = [], 0
    for raw in reader:
        row = {(k or "").strip().lower(): v for k, v in raw.items()}
        try:
            amount = _parse_amount(_pick(row, _AMOUNT_COLS))
        except (ValueError, TypeError):
            skipped += 1
            continue
        if amount <= 0:
            skipped += 1
            continue
        rows.append(
            {
                "month": _month_from_date(_pick(row, _DATE_COLS)),
                "category": _pick(row, _CATEGORY_COLS) or "uncategorised",
                "amount": amount,
                "card": _pick(row, _CARD_COLS),
            }
        )
    return {"rows": rows, "skipped": skipped}


async def import_rows(session_service, app_name: str, user_id: str, rows: list) -> dict:
    """Merge parsed rows into the user's spend_log and persist via the session
    service. Returns a summary dict."""
    from google.adk.events import Event, EventActions

    session = await session_service.create_session(app_name=app_name, user_id=user_id)
    log = deepcopy(session.state.get(_STATE_KEY) or {})

    current_month = datetime.now(timezone.utc).strftime("%Y-%m")
    for r in rows:
        apply_spend_to_log(
            log, r.get("month") or current_month, r["category"], r["amount"], r["card"]
        )

    event = Event(
        author="csv-import",
        actions=EventActions(state_delta={_STATE_KEY: log}),
    )
    await session_service.append_event(session, event)
    return {
        "imported": len(rows),
        "total_amount": round(sum(r["amount"] for r in rows), 2),
        "months": sorted(log.keys()),
    }
