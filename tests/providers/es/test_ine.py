from datetime import datetime, UTC

import httpx
import pytest

from scout.providers.es.enrich.ine import enrich_zone_median
from scout.core.models import EnrichedListing, Listing


def _item(muni="Sant Cugat del Vallès", prov="Barcelona"):
    l = Listing(
        portal="idealista", external_id="x", city="barcelona", url="http://x",
        price_eur=200000, size_m2=160, bedrooms=3, bathrooms=2,
        municipality=muni, province=prov, address="x",
        lat=41.5, lon=2.0, description="", days_on_market=0,
        cadastral_ref=None, raw_json="{}", first_seen_at=datetime.now(UTC),
    )
    return EnrichedListing(listing=l)


@pytest.mark.asyncio
async def test_ine_finds_zone_median_from_seed(tmp_path):
    """Returns price_psqm and quarter for a matching municipality/province row."""
    csv = tmp_path / "ine.csv"
    csv.write_text(
        "municipality,province,price_psqm_eur,quarter\n"
        "Sant Cugat del Vallès,Barcelona,3850,2026Q1\n",
        encoding="utf-8",
    )
    async with httpx.AsyncClient() as client:
        r = await enrich_zone_median(_item(), client, csv_path=csv)
    assert r.success
    assert r.payload["price_psqm"] == 3850
    assert r.payload["quarter"] == "2026Q1"


@pytest.mark.asyncio
async def test_ine_unknown_municipality(tmp_path):
    """Soft-fails when the municipality is absent from the CSV."""
    csv = tmp_path / "ine.csv"
    csv.write_text(
        "municipality,province,price_psqm_eur,quarter\n",
        encoding="utf-8",
    )
    async with httpx.AsyncClient() as client:
        r = await enrich_zone_median(_item(muni="Unknown"), client, csv_path=csv)
    assert r.success is False
