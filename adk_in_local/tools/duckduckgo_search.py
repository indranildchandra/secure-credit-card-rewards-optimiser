"""
DuckDuckGo Search Tool for ADK agents.

A plain Python function that ADK exposes as a callable tool.
No API key required — free web search via DuckDuckGo.

In this optimiser the LLM is instructed to author a FOCUSED query about the
merchant/vendor and candidate card(s) — e.g. "Croma Tata Neu Infinity latest
offer discount June 2026" — rather than passing the user's raw transaction
text. Only card and merchant names leave the machine; transaction amounts and
personal context stay local.
"""

from ddgs import DDGS


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
    try:
        results = DDGS().text(query, max_results=10)
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
