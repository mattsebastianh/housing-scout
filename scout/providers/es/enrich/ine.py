import csv
from functools import lru_cache
from pathlib import Path

import httpx

from scout.core.enrich.base import EnrichmentResult
from scout.core.models import EnrichedListing


@lru_cache(maxsize=8)
def _load(csv_path: str) -> dict[tuple[str, str], dict]:
    rows: dict[tuple[str, str], dict] = {}
    with Path(csv_path).open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows[(r["municipality"].strip().lower(), r["province"].strip().lower())] = {
                "price_psqm": int(r["price_psqm_eur"]),
                "quarter": r["quarter"],
            }
    return rows


async def enrich_zone_median(
    item: EnrichedListing,
    client: httpx.AsyncClient,
    *,
    csv_path: Path | str = "scout/providers/es/data/municipal_price_psqm.csv",
) -> EnrichmentResult:
    listing = item.listing
    if not listing.municipality or not listing.province:
        return EnrichmentResult(success=False, error="missing municipality/province")
    rows = _load(str(csv_path))
    key = (listing.municipality.strip().lower(), listing.province.strip().lower())
    found = rows.get(key)
    if found is None:
        return EnrichmentResult(success=False, error=f"no INE row for {listing.municipality}")
    return EnrichmentResult(success=True, payload=found)
