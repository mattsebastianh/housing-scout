"""Degraded-render guard for the Idealista scraper.

ScrapeOps' DataDome bypass intermittently returns a near-empty render with only
a card or two even when the search has many results. Because the parser still
found >0 listings, this previously slipped through and produced a near-empty
report (the 2026-05-30 `fetched: 1` runs). `scrape()` now re-fetches the first
page when it parses suspiciously few cards yet advertises many more results.
"""

import scout.providers.es.scrape.idealista as ide
from scout.providers.es.scrape.idealista import _LOW_YIELD_REFETCHES, scrape


def _card(eid: int) -> str:
    return (
        f'<article class="item" data-element-id="{eid}">'
        f'<a class="item-link" href="/inmueble/{eid}/" '
        f'title="Chalet en Calle {eid}, Vallirana, Barcelona"></a>'
        f'<span class="item-price">200.000 €</span>'
        f'<span class="item-detail">3 hab.</span>'
        f'<span class="item-detail">120 m²</span>'
        f'<div class="item-description">casa con parcela</div>'
        f"</article>"
    )


def _page(n_cards: int, advertised_total: int) -> str:
    cards = "".join(_card(i) for i in range(n_cards))
    return (
        "<!DOCTYPE html><html><head>"
        f'<meta name="description" content="{advertised_total} casas y chalets '
        'en Barcelona, a partir de 150.000 euros.">'
        f'</head><body><section class="items-list">{cards}</section></body></html>'
    )


def _install_fetch(monkeypatch, pages: list[str]) -> dict:
    """Mock `_fetch_via_scrapeops` to serve `pages` in order (repeats the last)."""
    state = {"n": 0}

    def _fetch(client, api_key, url):  # noqa: ANN001
        idx = min(state["n"], len(pages) - 1)
        state["n"] += 1
        return pages[idx]

    monkeypatch.setenv("SCRAPEOPS_API_KEY", "test-key")
    monkeypatch.setattr(ide, "_fetch_via_scrapeops", _fetch)
    return state


def _scrape():
    return scrape(
        city="barcelona",
        price_min=150_000,
        price_max=250_000,
        pages=1,
        delay_ms=0,
        geocode=False,
    )


def test_refetches_degraded_first_page(monkeypatch):
    """Re-fetches when the first render is degraded (few cards vs. high advertised total) and accepts the healthy retry."""
    # First render is degraded (1 card, but page advertises 1120); the retry
    # gets a healthy render with the full result set.
    state = _install_fetch(monkeypatch, [_page(1, 1120), _page(6, 30)])
    result = _scrape()
    assert len(result) == 6
    assert state["n"] == 2  # one degraded fetch + one successful re-fetch


def test_small_result_set_not_refetched(monkeypatch):
    """A genuinely small result set (advertised total within threshold) is accepted without re-fetching."""
    # A genuinely small result set (advertised total within threshold) is
    # accepted as-is — no wasted re-fetch.
    state = _install_fetch(monkeypatch, [_page(3, 3)])
    result = _scrape()
    assert len(result) == 3
    assert state["n"] == 1


def test_persistent_degraded_gives_up(monkeypatch):
    """Retries a bounded number of times then accepts the degraded result rather than looping forever."""
    # If every render stays degraded, we retry a bounded number of times and
    # then accept what we have rather than looping forever.
    state = _install_fetch(monkeypatch, [_page(1, 1120)])
    result = _scrape()
    assert len(result) == 1
    assert state["n"] == 1 + _LOW_YIELD_REFETCHES
