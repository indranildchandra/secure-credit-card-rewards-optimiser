"""
DuckDuckGo Search Tool for ADK agents.

A plain Python function that ADK exposes as a callable tool.
No API key required — free web search via DuckDuckGo.

In this optimiser the LLM is instructed to author a FOCUSED query about the
merchant/vendor and candidate card(s) — e.g. "Croma Tata Neu Infinity latest
offer discount June 2026" — rather than passing the user's raw transaction
text. Only card and merchant names leave the machine; transaction amounts and
personal context stay local.

Privacy invariant #2 (see AGENTS.md) says web-search queries must be built from
merchant/vendor and card names (plus a recency hint) — never the user's raw
sentence or transaction AMOUNTS. The prompt asks the model to comply, but a
local model can still leak amounts, so ``_strip_amounts`` below is a
deterministic, code-level guard applied to EVERY outbound query as a
belt-and-braces enforcement of that invariant.
"""

import re

from ddgs import DDGS

# Hard cap on how long the live web-search step may block. Without this the call
# can hang on flaky networks (e.g. a conference/venue wifi) and stall the whole
# "which card?" answer. On timeout/any failure ddg_search returns a short string
# and the agent simply reports "no live data" — the recommendation still stands.
_SEARCH_TIMEOUT_SECONDS = 5

# Currency markers that flag a transaction amount: "Rs", "Rs.", "₹", "INR",
# "rupee"/"rupees" (case-insensitive).
_CURRENCY = r"(?:rs\.?|inr|rupees?|₹)"


def _strip_amounts(query: str) -> str:
    """Remove likely transaction PII (currency amounts / numbers) from a query.

    Pure, deterministic and network-free so it is unit-testable. Enforces
    privacy invariant #2: strip currency symbols/words and their numbers, plus
    comma-grouped and long standalone numbers, while keeping useful tokens such
    as card names, merchant names and a bare 4-digit year (1900-2099) used as a
    recency hint.
    """
    s = query
    # currency marker directly followed by a number: "Rs.85,000", "₹85000",
    # "INR 50000".
    s = re.sub(rf"{_CURRENCY}\s*[\d.,]*\d", "", s, flags=re.IGNORECASE)
    # number directly followed by a currency marker: "85,000 rupees".
    s = re.sub(rf"\d[\d.,]*\s*{_CURRENCY}", "", s, flags=re.IGNORECASE)
    # any leftover standalone currency marker.
    s = re.sub(_CURRENCY, "", s, flags=re.IGNORECASE)
    # comma-grouped numbers: "85,000", "1,50,000".
    s = re.sub(r"\b\d{1,3}(?:,\d{2,3})+\b", "", s)
    # long standalone digit groups (5+ digits) are amounts, not years.
    s = re.sub(r"\b\d{5,}\b", "", s)
    # bare 4-digit numbers: keep plausible years, drop anything else.
    s = re.sub(
        r"\b\d{4}\b",
        lambda m: m.group() if 1900 <= int(m.group()) <= 2099 else "",
        s,
    )
    # tidy up whitespace and punctuation orphaned by the removals.
    s = re.sub(r"\s+([,.;:])", r"\1", s)
    s = re.sub(r"\s+", " ", s).strip(" ,.;:")
    return s


def ddg_search(query: str) -> str:
    """Search the web using DuckDuckGo and return a formatted summary of results.

    Use this to check for the LATEST credit-card offers, discounts, or
    devaluations for a specific merchant/vendor and card. Construct the query
    around the merchant/vendor name plus the candidate card name(s) and a
    recency hint (e.g. the current month/year) — do NOT paste the user's raw
    transaction sentence or any personal amounts.

    Args:
        query: A focused search query, e.g. "HSBC Live+ Swiggy offer devaluation June 2026".

    Returns:
        Formatted string with title, URL, and snippet for each result.
        Returns an error message if the search fails.
    """
    # Privacy invariant #2: sanitise the model-authored query at the single
    # choke point before it hits the network, so any leaked amounts / raw
    # transaction numbers never leave the machine regardless of what the model
    # wrote.
    query = _strip_amounts(query)
    try:
        results = DDGS(timeout=_SEARCH_TIMEOUT_SECONDS).text(query, max_results=10)
        if not results:
            return f"No results found for: {query}"

        lines = [f"Search results for: {query}\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r.get('title', 'No title')}")
            lines.append(f"   URL: {r.get('href', '')}")
            lines.append(f"   {r.get('body', '')[:300]}")
            lines.append("")
        return "\n".join(lines)
    except Exception as e:
        return f"Search failed: {e}"
