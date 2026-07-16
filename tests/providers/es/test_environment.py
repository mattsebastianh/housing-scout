from datetime import datetime, UTC

import httpx
import pytest

from scout.providers.es.enrich.environment import enrich_air, enrich_noise, enrich_wildfire
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
    csv = tmp_path / "env.csv"
    csv.write_text(
        "municipality,province,no2_avg_ugm3,lden_db,wildfire_hazard_class,source_year\n"
        "Terrassa,Barcelona,22,60,3,2023\n",
        encoding="utf-8",
    )
    return csv


@pytest.mark.asyncio
async def test_air_returns_no2(tmp_path):
    """Returns NO₂ µg/m³ for a matching municipality/province row in the CSV."""
    async with httpx.AsyncClient() as client:
        r = await enrich_air(_item(), client, csv_path=_write_csv(tmp_path))
    assert r.success
    assert r.payload == {"no2_avg": 22.0}


@pytest.mark.asyncio
async def test_noise_returns_lden(tmp_path):
    """Returns Lden dB for a matching municipality/province row in the CSV."""
    async with httpx.AsyncClient() as client:
        r = await enrich_noise(_item(), client, csv_path=_write_csv(tmp_path))
    assert r.success
    assert r.payload == {"lden_db": 60.0}


@pytest.mark.asyncio
async def test_wildfire_returns_hazard_class(tmp_path):
    """Returns wildfire hazard class for a matching municipality/province row in the CSV."""
    async with httpx.AsyncClient() as client:
        r = await enrich_wildfire(_item(), client, csv_path=_write_csv(tmp_path))
    assert r.success
    assert r.payload == {"hazard_class": 3}


@pytest.mark.asyncio
async def test_unknown_municipality_fails_soft(tmp_path):
    """All three enrichers soft-fail when the municipality is absent from the CSV."""
    async with httpx.AsyncClient() as client:
        for fn in (enrich_air, enrich_noise, enrich_wildfire):
            r = await fn(_item(muni="Unknown"), client, csv_path=_write_csv(tmp_path))
            assert r.success is False
