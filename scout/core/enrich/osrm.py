import httpx

from scout.core.enrich.base import EnrichmentResult
from scout.core.models import EnrichedListing

_OSRM = "https://router.project-osrm.org/route/v1/driving"


async def enrich_drive_time(
    item: EnrichedListing,
    client: httpx.AsyncClient,
    *,
    city_centres: dict[str, tuple[float, float]],
) -> EnrichmentResult:
    listing = item.listing
    if listing.lat is None or listing.lon is None:
        return EnrichmentResult(success=False, error="no coordinates")
    centre = city_centres.get(listing.city)
    if centre is None:
        return EnrichmentResult(success=False, error=f"unknown city {listing.city}")
    cl_lat, cl_lon = centre
    url = f"{_OSRM}/{listing.lon},{listing.lat};{cl_lon},{cl_lat}"
    try:
        resp = await client.get(url, params={"overview": "false"}, timeout=15)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        return EnrichmentResult(success=False, error=f"{type(exc).__name__}: {exc}")
    routes = resp.json().get("routes") or []
    if not routes:
        return EnrichmentResult(success=False, error="no route")
    return EnrichmentResult(
        success=True,
        payload={
            "drive_min": int(round(routes[0]["duration"] / 60)),
            "distance_km": round(routes[0]["distance"] / 1000, 1),
        },
    )
