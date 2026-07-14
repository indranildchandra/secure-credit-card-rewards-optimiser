"""Offline tests for the web-search amount sanitiser (privacy invariant #2).

Covers the pure ``_strip_amounts`` heuristic and verifies that ``ddg_search``
sanitises the outbound query before it reaches the network. The DDGS client is
stubbed — these tests never make a real network call.
"""

import importlib.util
import pathlib

# Load the module directly from its file so this test does not depend on the
# eager ``tools/__init__.py`` import chain (keeps it isolated and fast).
_MODULE_PATH = (
    pathlib.Path(__file__).resolve().parent.parent / "tools" / ("duckduckgo_search.py")
)
_spec = importlib.util.spec_from_file_location("duckduckgo_search", _MODULE_PATH)
ddg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ddg)

_strip_amounts = ddg._strip_amounts
ddg_search = ddg.ddg_search


def test_strips_currency_and_amount_keeps_useful_tokens():
    out = _strip_amounts("Croma Tata Neu Rs.85,000 offer 2026")
    assert "85,000" not in out
    assert "85000" not in out
    # the "Rs" currency marker is gone (no standalone token)...
    assert "rs" not in out.lower().split()
    # ...but the merchant, card and recency-year tokens survive.
    assert "Croma" in out
    assert "Tata Neu" in out
    assert "offer" in out
    assert "2026" in out


def test_strips_rupee_symbol_comma_grouped_amount():
    out = _strip_amounts("HDFC Millennia ₹1,50,000 cashback")
    assert "1,50,000" not in out
    assert "₹" not in out
    assert "150000" not in out
    assert "HDFC Millennia" in out
    assert "cashback" in out


def test_strips_inr_prefixed_amount():
    out = _strip_amounts("Amazon Pay INR 50000 reward")
    assert "50000" not in out
    assert "inr" not in out.lower()
    assert "Amazon Pay" in out
    assert "reward" in out


def test_strips_trailing_currency_word():
    out = _strip_amounts("Swiggy HSBC Live+ 12,500 rupees")
    assert "12,500" not in out
    assert "rupees" not in out.lower()
    assert "Swiggy" in out
    assert "HSBC Live+" in out


def test_bare_non_year_four_digit_is_stripped():
    out = _strip_amounts("Croma amount 8500 offer")
    assert "8500" not in out
    assert "Croma" in out
    assert "offer" in out


def test_clean_merchant_card_year_query_passes_through_unchanged():
    query = "HSBC Live+ Swiggy offer devaluation June 2026"
    assert _strip_amounts(query) == query


class _StubDDGS:
    """Records the query passed to ``.text`` instead of hitting the network."""

    last_query = None
    last_timeout = None

    def __init__(self, **kwargs):
        # The tool constructs DDGS(timeout=...); capture it so we can assert the
        # explicit timeout is actually passed through.
        _StubDDGS.last_timeout = kwargs.get("timeout")

    def text(self, query, max_results=10):
        _StubDDGS.last_query = query
        return [{"title": "T", "href": "http://x", "body": "snippet"}]


def test_ddg_search_sends_sanitised_query(monkeypatch):
    monkeypatch.setattr(ddg, "DDGS", _StubDDGS)
    result = ddg_search("Croma Tata Neu Rs.85,000 offer 2026")

    sent = _StubDDGS.last_query
    assert sent is not None
    assert "85,000" not in sent
    assert "Rs" not in sent
    assert "Croma" in sent
    assert "2026" in sent
    # the header echoes the (already sanitised) query, not the raw amount.
    assert "85,000" not in result


def test_ddg_search_passes_explicit_timeout(monkeypatch):
    # Demo-safety: the search must run with a bounded timeout, never unbounded.
    monkeypatch.setattr(ddg, "DDGS", _StubDDGS)
    ddg_search("HSBC Live+ Swiggy offer 2026")
    assert _StubDDGS.last_timeout == ddg._SEARCH_TIMEOUT_SECONDS
    assert isinstance(_StubDDGS.last_timeout, (int, float))


def test_ddg_search_degrades_gracefully_on_failure(monkeypatch):
    # Network failure / timeout must NOT raise — the tool returns a short string
    # so the agent can say "no live data" and still give its recommendation.
    class _BoomDDGS:
        def __init__(self, **kwargs):
            pass

        def text(self, query, max_results=10):
            raise TimeoutError("connection timed out")

    monkeypatch.setattr(ddg, "DDGS", _BoomDDGS)
    result = ddg_search("HSBC Live+ Swiggy offer 2026")
    assert isinstance(result, str)
    assert "Search failed" in result  # graceful, not an exception
