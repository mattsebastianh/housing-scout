import json
from typing import Any

import httpx

from scout.core.enrich.base import EnrichmentResult
from scout.core.models import EnrichedListing

_WMS = "https://wms.mapama.gob.es/sig/AguaCostas/SNCZI_LAMINASQ/wms.aspx"
_LAYER = "LAMINASQ.T500,LAMINASQ.T100,LAMINASQ.T10"


def _bbox(lat: float, lon: float, eps: float = 0.0005) -> str:
    return f"{lon - eps},{lat - eps},{lon + eps},{lat + eps}"


def _classify(features: list[dict[str, Any]]) -> str:
    periods = {(f.get("properties") or {}).get("PERIODO_RETORNO") for f in features}
    for p in ("T10", "T100", "T500"):
        if p in periods:
            return p
    return "none"


async def enrich_flood(item: EnrichedListing, client: httpx.AsyncClient) -> EnrichmentResult:
    if item.listing.lat is None or item.listing.lon is None:
        return EnrichmentResult(success=False, error="no coordinates")
    params = {
        "SERVICE": "WMS",
        "VERSION": "1.3.0",
        "REQUEST": "GetFeatureInfo",
        "LAYERS": _LAYER,
        "QUERY_LAYERS": _LAYER,
        "CRS": "EPSG:4326",
        "BBOX": _bbox(item.listing.lat, item.listing.lon),
        "WIDTH": 5, "HEIGHT": 5,
        "I": 2, "J": 2,
        "INFO_FORMAT": "application/json",
    }
    try:
        resp = await client.get(_WMS, params=params, timeout=15)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        return EnrichmentResult(success=False, error=f"{type(exc).__name__}: {exc}")
    try:
        data = json.loads(resp.text)
        features = data.get("features", [])
    except json.JSONDecodeError as exc:
        return EnrichmentResult(success=False, error=f"parse error: {exc}")
    return EnrichmentResult(success=True, payload={"return_period": _classify(features)})
