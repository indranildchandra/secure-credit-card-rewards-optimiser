"""
Monthly spend / cap tracker — backed by ADK session state.

Caps and thresholds are central to the optimiser's logic (HSBC Live+ shares a
Rs.1,000/month cashback cap across Dining+Food+Grocery; Scapia needs Rs.20,000/
month for lounge access; Amex targets Rs.7 Lakh/year). These tools let the agent
record spends and answer "is the cap exhausted yet?".

Persistence: each tool takes a ``tool_context: ToolContext`` and reads/writes
``tool_context.state`` — the ADK framework persists this to the SQLite session
store configured in run.sh (so it survives across turns/restarts).

State shape (under key ``spend_log``):
    {
      "<YYYY-MM>": {
        "by_category": {"dining": 1234.0, ...},
        "by_card":     {"HSBC Live+": 1234.0, ...}
      },
      ...
    }
"""

from datetime import datetime, timezone

from google.adk.tools import ToolContext

from data.cards import CARDS
from tools.card_tools import _resolve_card_name

_STATE_KEY = "spend_log"


def _current_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _get_log(tool_context: ToolContext) -> dict:
    return tool_context.state.get(_STATE_KEY) or {}


def _month_bucket(log: dict, month: str) -> dict:
    bucket = log.get(month)
    if bucket is None:
        bucket = {"by_category": {}, "by_card": {}}
        log[month] = bucket
    return bucket


def _parse_amount(value) -> float:
    """Coerce an amount to float, tolerating common formats the model may send.

    Accepts numbers, or strings like "1,50,000", "₹1000", "Rs. 1,500", "INR 200".
    Raises ValueError on anything that isn't a number after cleanup.
    """
    if isinstance(value, bool):  # bool is an int subclass — reject it explicitly
        raise ValueError("amount must be a number, not a boolean")
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().lower()
    for token in ("₹", "rs.", "rs", "inr", ",", " "):
        s = s.replace(token, "")
    return float(s)  # may raise ValueError — caller handles it


def record_spend(
    tool_context: ToolContext, category: str, amount: float, card: str = ""
) -> str:
    """Record a spend for the current month so caps/thresholds can be tracked.

    Args:
        category: Spend category/merchant, e.g. "dining", "grocery", "upi".
        amount: Amount in Rupees.
        card: Card used (optional; fuzzy/alias accepted).

    Returns:
        A confirmation string with updated month totals.
    """
    try:
        amt = _parse_amount(amount)
    except (ValueError, TypeError):
        return (
            f"Could not read the amount {amount!r}. Please give it as a number, "
            "e.g. 1500."
        )

    month = _current_month()
    log = _get_log(tool_context)
    bucket = _month_bucket(log, month)

    cat = (category or "uncategorised").strip().lower()
    bucket["by_category"][cat] = round(bucket["by_category"].get(cat, 0.0) + amt, 2)

    canonical = _resolve_card_name(card) if card else None
    if canonical:
        bucket["by_card"][canonical] = round(
            bucket["by_card"].get(canonical, 0.0) + amt, 2
        )

    # Reassign so ADK detects the state mutation and persists it.
    tool_context.state[_STATE_KEY] = log

    card_txt = f" on {canonical}" if canonical else ""
    return (
        f"Recorded Rs.{amt:,.0f} in '{cat}'{card_txt} for {month}. "
        f"Month total for '{cat}': Rs.{bucket['by_category'][cat]:,.0f}."
    )


def get_spend_summary(tool_context: ToolContext) -> dict:
    """Return this month's spend totals by category and by card.

    Returns:
        dict: {month, by_category, by_card}. Empty maps if nothing recorded.
    """
    month = _current_month()
    bucket = _get_log(tool_context).get(month, {"by_category": {}, "by_card": {}})
    return {
        "month": month,
        "by_category": bucket.get("by_category", {}),
        "by_card": bucket.get("by_card", {}),
    }


