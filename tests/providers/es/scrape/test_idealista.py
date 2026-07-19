from pathlib import Path

import httpx
import pytest
import respx

from scout.providers.es.scrape import idealista as ide
from scout.providers.es.scrape.idealista import (
    ScrapingBlockedError,
    _address_from_title,
    _geocode_listings,
    _is_attached,
    _municipality_from_title,
    _next_page_url,
    _parse_page,
    _parse_plot_m2,
    scrape,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_extracts_chalet_and_skips_flat():
    """Parses one chalet from the fixture and filters out the flat."""
    html = (FIXTURES / "idealista_barcelona.html").read_text(encoding="utf-8")
    listings = _parse_page(html, city="barcelona")
    # fixture has one chalet and one flat — the flat is filtered out
    assert len(listings) == 1
    l = listings[0]
    assert l.portal == "idealista"
    assert l.external_id == "98765432"
    assert l.city == "barcelona"
    assert l.url == "https://www.idealista.com/inmueble/98765432/"
    assert l.price_eur == 175000
    assert l.size_m2 == 165
    assert l.bedrooms == 4
    assert l.bathrooms == 2
    assert l.municipality == "Sant Cugat del Vallès"
    # coordinates are not present in Idealista list HTML
    assert l.lat is None
    assert l.lon is None


def test_is_attached_flags_pareado_and_adosado():
    """Returns True for pareado/adosado titles and False for independent/rustic/villa types."""
    assert _is_attached("Chalet adosado en Carrer X, Terrassa")
    assert _is_attached("Casa pareada en Avinguda Y, Sabadell")
    assert _is_attached("Chalet adosada en Z")
    # independent / rustic / villa types are kept
    assert not _is_attached("Chalet independiente en Carrer Major, Sant Cugat")
    assert not _is_attached("Casa o chalet en Vallirana")
    assert not _is_attached("Villa en Sitges")
    assert not _is_attached("Finca rústica en Olesa")


def test_parse_skips_pareado_and_adosado():
    """_parse_page drops attached listings and keeps only the independent one."""
    html = """
    <html><body>
      <article class="item" data-element-id="1">
        <a href="/inmueble/1/" class="item-link" title="Chalet adosado en Terrassa">x</a>
        <span class="item-price">200.000 €</span>
        <span class="item-detail">120 m²</span>
      </article>
      <article class="item" data-element-id="2">
        <a href="/inmueble/2/" class="item-link" title="Chalet independiente en Terrassa">x</a>
        <span class="item-price">210.000 €</span>
        <span class="item-detail">130 m²</span>
      </article>
    </body></html>
    """
    listings = _parse_page(html, city="barcelona")
    assert [l.external_id for l in listings] == ["2"]


def test_parse_plot_m2_variants():
    """Extracts plot size from various Spanish description phrasings and returns None when absent."""
    assert _parse_plot_m2("Chalet con parcela de 800 m²") == 800
    assert _parse_plot_m2("terreno de 1.200 m2 y piscina") == 1200
    assert _parse_plot_m2("Amplio solar de 650m² urbano") == 650
    assert _parse_plot_m2("650 m² de parcela") == 650
    assert _parse_plot_m2("Casa de 150 m² construidos") is None
    assert _parse_plot_m2("") is None


def test_parse_populates_plot_m2_from_description():
    """_parse_page mines plot_m2 from the listing description when present."""
    html = """
    <html><body>
      <article class="item" data-element-id="9">
        <a href="/inmueble/9/" class="item-link" title="Chalet independiente en Olesa">x</a>
        <span class="item-price">230.000 €</span>
        <span class="item-detail">160 m²</span>
        <div class="item-description">Bonito chalet con parcela de 750 m² y jardín.</div>
      </article>
    </body></html>
    """
    listings = _parse_page(html, city="barcelona")
    assert listings[0].plot_m2 == 750


_DETAIL_HTML = """
<html><body>
  <div class="details-property-feature-one">
    <div class="details-property_features">
      <ul>
        <li>Casa o chalet independiente</li>
        <li>116 m² construidos</li>
        <li>3 habitaciones</li>
        <li>1 baño</li>
        <li>Parcela de 1.759 m²</li>
      </ul>
    </div>
  </div>
</body></html>
"""


def test_parse_detail_page_extracts_bathrooms():
    """_parse_detail_page extracts bathrooms, bedrooms, and plot size from detail-page HTML."""
    from scout.providers.es.scrape.idealista import _parse_detail_page
    d = _parse_detail_page(_DETAIL_HTML)
    assert d["bathrooms"] == 1
    assert d["bedrooms"] == 3
    assert d["plot_m2"] == 1759


def test_parse_detail_page_handles_missing():
    """Returns all-None dict when the detail page contains no recognisable feature elements."""
    from scout.providers.es.scrape.idealista import _parse_detail_page
    d = _parse_detail_page("<html><body>nothing here</body></html>")
    assert d == {"bathrooms": None, "bedrooms": None, "plot_m2": None}


def test_fetch_listing_details_no_key_returns_empty(monkeypatch):
    """Returns an empty dict immediately when SCRAPEOPS_API_KEY is not set."""
    from scout.providers.es.scrape.idealista import fetch_listing_details
    monkeypatch.delenv("SCRAPEOPS_API_KEY", raising=False)
    assert fetch_listing_details("https://www.idealista.com/inmueble/1/") == {}


def test_fetch_listing_details_parses_via_scrapeops(monkeypatch):
    """Fetches a detail page via ScrapeOps and parses bathrooms, bedrooms, and plot size."""
    from scout.providers.es.scrape.idealista import fetch_listing_details
    monkeypatch.setenv("SCRAPEOPS_API_KEY", "test-key")
    with respx.mock:
        respx.get("https://proxy.scrapeops.io/v1/").mock(
            return_value=httpx.Response(200, text=_DETAIL_HTML)
        )
        d = fetch_listing_details("https://www.idealista.com/inmueble/110977766/")
    assert d["bathrooms"] == 1
    assert d["bedrooms"] == 3
    assert d["plot_m2"] == 1759


def test_parse_returns_empty_for_no_articles():
    """Returns an empty list when the page contains no article elements."""
    html = "<html><body><section class='items-list'></section></body></html>"
    listings = _parse_page(html, city="barcelona")
    assert listings == []


def test_parse_skips_article_without_id():
    """Skips article elements that lack a data-element-id attribute."""
    html = """
    <html><body>
      <article class="item">
        <a href="/inmueble/x/" class="item-link" title="Casa o chalet en Olesa">No id</a>
        <span class="item-price">175.000 €</span>
      </article>
    </body></html>
    """
    listings = _parse_page(html, city="valencia")
    assert listings == []


def test_parse_price_with_dot_separator():
    """Parses Spanish dot-separated price strings (e.g. '200.000 €') correctly."""
    html = """
    <html><body>
      <article class="item" data-element-id="1">
        <a href="/inmueble/1/" class="item-link" title="Casa o chalet en Terrassa">Casa</a>
        <span class="item-price">200.000 €</span>
        <span class="item-detail">100 m²</span>
      </article>
    </body></html>
    """
    listings = _parse_page(html, city="barcelona")
    assert listings[0].price_eur == 200000


def test_municipality_from_title():
    """Extracts the last location segment after 'en' as the municipality name."""
    assert (
        _municipality_from_title(
            "Casa o chalet independiente en Carrer Major, Centre, Sant Cugat del Vallès"
        )
        == "Sant Cugat del Vallès"
    )
    assert _municipality_from_title("Casa o chalet en Vallirana") == "Vallirana"
    assert _municipality_from_title("no-preposition-here") is None


def test_address_from_title():
    """Extracts the full location string after 'en' as the address."""
    assert (
        _address_from_title(
            "Casa o chalet independiente en Carrer Major, Centre, Sant Cugat del Vallès"
        )
        == "Carrer Major, Centre, Sant Cugat del Vallès"
    )
    assert _address_from_title("no-preposition-here") is None


def test_geocode_listings_populates_coords(monkeypatch):
    """Geocodes listings and caches identical addresses so Nominatim is called only once."""
    from datetime import datetime, UTC
    from scout.core.models import Listing

    def make(addr):
        return Listing(
            portal="idealista", external_id="x", city="barcelona",
            url="http://x", price_eur=200000, size_m2=120, bedrooms=3,
            bathrooms=0, municipality="Vallirana", province=None, address=addr,
            lat=None, lon=None, description="", days_on_market=0,
            cadastral_ref=None, raw_json="{}", first_seen_at=datetime.now(UTC),
        )

    calls = []

    class FakeLoc:
        latitude = 41.39
        longitude = 1.93

    def fake_geocode(query):
        calls.append(query)
        return FakeLoc()

    monkeypatch.setattr(ide, "_build_geocoder", lambda: fake_geocode)

    a, b = make("Carrer X, Vallirana"), make("Carrer X, Vallirana")
    _geocode_listings([a, b])

    assert a.lat == 41.39 and a.lon == 1.93
    assert b.lat == 41.39 and b.lon == 1.93
    # identical address geocoded once (cached)
    assert len(calls) == 1
    assert "España" in calls[0]


def test_geocode_listings_falls_back_to_municipality(monkeypatch):
    """Falls back to bare municipality name when the full street address geocoding misses."""
    from datetime import datetime, UTC
    from scout.core.models import Listing

    listing = Listing(
        portal="idealista", external_id="x", city="barcelona", url="http://x",
        price_eur=200000, size_m2=120, bedrooms=3, bathrooms=0,
        municipality="Mataró", province=None,
        address="Calle Caseta, Cirera, Mataró",
        lat=None, lon=None, description="", days_on_market=0,
        cadastral_ref=None, raw_json="{}", first_seen_at=datetime.now(UTC),
    )

    class FakeLoc:
        latitude = 41.54
        longitude = 2.44

    def fake_geocode(query):
        # full street address misses; bare municipality resolves
        if query.startswith("Mataró"):
            return FakeLoc()
        return None

    monkeypatch.setattr(ide, "_build_geocoder", lambda: fake_geocode)
    _geocode_listings([listing])
    assert listing.lat == 41.54 and listing.lon == 2.44


def test_geocode_listings_handles_miss(monkeypatch):
    """Leaves lat/lon as None when both the address and municipality geocoding miss."""
    from datetime import datetime, UTC
    from scout.core.models import Listing

    listing = Listing(
        portal="idealista", external_id="x", city="barcelona", url="http://x",
        price_eur=200000, size_m2=120, bedrooms=3, bathrooms=0,
        municipality="Nowhere", province=None, address="Nowhere",
        lat=None, lon=None, description="", days_on_market=0,
        cadastral_ref=None, raw_json="{}", first_seen_at=datetime.now(UTC),
    )
    monkeypatch.setattr(ide, "_build_geocoder", lambda: (lambda q: None))
    _geocode_listings([listing])
    assert listing.lat is None and listing.lon is None


def test_next_page_url_extracts_absolute_href():
    """Extracts and returns the absolute URL of the next-page link."""
    html = '<a class="icon-arrow-right-after" href="/venta-viviendas/barcelona-provincia/pagina-2.htm">→</a>'
    assert (
        _next_page_url(html)
        == "https://www.idealista.com/venta-viviendas/barcelona-provincia/pagina-2.htm"
    )


def test_next_page_url_none_when_absent():
    """Returns None when no next-page link is present in the HTML."""
    assert _next_page_url("<html><body>no next link</body></html>") is None


def test_scrape_raises_without_api_key(monkeypatch):
    """Raises RuntimeError immediately when SCRAPEOPS_API_KEY is not set."""
    monkeypatch.delenv("SCRAPEOPS_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="SCRAPEOPS_API_KEY"):
        scrape(city="barcelona", price_min=150000, price_max=250000, pages=1)


def test_scrape_fetches_and_parses_via_scrapeops(monkeypatch):
    """Calls ScrapeOps with the correct params (api_key, bypass, country, residential, chalet URL) and parses results."""
    monkeypatch.setenv("SCRAPEOPS_API_KEY", "test-key")
    html = (FIXTURES / "idealista_barcelona.html").read_text(encoding="utf-8")

    with respx.mock:
        route = respx.get("https://proxy.scrapeops.io/v1/").mock(
            return_value=httpx.Response(200, text=html)
        )
        listings = scrape(
            city="barcelona", price_min=150000, price_max=250000,
            pages=1, delay_ms=0, geocode=False,
        )

    assert route.called
    sent = route.calls[0].request.url
    assert sent.params["api_key"] == "test-key"
    assert sent.params["bypass"] == "datadome"
    assert sent.params["country"] == "es"
    assert sent.params["residential"] == "true"
    assert "venta-viviendas/barcelona-provincia" in sent.params["url"]
    assert "chalets" in sent.params["url"]

    assert len(listings) == 1
    assert listings[0].external_id == "98765432"
    assert listings[0].portal == "idealista"


def test_is_retryable_fetch():
    """Returns True for transient HTTP status codes (408/429/503) and timeouts, False otherwise."""
    req = httpx.Request("GET", "http://x")
    mk = lambda code: httpx.HTTPStatusError(
        "e", request=req, response=httpx.Response(code, request=req)
    )
    assert ide._is_retryable_fetch(mk(408))
    assert ide._is_retryable_fetch(mk(429))
    assert ide._is_retryable_fetch(mk(503))
    assert not ide._is_retryable_fetch(mk(404))
    assert ide._is_retryable_fetch(httpx.ConnectTimeout("timeout"))
    assert not ide._is_retryable_fetch(ValueError("nope"))


def test_scrape_retries_transient_500_then_succeeds(monkeypatch):
    """Retries on a transient 500 and succeeds on the second attempt."""
    import tenacity

    monkeypatch.setenv("SCRAPEOPS_API_KEY", "test-key")
    # zero-wait so the backoff does not slow the test
    monkeypatch.setattr(ide, "wait_exponential_jitter", lambda **kw: tenacity.wait_none())
    html = (FIXTURES / "idealista_barcelona.html").read_text(encoding="utf-8")

    with respx.mock:
        route = respx.get("https://proxy.scrapeops.io/v1/").mock(
            side_effect=[
                httpx.Response(500, text="transient"),
                httpx.Response(200, text=html),
            ]
        )
        listings = scrape(
            city="barcelona", price_min=150000, price_max=250000,
            pages=1, delay_ms=0, geocode=False,
        )

    assert route.call_count == 2
    assert len(listings) == 1


def test_scrape_gives_up_after_persistent_500(monkeypatch):
    """Raises HTTPStatusError after exhausting all retry attempts on a persistent 500."""
    import tenacity

    monkeypatch.setenv("SCRAPEOPS_API_KEY", "test-key")
    monkeypatch.setattr(ide, "wait_exponential_jitter", lambda **kw: tenacity.wait_none())

    with respx.mock:
        route = respx.get("https://proxy.scrapeops.io/v1/").mock(
            return_value=httpx.Response(500, text="still failing")
        )
        with pytest.raises(httpx.HTTPStatusError):
            scrape(
                city="valencia", price_min=150000, price_max=250000,
                pages=1, delay_ms=0, geocode=False,
            )

    assert route.call_count == ide._FETCH_ATTEMPTS


def test_scrape_raises_blocked_when_no_listings(monkeypatch):
    """Raises ScrapingBlockedError when a page returns 200 but contains no listing articles."""
    monkeypatch.setenv("SCRAPEOPS_API_KEY", "test-key")
    with respx.mock:
        respx.get("https://proxy.scrapeops.io/v1/").mock(
            return_value=httpx.Response(200, text="<html><body>blocked</body></html>")
        )
        with pytest.raises(ScrapingBlockedError):
            scrape(
                city="barcelona", price_min=150000, price_max=250000,
                pages=1, delay_ms=0, geocode=False,
            )
