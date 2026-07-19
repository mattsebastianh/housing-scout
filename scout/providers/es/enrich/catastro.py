import re
from typing import Any, Optional

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from scout.core.enrich.base import EnrichmentResult
from scout.core.models import EnrichedListing

_BASE = "https://ovc.catastro.meh.es/OVCServWeb/OVCWcfCallejero/COVCCallejero.svc/json/Consulta_DNPRC"

# INSPIRE WFS for cadastral parcels — used to resolve a cadastral reference from
# a coordinate when the listing carries no ref (the common case for Idealista
# cards). The OVC Consulta_RCCOOR JSON endpoint is unreliable/relocated; this WFS
# is stable and documented. EPSG:4326 in WFS 2.0.0 uses lat,lon (Y,X) axis order.
_WFS = "https://ovc.catastro.meh.es/INSPIRE/wfsCP.aspx"
_REF_RE = re.compile(
    r"<cp:nationalCadastralReference>\s*([0-9A-Z]+)\s*</cp:nationalCadastralReference>",
    re.IGNORECASE,
)


def _urbanistic_class(bi: dict[str, Any]) -> str | None:
    """Map the Catastro cadastral class to an urbanistic classification.

    The Catastro classifies each parcel as "UR" (urbana) or "RU" (rústica).
    These are not the same as a municipal PGOU classification, but for a house
    a rústica parcel carries the legal risk of non-developable land, so we map it
    to "no urbanizable" — exactly the signal ``score_legal`` penalises. Urban
    parcels map to "urbano" (no penalty).
    """
    cn = (bi.get("idbi") or {}).get("cn")
    if cn == "RU":
        return "no urbanizable"
    if cn == "UR":
        return "urbano"
    return None


def _to_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(str(v).strip())
    except (ValueError, TypeError):
        return None


def _extract(consulta: dict[str, Any]) -> dict[str, Any]:
    # The live JSON service wraps the body in `consulta_dnprcResult`; older
    # captures used `consulta_dnp`. Accept either.
    root = consulta.get("consulta_dnprcResult") or consulta.get("consulta_dnp") or consulta
    bi = root["bico"]["bi"]
    debi = bi.get("debi") or {}
    return {
        "use_code": debi.get("luso"),
        "built_m2": _to_int(debi.get("sfc")),
        "year_built": _to_int(debi.get("ant")),
        "urbanistic_class": _urbanistic_class(bi),
        "raw": bi,
    }


async def _ref_by_coords(
    lat: float, lon: float, client: httpx.AsyncClient
) -> Optional[str]:
    """Resolve the 14-char cadastral reference for a coordinate via INSPIRE WFS.

    Uses a ~10 m bbox around the point and returns the first parcel's
    ``nationalCadastralReference``. Best-effort: returns None on any failure.
    """
    eps = 0.00008  # ~9 m at these latitudes
    params = {
        "service": "wfs",
        "version": "2.0.0",
        "request": "GetFeature",
        "typenames": "cp:CadastralParcel",
        "srsname": "EPSG:4326",
        "bbox": f"{lat - eps},{lon - eps},{lat + eps},{lon + eps},EPSG:4326",
    }
    try:
        resp = await client.get(_WFS, params=params, timeout=15)
        resp.raise_for_status()
    except httpx.HTTPError:
        return None
    m = _REF_RE.search(resp.text)
    return m.group(1) if m else None


async def enrich_catastro(item: EnrichedListing, client: httpx.AsyncClient) -> EnrichmentResult:
    listing = item.listing
    ref = listing.cadastral_ref
    if not ref and listing.lat is not None and listing.lon is not None:
        ref = await _ref_by_coords(listing.lat, listing.lon, client)
    if not ref:
        return EnrichmentResult(success=False, error="no cadastral ref (coords lookup failed)")

    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential_jitter(initial=1, max=8),
            retry=retry_if_exception_type(httpx.HTTPError),
            reraise=True,
        ):
            with attempt:
                resp = await client.get(_BASE, params={"RefCat": ref}, timeout=10)
                resp.raise_for_status()
                data = resp.json()
    except httpx.HTTPError as exc:
        return EnrichmentResult(success=False, error=f"{type(exc).__name__}: {exc}")

    try:
        return EnrichmentResult(success=True, payload=_extract(data))
    except (KeyError, TypeError) as exc:
        return EnrichmentResult(success=False, error=f"parse error: {exc}")