def check_cap_status(tool_context: ToolContext, card_name: str) -> dict:
    """Report remaining headroom for a card's configured cap / threshold.

    Entirely config-driven: a card opts in by declaring a ``tracker`` block in
    cards.config. Three tracker types are supported (add the block to any card to
    enable tracking for it — no code changes):

      * ``combined_monthly_cashback`` — a cashback cap shared across several spend
        categories at a given rate (e.g. {categories, rate, cap_value}).
      * ``monthly_spend_threshold``  — a monthly spend target, optionally counting
        spends across several cards (e.g. {threshold, counts_cards}).
      * ``annual_spend_milestone``   — a year-to-date spend target ({target}).

    Args:
        card_name: Card to check (fuzzy/alias accepted).

    Returns:
        dict describing the cap, amount used, and whether it's exhausted/met,
        or a ``note`` if the card has no ``tracker`` configured.
    """
    canonical = _resolve_card_name(card_name)
    if not canonical:
        return {"error": f"Unknown card: {card_name}"}

    tracker = CARDS[canonical].get("tracker")
    if not tracker:
        return {
            "card": canonical,
            "note": "No machine-trackable cap/threshold configured for this card. "
            "Add a 'tracker' block in cards.config to enable it. "
            "See get_card_details for milestones and fee-waiver thresholds.",
        }

    month = _current_month()
    bucket = _get_log(tool_context).get(month, {"by_category": {}, "by_card": {}})
    by_cat = bucket.get("by_category", {})
    by_card = bucket.get("by_card", {})
    ttype = tracker.get("type")
    label = tracker.get("label", ttype)

    if ttype == "combined_monthly_cashback":
        cats = [c.lower() for c in tracker.get("categories", [])]
        rate = tracker.get("rate", 0.10)
        cap_value = tracker.get("cap_value", 0)
        # Symmetric substring match so a category recorded by merchant name
        # ("swiggy") counts against a tracker category ("food delivery") and
        # vice-versa.
        eligible_spend = round(
            sum(
                amt
                for cat, amt in by_cat.items()
                if any(c in cat or cat in c for c in cats)
            ),
            2,
        )
        cashback_earned = round(min(eligible_spend * rate, cap_value), 2)
        remaining = round(max(cap_value - cashback_earned, 0.0), 2)
        spend_to_cap = round(cap_value / rate, 2) if rate else 0.0
        return {
            "card": canonical,
            "cap": f"Rs.{cap_value:,.0f}/month {label} @ {rate * 100:g}%",
            "eligible_spend_this_month": eligible_spend,
            "cashback_earned": cashback_earned,
            "cashback_remaining": remaining,
            "exhausted": remaining <= 0,
            "note": (
                "Cap exhausted — these categories now earn the base rate."
                if remaining <= 0
                else f"~Rs.{spend_to_cap:,.0f} of eligible spend hits the cap; "
                f"Rs.{round(spend_to_cap - eligible_spend, 2):,.0f} of headroom left."
            ),
        }

    if ttype == "monthly_spend_threshold":
        threshold = tracker.get("threshold", 0)
        cards = tracker.get("counts_cards", [canonical])
        counted = round(sum(by_card.get(c, 0.0) for c in cards), 2)
        remaining = round(max(threshold - counted, 0.0), 2)
        return {
            "card": canonical,
            "threshold": f"Rs.{threshold:,.0f}/month — {label}",
            "spend_this_month": counted,
            "remaining_to_unlock": remaining,
            "met": remaining <= 0,
            "note": (
                f"{label} met for the month."
                if remaining <= 0
                else f"Spend Rs.{remaining:,.0f} more this month to reach it."
            ),
        }

    if ttype == "annual_spend_milestone":
        target = tracker.get("target", 0)
        year = datetime.now(timezone.utc).strftime("%Y")
        log = _get_log(tool_context)
        ytd = round(
            sum(
                b.get("by_card", {}).get(canonical, 0.0)
                for m, b in log.items()
                if m.startswith(year)
            ),
            2,
        )
        remaining = round(max(target - ytd, 0.0), 2)
        return {
            "card": canonical,
            "annual_target": f"Rs.{target:,.0f} — {label}",
            "spend_ytd": ytd,
            "remaining_to_target": remaining,
            "met": remaining <= 0,
            "note": (
                "Annual target reached — stop routing extra spends here."
                if remaining <= 0
                else f"Rs.{remaining:,.0f} more to hit the target."
            ),
        }

    return {
        "card": canonical,
        "note": f"Unknown tracker type '{ttype}' in cards.config for this card.",
    }


def check_fee_waiver_status(tool_context: ToolContext, card_name: str) -> dict:
    """Report progress toward a card's annual fee-waiver threshold.

    Config-driven via each card's ``fee_waiver`` block in cards.config:
      * ``{"lifetime_free": true}``            — no annual fee.
      * ``{"annual_spend": N, "fee": "..."}``  — fee waived once YTD spend hits N.
      * ``{"annual_spend": null, "fee": "..."}`` — annual fee with no spend waiver.

    Args:
        card_name: Card to check (fuzzy/alias accepted).

    Returns:
        dict describing the annual fee, the waiver threshold, year-to-date spend
        on the card, how much more is needed, and whether the fee is waived.
    """
    canonical = _resolve_card_name(card_name)
    if not canonical:
        return {"error": f"Unknown card: {card_name}"}

    fw = CARDS[canonical].get("fee_waiver")
    if not fw:
        return {
            "card": canonical,
            "note": "No fee-waiver info configured for this card. "
            "Add a 'fee_waiver' block in cards.config to enable tracking.",
        }

    if fw.get("lifetime_free"):
        return {
            "card": canonical,
            "lifetime_free": True,
            "note": "Lifetime free — no annual fee to waive.",
        }

    fee = fw.get("fee", "")
    threshold = fw.get("annual_spend")

    year = datetime.now(timezone.utc).strftime("%Y")
    log = _get_log(tool_context)
    ytd = round(
        sum(
            b.get("by_card", {}).get(canonical, 0.0)
            for m, b in log.items()
            if m.startswith(year)
        ),
        2,
    )

    if not threshold:
        return {
            "card": canonical,
            "annual_fee": fee,
            "spend_ytd": ytd,
            "waived": False,
            "note": f"Annual fee {fee} applies — no spend-based waiver for this card.",
        }

    remaining = round(max(threshold - ytd, 0.0), 2)
    return {
        "card": canonical,
        "annual_fee": fee,
        "waiver_threshold": threshold,
        "spend_ytd": ytd,
        "remaining_to_waiver": remaining,
        "waived": remaining <= 0,
        "note": (
            f"Fee {fee} is waived — Rs.{threshold:,.0f} annual spend reached."
            if remaining <= 0
            else f"Spend Rs.{remaining:,.0f} more this year to waive the {fee} fee."
        ),
    }
