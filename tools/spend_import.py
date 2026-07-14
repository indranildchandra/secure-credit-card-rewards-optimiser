"""
Local CSV / statement import for the spend tracker.

Reads a transactions CSV entirely on-device (no mailbox access) and writes the
aggregated totals into the same ADK user-scoped state the optimiser reads
(``user:spend_log``), so cap/milestone tracking works without logging every
purchase by hand.

Split into a pure parser (``parse_spends_csv`` — no ADK, easily tested) and a
persistence step (``import_rows`` — writes via an ADK SessionService event).

Correctness guards baked into the pipeline:
  * **Net, don't inflate.** Real statements mix debits with refunds/credits.
    Credit columns, signed amounts and dr/cr indicators are parsed as *negative*
    (refund) rows that reduce net spend for the same card/category/month
    (floored at 0). Counting debits only would over-state YTD and trigger false
    fee-waiver / milestone completion.
  * **Don't guess an ambiguous card.** A CSV ``card`` value like "Axis" that maps
    to more than one held card is *not* booked to whichever card iterates first —
    the row is skipped and reported so the caller can re-import it with a specific
    card name.
  * **Don't trust far-future dates.** A bogus date (e.g. 2099-01) would sort
    highest, survive retention pruning and evict real months; a future date in the
    current year would inflate YTD. Rows dated after the current month are skipped.
"""

import csv
import io
from copy import deepcopy
from datetime import datetime, timezone

from tools.spend_tracker import (
    _parse_amount,
    apply_spend_to_log,
    _prune_old_months,
    _STATE_KEY,
)
from tools.card_tools import _resolve_card_name

# The shared card resolver (canonical name, or an ambiguity report) lives in
# card_tools. Rely on it; the local fallback only exists so this module keeps
# working if the sibling change that adds it hasn't landed yet.
try:
    from tools.card_tools import resolve_card_or_ambiguity
except ImportError:  # pragma: no cover - shared helper lands via a sibling change
    from tools.card_tools import find_matching_cards

    def resolve_card_or_ambiguity(card_name):
        info = find_matching_cards(card_name)
        matches = info.get("matches", [])
        if info.get("ambiguous"):
            return None, {
                "query": card_name,
                "matches": matches,
                "count": len(matches),
                "message": (
                    f"'{card_name}' is ambiguous — it matches {matches}. "
                    "Re-import this row with a specific card name."
                ),
            }
        if len(matches) == 1:
            return matches[0], None
        return None, None


# Flexible header mapping — first matching column (case-insensitive) wins.
_AMOUNT_COLS = ("amount", "amt", "value", "debit", "spent")
_CREDIT_COLS = ("credit", "cr", "refund")
_TYPE_COLS = ("type", "dr/cr", "cr/dr", "drcr", "transaction type", "txn type")
_CATEGORY_COLS = ("category", "merchant", "description", "narration", "details", "name")
_CARD_COLS = ("card", "account", "instrument")
_DATE_COLS = ("date", "txn date", "transaction date", "posting date")

# Tokens (substring match, case-insensitive) that a dr/cr indicator column may
# carry to flag a row's direction when a single signed-amount column is used.
_CREDIT_TYPE_TOKENS = ("credit", "cr", "refund")
_DEBIT_TYPE_TOKENS = ("debit", "dr")


def _pick(row: dict, names) -> str:
    for n in names:
        if n in row and row[n] not in (None, ""):
            return str(row[n]).strip()
    return ""


