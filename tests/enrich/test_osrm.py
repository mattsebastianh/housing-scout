from datetime import datetime, UTC

import httpx
import pytest
import respx

from scout.core.enrich.osrm import enrich_drive_time
from scout.core.models import EnrichedListing, Listing


CITY_CENTRES = {"barcelona": (41.3874, 2.1686), "valencia": (39.4699, -0.3763)}


def _item(city="barcelona", lat=41.5, lon=2.0):
    l = Listing(
        portal="idealista", external_id="x", city=city, url="http://x",
        price_eur=150000, size_m2=120, bedrooms=3, bathrooms=2,
        municipality="Terrassa", province="Barcelona", address="x",
        lat=lat, lon=lon, description="", days_on_market=0,
        cadastral_ref=None, raw_json="{}", first_seen_at=datetime.now(UTC),
    )
    return EnrichedListing(listing=l)


@pytest.mark.asyncio
@respx.mock
async def test_drive_time_parsed_to_minutes():
    """Converts the OSRM route duration in seconds to integer minutes."""
    respx.get(url__regex=r"https://router\.project-osrm\.org/route/.+").mock(
        return_value=httpx.Response(
            200, json={"routes": [{"duration": 1800.0, "distance": 25000.0}]}
        )
    )
    async with httpx.AsyncClient() as client:
        r = await enrich_drive_time(_item(), client, city_centres=CITY_CENTRES)
    assert r.success and r.payload["drive_min"] == 30
