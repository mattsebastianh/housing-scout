"""
Neighbourhood stability enricher — backs the two scoring inputs that were
previously hardcoded stubs (``primary_residence_pct``, ``investment_hits``).

Data comes from the same official open sources MiraTuZona wraps, fetched
directly: INE Censo 2021 (viviendas principales vs. secundarias/vacías per
municipality) and the regional tourism-rental registries (Catalunya RTC/HUT,
Comunitat Valenciana VUT). Bundled as a small CSV — same pattern as the INE
price CSV — and refreshed the same way.

``investment_hits`` is derived from the tourist-rental density (VUT per 1,000
dwellings): each full block of 5 VUT/1,000 is one "hit" of investment/tourism
pressure, capped at 5. A family-oriented commuter town scores 0; a tourist-heavy
city centre scores 2-3. ``score_neighbourhood`` turns each hit into a -2 penalty
on the stability sub-score.
"""

import csv
from functools import lru_cache
from pathlib import Path

import httpx

from scout.core.enrich.base import EnrichmentResult
from scout.core.models import EnrichedListing

# VUT density (per 1,000 dwellings) that constitutes one "investment hit".
_VUT_PER_HIT = 5.0
_MAX_HITS = 5


def _investment_hits(vut_per_1000: float) -> int:
    return min(_MAX_HITS, int(vut_per_1000 // _VUT_PER_HIT))


@lru_cache(maxsize=8)
def _load(csv_path: str) -> dict[tuple[str, str], dict]:
    rows: dict[tuple[str, str], dict] = {}
    with Path(csv_path).open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            vut = float(r["vut_per_1000_dwellings"])
            rows[(r["municipality"].strip().lower(), r["province"].strip().lower())] = {
                "primary_residence_pct": float(r["primary_residence_pct"]),
                "vut_per_1000_dwellings": vut,
                "investment_hits": _investment_hits(vut),
                "source_year": r["source_year"],
            }
    return rows


async def enrich_neighbourhood(
    item: EnrichedListing,
    client: httpx.AsyncClient,
    *,
    csv_path: Path | str = "scout/providers/es/data/municipal_neighbourhood.csv",
) -> EnrichmentResult:
    listing = item.listing
    if not listing.municipality or not listing.province:
        return EnrichmentResult(success=False, error="missing municipality/province")
    rows = _load(str(csv_path))
    key = (listing.municipality.strip().lower(), listing.province.strip().lower())
    found = rows.get(key)
    if found is None:
        return EnrichmentResult(success=False, error=f"no neighbourhood row for {listing.municipality}")
    return EnrichmentResult(success=True, payload=found)
