import json

import httpx
import pytest
import respx

from scout.providers.es.scrape import brightdata as bd
from scout.providers.es.scrape.idealista import ScrapingBlockedError

TRIGGER_URL = "https://api.brightdata.com/dca/trigger"
DATASET_URL = "https://api.brightdata.com/dca/dataset"

COLLECTOR = "c_test123"


def _record(**overrides):
    """A realistic Bright Data collector record (detail-page crawl output)."""
    rec = {
        "title": "Casa o chalet independiente en venta en Calle N-3",
        "price": {"value": 165000, "currency": "EUR", "symbol": "€"},
        "location": "Nord, Vilanova i la Geltrú",
        "size_m2": "119 m² construidos, 58 m² útiles",
        "bedrooms": "2 habitaciones",
        "description": (
            "Bonita casa con jardín en zona tranquila. Dispone de 2 baños "
            "completos y una parcela de 450 m² con piscina."
        ),
        "url": "https://www.idealista.com/inmueble/110069536/",
        "property_id": "110069536",
        "input": {"url": "https://www.idealista.com/venta-viviendas/..."},
    }
    rec.update(overrides)
    return rec


# ---------------------------------------------------------------- mapping


def test_record_to_listing_maps_all_fields():
    """Maps a full collector record onto every Listing field the pipeline uses."""
    l = bd._record_to_listing(_record(), city="barcelona")
    assert l is not None
    assert l.portal == "idealista"
    assert l.external_id == "110069536"
    assert l.city == "barcelona"
    assert l.url == "https://www.idealista.com/inmueble/110069536/"
    assert l.price_eur == 165000
    assert l.size_m2 == 119  # built area, not the useful-area second figure
    assert l.bedrooms == 2
    assert l.bathrooms == 2  # mined from the description
    assert l.plot_m2 == 450  # mined from the description
    assert l.municipality == "Vilanova i la Geltrú"
    assert l.address == "Calle N-3, Nord, Vilanova i la Geltrú"
    assert l.lat is None and l.lon is None
    assert json.loads(l.raw_json)["property_id"] == "110069536"


def test_record_to_listing_price_string_fallback():
    """Parses price when the collector returns it as display text, not a dict."""
    l = bd._record_to_listing(_record(price="225.000 €"), city="barcelona")
    assert l.price_eur == 225000


def test_record_to_listing_external_id_from_url():
    """Falls back to the /inmueble/<id>/ URL segment when property_id is absent."""
    l = bd._record_to_listing(_record(property_id=None), city="barcelona")
    assert l.external_id == "110069536"


def test_record_to_listing_drops_flats_and_attached():
    """Returns None for pisos and adosado/pareado records (detached-only search)."""
    flat = _record(title="Piso en venta en Calle Mayor")
    attached = _record(title="Chalet adosado en venta en Calle de Velázquez")
    assert bd._record_to_listing(flat, city="barcelona") is None
    assert bd._record_to_listing(attached, city="barcelona") is None


def test_record_to_listing_missing_price_returns_none():
    """Skips records without a parseable price (parity with the HTML parser)."""
    assert bd._record_to_listing(_record(price=None), city="barcelona") is None


def test_record_to_listing_tolerates_missing_optional_fields():
    """Maps records lacking bedrooms/description without raising; counts stay 0."""
    l = bd._record_to_listing(
        _record(bedrooms=None, description=None, size_m2=None),
        city="barcelona",
    )
    assert l.bedrooms == 0
    assert l.bathrooms == 0
    assert l.size_m2 == 0
    assert l.plot_m2 is None
    assert l.description == ""


def test_municipality_without_area_part():
    """A location with no comma (plain municipality) maps as-is."""
    l = bd._record_to_listing(_record(location="Castellet i la Gornal"), city="barcelona")
    assert l.municipality == "Castellet i la Gornal"
    assert l.address == "Calle N-3, Castellet i la Gornal"


# ---------------------------------------------------------------- transport


def _mock_trigger_and_dataset(respx_mock, records, *, building_first=True):
    respx_mock.post(TRIGGER_URL).mock(
        return_value=httpx.Response(200, json={"collection_id": "j_abc123"})
    )
    responses = []
    if building_first:
        responses.append(
            httpx.Response(202, json={"status": "building", "message": "not ready"})
        )
    responses.append(httpx.Response(200, json=records))
    respx_mock.get(DATASET_URL).mock(side_effect=responses)