def _parse_signed_amount(text: str) -> float:
    """``_parse_amount`` plus sign handling: a leading '-' or accounting
    parentheses ``(1,200)`` denote a negative (credit/refund) amount. Raises
    ValueError/TypeError on anything that isn't a number after cleanup."""
    s = (text or "").strip()
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1].strip()
    value = _parse_amount(s)
    return -value if negative else value


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

    ``amount`` is *signed*: a positive value is a debit (spend), a negative value
    is a credit/refund (nets out against spend at import time). Credits are read
    from a dedicated credit/refund column, from a negative/parenthesised amount,
    or from a dr/cr indicator column. Rows with a missing/unparseable amount, or
    whose debit and credit exactly cancel (net 0), are counted in ``skipped``.
    """
    reader = csv.DictReader(io.StringIO(text))
    rows, skipped = [], 0
    for raw in reader:
        row = {(k or "").strip().lower(): v for k, v in raw.items()}
        amount_str = _pick(row, _AMOUNT_COLS)
        credit_str = _pick(row, _CREDIT_COLS)
        type_str = _pick(row, _TYPE_COLS).lower()

        net = 0.0
        have_value = False
        try:
            if amount_str:
                net += _parse_signed_amount(amount_str)
                have_value = True
            if credit_str:
                # A dedicated credit/refund column always reduces net spend.
                net -= abs(_parse_signed_amount(credit_str))
                have_value = True
        except (ValueError, TypeError):
            skipped += 1
            continue
        if not have_value:
            skipped += 1
            continue

        # A dr/cr indicator column disambiguates a single unsigned amount column.
        if type_str:
            if any(t in type_str for t in _CREDIT_TYPE_TOKENS):
                net = -abs(net)
            elif any(t in type_str for t in _DEBIT_TYPE_TOKENS):
                net = abs(net)

        if net == 0:
            skipped += 1
            continue

        rows.append(
            {
                "month": _month_from_date(_pick(row, _DATE_COLS)),
                "category": _pick(row, _CATEGORY_COLS) or "uncategorised",
                "amount": round(net, 2),
                "card": _pick(row, _CARD_COLS),
            }
        )
    return {"rows": rows, "skipped": skipped}


def _reduce_log(log: dict, month: str, category: str, amount: float, card: str) -> None:
    """Subtract a credit/refund ``amount`` (a positive magnitude) from the
    matching card/category buckets for ``month``, floored at 0 so a bucket can't
    go negative. Only touches buckets that already exist."""
    bucket = log.get(month)
    if bucket is None:
        return
    cat = (category or "uncategorised").strip().lower()
    by_cat = bucket.get("by_category", {})
    if cat in by_cat:
        by_cat[cat] = round(max(by_cat[cat] - amount, 0.0), 2)
    canonical = _resolve_card_name(card) if card else None
    if canonical:
        by_card = bucket.get("by_card", {})
        if canonical in by_card:
            by_card[canonical] = round(max(by_card[canonical] - amount, 0.0), 2)


async def import_rows(session_service, app_name: str, user_id: str, rows: list) -> dict:
    """Merge parsed rows into the user's spend_log and persist via the session
    service. Returns a summary dict.

    Rows are guarded before they touch durable state:
      * an ambiguous ``card`` value (maps to >1 held card) is skipped, not booked
        to an arbitrary card;
      * a date after the current month is skipped as bogus;
    both go into the returned ``skipped`` list (row index + reason + detail).
    Debits are applied first, then credits/refunds are netted out (floored at 0).
    """
    from google.adk.events import Event, EventActions

    session = await session_service.create_session(app_name=app_name, user_id=user_id)
    log = deepcopy(session.state.get(_STATE_KEY) or {})

    current_month = datetime.now(timezone.utc).strftime("%Y-%m")

    debits, credits, skipped = [], [], []
    for idx, r in enumerate(rows):
        card = r.get("card", "")
        month = r.get("month") or current_month

        # 1. Never book an ambiguous card to whichever card iterates first.
        _, ambiguity = resolve_card_or_ambiguity(card)
        if ambiguity:
            matches = ambiguity.get("matches") or ambiguity.get("candidates") or []
            message = (
                ambiguity.get("message")
                or ambiguity.get("note")
                or f"Ambiguous card {card!r}; specify which of {matches}."
            )
            skipped.append(
                {
                    "row": idx,
                    "card": card,
                    "reason": "ambiguous_card",
                    "error": message,
                    "matches": matches,
                }
            )
            continue

        # 2. Reject clearly-bogus future dates that would evict real months / YTD.
        if month > current_month:
            skipped.append(
                {
                    "row": idx,
                    "card": card,
                    "reason": "future_date",
                    "error": (
                        f"Date {month} is after the current month {current_month}; "
                        "skipped as bogus."
                    ),
                }
            )
            continue

        entry = {"month": month, "category": r["category"], "card": card}
        if r["amount"] >= 0:
            entry["amount"] = r["amount"]
            debits.append(entry)
        else:
            entry["amount"] = -r["amount"]  # store the credit as a positive magnitude
            credits.append(entry)

    # Apply debits first so credits have a bucket to net against.
    for d in debits:
        apply_spend_to_log(log, d["month"], d["category"], d["amount"], d["card"])
    for c in credits:
        _reduce_log(log, c["month"], c["category"], c["amount"], c["card"])

    _prune_old_months(log)  # bound the durable store, same as record_spend

    event = Event(
        author="csv-import",
        actions=EventActions(state_delta={_STATE_KEY: log}),
    )
    await session_service.append_event(session, event)

    debits_total = round(sum(d["amount"] for d in debits), 2)
    credits_total = round(sum(c["amount"] for c in credits), 2)
    return {
        "imported": len(debits) + len(credits),
        "debits_total": debits_total,
        "credits_total": credits_total,
        "net_total": round(debits_total - credits_total, 2),
        "total_amount": round(debits_total - credits_total, 2),
        "skipped": skipped,
        "skipped_count": len(skipped),
        "skipped_ambiguous": sum(1 for s in skipped if s["reason"] == "ambiguous_card"),
        "skipped_future_date": sum(1 for s in skipped if s["reason"] == "future_date"),
        "months": sorted(log.keys()),
    }
