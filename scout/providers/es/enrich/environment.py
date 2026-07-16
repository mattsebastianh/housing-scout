"""
Local environmental enrichers — back the three ``score_environmental`` inputs
that were read but never populated: wildfire hazard, noise (Lden), and air
quality (NO₂). Together with the already-wired ``flood`` enricher they make the
environmental dimension multi-factor instead of flood-only.

Data is bundled as a small per-municipality CSV (same pattern as the INE price
and neighbourhood CSVs), sourced from:
  - NO₂ annual average (µg/m³): MITECO / EEA air-quality station network
  - Lden (dB): MITECO Mapas Estratégicos de Ruido (END) for the agglomeration
  - wildfire hazard class (1 low … 3 high): Catalan DECRET 64/1995 forest
    high-risk municipalities + Comunitat Valenciana forest-interface zones

These phenomena are hyper-local; the municipal value is a representative
residential figure, refreshed the same way the other CSVs are. Listings outside
the seed set fail soft (no key emitted → that factor is simply skipped by
``score_environmental``, which renormalises over whatever factors are present).
"""

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
                "no2_avg": float(r["no2_avg_ugm3"]),
                "lden_db": float(r["lden_db"]),
                "hazard_class": int(r["wildfire_hazard_class"]),
                "source_year": r["source_year"],
            }
    return rows


def _lookup(item: EnrichedListing, csv_path: Path | str) -> dict | None:
    listing = item.listing
    if not listing.municipality or not listing.province:
        return None
    rows = _load(str(csv_path))
    return rows.get((listing.municipality.strip().lower(), listing.province.strip().lower()))


_DEFAULT_CSV = "scout/providers/es/data/municipal_environment.csv"


async def enrich_air(
    item: EnrichedListing, client: httpx.AsyncClient, *, csv_path: Path | str = _DEFAULT_CSV
) -> EnrichmentResult:
    row = _lookup(item, csv_path)
    if row is None:
        return EnrichmentResult(success=False, error="no environment row")
    return EnrichmentResult(success=True, payload={"no2_avg": row["no2_avg"]})


async def enrich_noise(
    item: EnrichedListing, client: httpx.AsyncClient, *, csv_path: Path | str = _DEFAULT_CSV
) -> EnrichmentResult:
    row = _lookup(item, csv_path)
    if row is None:
        return EnrichmentResult(success=False, error="no environment row")
    return EnrichmentResult(success=True, payload={"lden_db": row["lden_db"]})


async def enrich_wildfire(
    item: EnrichedListing, client: httpx.AsyncClient, *, csv_path: Path | str = _DEFAULT_CSV
) -> EnrichmentResult:
    row = _lookup(item, csv_path)
    if row is None:
        return EnrichmentResult(success=False, error="no environment row")
    return EnrichmentResult(success=True, payload={"hazard_class": row["hazard_class"]})