@respx.mock
def test_scrape_triggers_polls_and_maps(monkeypatch, respx_mock):
    """Full flow: trigger the collector, poll past 'building', map records."""
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "test-key")
    monkeypatch.setattr(bd, "_POLL_INTERVAL_S", 0)
    _mock_trigger_and_dataset(respx_mock, [_record()])

    listings = bd.scrape(
        city="barcelona",
        price_min=150000,
        price_max=250000,
        collector_id=COLLECTOR,
        geocode=False,
    )

    assert len(listings) == 1
    assert listings[0].external_id == "110069536"

    trigger_call = respx_mock.calls[0].request
    assert trigger_call.url.params["collector"] == COLLECTOR
    assert trigger_call.headers["authorization"] == "Bearer test-key"
    body = json.loads(trigger_call.content)
    assert body == [
        {
            "url": (
                "https://www.idealista.com/venta-viviendas/barcelona-provincia/"
                "con-precio-desde_150000,precio-hasta_250000,chalets/"
                "?orden=publicado-desc"
            )
        }
    ]


@respx.mock
def test_scrape_pages_adds_pagination_inputs(monkeypatch, respx_mock):
    """pages=2 sends a second collector input for the pagina-2 URL."""
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "test-key")
    monkeypatch.setattr(bd, "_POLL_INTERVAL_S", 0)
    _mock_trigger_and_dataset(respx_mock, [_record()], building_first=False)

    bd.scrape(
        city="girona",
        price_min=150000,
        price_max=250000,
        pages=2,
        collector_id=COLLECTOR,
        geocode=False,
    )

    body = json.loads(respx_mock.calls[0].request.content)
    assert len(body) == 2
    assert body[1]["url"] == (
        "https://www.idealista.com/venta-viviendas/girona-provincia/"
        "con-precio-desde_150000,precio-hasta_250000,chalets/"
        "pagina-2.htm?orden=publicado-desc"
    )


@respx.mock
def test_scrape_empty_dataset_raises_blocked(monkeypatch, respx_mock):
    """An empty result array raises ScrapingBlockedError (parity with HTML path)."""
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "test-key")
    monkeypatch.setattr(bd, "_POLL_INTERVAL_S", 0)
    _mock_trigger_and_dataset(respx_mock, [], building_first=False)

    with pytest.raises(ScrapingBlockedError):
        bd.scrape(
            city="barcelona",
            price_min=150000,
            price_max=250000,
            collector_id=COLLECTOR,
            geocode=False,
        )


@respx.mock
def test_scrape_all_records_filtered_raises_blocked(monkeypatch, respx_mock):
    """A dataset of only flats/adosados yields no listings and raises."""
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "test-key")
    monkeypatch.setattr(bd, "_POLL_INTERVAL_S", 0)
    records = [_record(title="Piso en venta en Calle Mayor")]
    _mock_trigger_and_dataset(respx_mock, records, building_first=False)

    with pytest.raises(ScrapingBlockedError):
        bd.scrape(
            city="barcelona",
            price_min=150000,
            price_max=250000,
            collector_id=COLLECTOR,
            geocode=False,
        )


@respx.mock
def test_scrape_poll_timeout_raises_blocked(monkeypatch, respx_mock):
    """A job stuck on 'building' past the deadline raises ScrapingBlockedError."""
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "test-key")
    monkeypatch.setattr(bd, "_POLL_INTERVAL_S", 0)
    monkeypatch.setattr(bd, "_POLL_TIMEOUT_S", 0)
    respx_mock.post(TRIGGER_URL).mock(
        return_value=httpx.Response(200, json={"collection_id": "j_abc123"})
    )
    respx_mock.get(DATASET_URL).mock(
        return_value=httpx.Response(202, json={"status": "building"})
    )

    with pytest.raises(ScrapingBlockedError):
        bd.scrape(
            city="barcelona",
            price_min=150000,
            price_max=250000,
            collector_id=COLLECTOR,
            geocode=False,
        )


def test_scrape_requires_api_key(monkeypatch):
    """Raises RuntimeError when BRIGHTDATA_API_KEY is not set."""
    monkeypatch.delenv("BRIGHTDATA_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="BRIGHTDATA_API_KEY"):
        bd.scrape(
            city="barcelona",
            price_min=150000,
            price_max=250000,
            collector_id=COLLECTOR,
        )


def test_scrape_requires_collector_id(monkeypatch):
    """Raises RuntimeError when no collector id is supplied."""
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "test-key")
    with pytest.raises(RuntimeError, match="collector"):
        bd.scrape(
            city="barcelona",
            price_min=150000,
            price_max=250000,
            collector_id=None,
        )
