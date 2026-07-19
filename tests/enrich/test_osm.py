from datetime import datetime, UTC

import httpx
import pytest
import respx
import tenacity

from scout.core.enrich import osm as osm_mod
from scout.core.enrich.osm import enrich_osm
from scout.core.models import EnrichedListing, Listing


@pytest.fixture(autouse=True)
def _clear_osm_cache():
    osm_mod._AMENITY_CACHE.clear()
    yield
    osm_mod._AMENITY_CACHE.clear()


@pytest.fixture
def _fast_backoff(monkeypatch):
    """Zero-wait backoff so retry tests don't sleep."""
    monkeypatch.setattr(osm_mod, "wait_exponential_jitter", lambda **kw: tenacity.wait_none())


def _item(lat=41.5, lon=2.0):
    l = Listing(
        portal="idealista", external_id="x", city="barcelona", url="http://x",
        price_eur=150000, size_m2=120, bedrooms=3, bathrooms=2,
        municipality="Terrassa", province="Barcelona", address="x",
        lat=lat, lon=lon, description="", days_on_market=0,
        cadastral_ref=None, raw_json="{}", first_seen_at=datetime.now(UTC),
    )
    return EnrichedListing(listing=l)


_OVERPASS_FAKE = {
    "elements": [
        {"type": "node", "tags": {"shop": "supermarket"}, "lat": 41.5005, "lon": 2.0005},
        {"type": "node", "tags": {"amenity": "pharmacy"}, "lat": 41.501, "lon": 2.001},
        {"type": "node", "tags": {"amenity": "school"}, "lat": 41.502, "lon": 2.002},
        {"type": "node", "tags": {"amenity": "hospital"}, "lat": 41.503, "lon": 2.003},
        {"type": "node", "tags": {"railway": "station"}, "lat": 41.508, "lon": 2.008},
        {"type": "node", "tags": {"highway": "motorway_junction"}, "lat": 41.520, "lon": 2.020},
        {"type": "node", "tags": {"place": "city", "population": "92162", "name": "Terrassa"},
         "lat": 41.512, "lon": 2.012},
    ]
}


@pytest.mark.asyncio
@respx.mock
async def test_osm_counts_amenities_and_finds_nearest_station():
    """Counts amenities by category, finds nearest transit station, motorway, and municipality population."""
    respx.post("https://overpass-api.de/api/interpreter").mock(
        return_value=httpx.Response(200, json=_OVERPASS_FAKE)
    )
    async with httpx.AsyncClient() as client:
        r = await enrich_osm(_item(), client)
    p = r.payload
    assert r.success
    assert p["amenities_5km"]["supermarket"] == 1
    assert p["amenities_5km"]["pharmacy"] == 1
    assert p["amenities_5km"]["school"] == 1
    assert p["amenities_5km"]["hospital"] == 1
    assert 0 < p["nearest_station_km"] < 5
    assert p["nearest_motorway_km"] is not None and p["nearest_motorway_km"] > 0
    assert p["municipality_population"] == 92162


@pytest.mark.asyncio
@respx.mock
async def test_osm_retries_transient_429_then_succeeds(_fast_backoff):
    """Retries once on a 429 and succeeds on the second attempt."""
    route = respx.post("https://overpass-api.de/api/interpreter").mock(
        side_effect=[
            httpx.Response(429, text="Too Many Requests"),
            httpx.Response(200, json=_OVERPASS_FAKE),
        ]
    )
    async with httpx.AsyncClient() as client:
        r = await enrich_osm(_item(), client)
    assert route.call_count == 2
    assert r.success
    assert r.payload["amenities_5km"]["school"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_osm_soft_fails_after_persistent_504(_fast_backoff):
    """Soft-fails after exhausting all retry attempts on persistent 504 errors."""
    route = respx.post("https://overpass-api.de/api/interpreter").mock(
        return_value=httpx.Response(504, text="Gateway Timeout")
    )
    async with httpx.AsyncClient() as client:
        r = await enrich_osm(_item(), client)
    assert route.call_count == osm_mod._FETCH_ATTEMPTS
    assert not r.success
    assert "504" in r.error or "Server error" in r.error


@pytest.mark.asyncio
@respx.mock
async def test_osm_caches_by_rounded_coordinates():
    """Two requests within the same rounded coordinate cell hit the API once and share the cached result."""
    route = respx.post("https://overpass-api.de/api/interpreter").mock(
        return_value=httpx.Response(200, json=_OVERPASS_FAKE)
    )
    async with httpx.AsyncClient() as client:
        r1 = await enrich_osm(_item(lat=41.50001, lon=2.00001), client)
        # ~1 m away → same rounded cell → served from cache, no second request
        r2 = await enrich_osm(_item(lat=41.50002, lon=2.00002), client)
    assert route.call_count == 1
    assert r1.success and r2.success
    assert r1.payload == r2.payload
