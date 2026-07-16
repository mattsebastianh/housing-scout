from datetime import datetime, UTC

import httpx
import pytest

from scout.providers.es.enrich.neighbourhood import enrich_neighbourhood, _investment_hits
from scout.core.models import EnrichedListing, Listing


def _item(muni="Terrassa", prov="Barcelona"):
    l = Listing(
        portal="idealista", external_id="x", city="barcelona", url="http://x",
        price_eur=200000, size_m2=160, bedrooms=3, bathrooms=2,
        municipality=muni, province=prov, address="x",
        lat=41.5, lon=2.0, description="", days_on_market=0,
        cadastral_ref=None, raw_json="{}", first_seen_at=datetime.now(UTC),
    )
    return EnrichedListing(listing=l)


def _write_csv(tmp_path):
    csv = tmp_path / "nb.csv"
    csv.write_text(
        "municipality,province,primary_residence_pct,vut_per_1000_dwellings,source_year\n"
        "Terrassa,Barcelona,89,1.0,2021\n"
        "Barcelona,Barcelona,80,15.4,2021\n",
        encoding="utf-8",
    )
    return csv


@pytest.mark.asyncio
async def test_neighbourhood_commuter_town_zero_hits(tmp_path):
    """Commuter town with low VUT density returns primary_residence_pct and zero investment_hits."""
    async with httpx.AsyncClient() as client:
        r = await enrich_neighbourhood(_item(), client, csv_path=_write_csv(tmp_path))
    assert r.success
    assert r.payload["primary_residence_pct"] == 89
    assert r.payload["investment_hits"] == 0  # 1.0 VUT/1000 → below threshold


@pytest.mark.asyncio
async def test_neighbourhood_tourist_city_has_hits(tmp_path):
    """City with high VUT density accumulates investment_hits via floor-divide per 5-unit bracket."""
    async with httpx.AsyncClient() as client:
        r = await enrich_neighbourhood(_item(muni="Barcelona"), client, csv_path=_write_csv(tmp_path))
    assert r.success
    assert r.payload["investment_hits"] == 3  # 15.4 // 5 == 3


@pytest.mark.asyncio
async def test_neighbourhood_unknown_municipality(tmp_path):
    """Soft-fails when municipality is absent from the CSV."""
    async with httpx.AsyncClient() as client:
        r = await enrich_neighbourhood(_item(muni="Unknown"), client, csv_path=_write_csv(tmp_path))
    assert r.success is False


def test_investment_hits_capped():
    """investment_hits is 0 below threshold, increments per bracket, and caps at 5."""
    assert _investment_hits(0.0) == 0
    assert _investment_hits(4.9) == 0
    assert _investment_hits(5.0) == 1
    assert _investment_hits(10.3) == 2
    assert _investment_hits(100.0) == 5  # capped
