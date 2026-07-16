from datetime import datetime, UTC

import httpx
import pytest
import respx

from scout.providers.es.enrich.sncziflood import enrich_flood
from scout.core.models import EnrichedListing, Listing


def _item(lat=41.5, lon=2.0):
    l = Listing(
        portal="idealista", external_id="x", city="barcelona", url="http://x",
        price_eur=150000, size_m2=120, bedrooms=3, bathrooms=2,
        municipality="Terrassa", province="Barcelona", address="x",
        lat=lat, lon=lon, description="", days_on_market=0,
        cadastral_ref=None, raw_json="{}", first_seen_at=datetime.now(UTC),
    )
    return EnrichedListing(listing=l)


@pytest.mark.asyncio
@respx.mock
async def test_flood_T100_zone():
    """Returns the PERIODO_RETORNO value from the WMS GeoJSON response."""
    respx.get(url__regex=r"https://wms\.mapama\.gob\.es/sig/.+").mock(
        return_value=httpx.Response(
            200,
            text='{"features":[{"properties":{"PERIODO_RETORNO":"T100"}}]}',
        )
    )
    async with httpx.AsyncClient() as client:
        r = await enrich_flood(_item(), client)
    assert r.success and r.payload["return_period"] == "T100"


@pytest.mark.asyncio
@respx.mock
async def test_flood_no_features_means_no_zone():
    """Returns 'none' when the WMS response contains an empty features array."""
    respx.get(url__regex=r"https://wms\.mapama\.gob\.es/sig/.+").mock(
        return_value=httpx.Response(200, text='{"features":[]}')
    )
    async with httpx.AsyncClient() as client:
        r = await enrich_flood(_item(), client)
    assert r.success and r.payload["return_period"] == "none"


@pytest.mark.asyncio
async def test_flood_skipped_without_coords():
    """Soft-fails immediately when the listing has no coordinates."""
    async with httpx.AsyncClient() as client:
        r = await enrich_flood(_item(lat=None, lon=None), client)
    assert r.success is False
