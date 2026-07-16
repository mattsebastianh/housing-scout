from datetime import datetime, UTC

import httpx
import pytest

from scout.core.enrich.base import EnrichmentResult, run_enrichers
from scout.core.models import EnrichedListing, Listing


def _enriched():
    l = Listing(
        portal="idealista", external_id="x", city="barcelona", url="http://x",
        price_eur=150000, size_m2=120, bedrooms=3, bathrooms=2,
        municipality="Terrassa", province="Barcelona", address="x",
        lat=41.5, lon=2.0, description="", days_on_market=0,
        cadastral_ref=None, raw_json="{}", first_seen_at=datetime.now(UTC),
    )
    return EnrichedListing(listing=l)


async def _ok_enricher(item, client):
    return EnrichmentResult(success=True, payload={"hello": "world"})


async def _fail_enricher(item, client):
    raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_run_enrichers_collects_successes_and_failures():
    """run_enrichers captures a successful result and wraps a raised exception as a failed result."""
    item = _enriched()
    async with httpx.AsyncClient() as client:
        results = await run_enrichers(
            item, client,
            {"ok": _ok_enricher, "bad": _fail_enricher},
        )
    assert results["ok"].success is True
    assert results["ok"].payload == {"hello": "world"}
    assert results["bad"].success is False
    assert "boom" in (results["bad"].error or "")
