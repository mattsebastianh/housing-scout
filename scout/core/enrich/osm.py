from math import inf
from typing import Any

import httpx
import structlog
from geopy.distance import geodesic
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from scout.core.enrich.base import EnrichmentResult
from scout.core.models import EnrichedListing

log = structlog.get_logger("enrich.osm")

_OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# The free Overpass endpoint rate-limits (429) and times out (504) on busy days.
# Retry those — plus 5xx and network errors — with exponential backoff + jitter.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_FETCH_ATTEMPTS = 4

# Process-local memo of Overpass payloads keyed by coordinates rounded to ~110 m
# cells. Listings at (almost) the same spot then share one request, cutting load
# on the rate-limited public endpoint. Reset per process (each daily run).
_AMENITY_CACHE: dict[tuple[float, float], dict[str, Any]] = {}


def _is_retryable_overpass(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUS
    return isinstance(exc, httpx.TransportError)


async def _fetch_overpass(client: httpx.AsyncClient, query: str) -> dict[str, Any]:
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(_FETCH_ATTEMPTS),
        wait=wait_exponential_jitter(initial=2, max=30),
        retry=retry_if_exception(_is_retryable_overpass),
        reraise=True,
        before_sleep=lambda rs: log.warning(
            "overpass.retry", attempt=rs.attempt_number,
            error=str(rs.outcome.exception()),
        ),
    ):
        with attempt:
            resp = await client.post(_OVERPASS_URL, data={"data": query}, timeout=30)
            resp.raise_for_status()
            return resp.json()

_QUERY_TEMPLATE = """
[out:json][timeout:30];
(
  node["shop"="supermarket"](around:5000,{lat},{lon});
  node["amenity"="pharmacy"](around:5000,{lat},{lon});
  node["amenity"="school"](around:5000,{lat},{lon});
  node["amenity"="kindergarten"](around:3000,{lat},{lon});
  node["amenity"="hospital"](around:8000,{lat},{lon});
  node["amenity"="clinic"](around:5000,{lat},{lon});
  node["amenity"="doctors"](around:5000,{lat},{lon});
  node["leisure"="park"](around:3000,{lat},{lon});
  node["leisure"="playground"](around:2000,{lat},{lon});
  node["railway"="station"](around:6000,{lat},{lon});
  node["public_transport"="station"](around:6000,{lat},{lon});
  node["highway"="motorway_junction"](around:15000,{lat},{lon});
  node["place"~"city|town|village"]["population"](around:25000,{lat},{lon});
);
out body;
"""


def _count(elements: list[dict[str, Any]], key: str, value: str) -> int:
    return sum(1 for e in elements if (e.get("tags") or {}).get(key) == value)


def _nearest_km(elements: list[dict[str, Any]], lat: float, lon: float,
                 key: str, values: set[str]) -> float | None:
    best = inf
    for e in elements:
        tags = e.get("tags") or {}
        if tags.get(key) in values:
            d = geodesic((lat, lon), (e["lat"], e["lon"])).km
            if d < best:
                best = d
    return None if best == inf else best


def _nearest_station_km(elements: list[dict[str, Any]], lat: float, lon: float) -> float | None:
    return _nearest_km(elements, lat, lon, "railway", {"station"}) or \
           _nearest_km(elements, lat, lon, "public_transport", {"station"})


def _nearest_motorway_km(elements: list[dict[str, Any]], lat: float, lon: float) -> float | None:
    return _nearest_km(elements, lat, lon, "highway", {"motorway_junction"})


def _municipality_population(elements: list[dict[str, Any]], lat: float, lon: float) -> int | None:
    """Return the population of the nearest OSM place node that carries a population tag."""
    best_pop: int | None = None
    best_d = inf
    for e in elements:
        tags = e.get("tags") or {}
        if tags.get("place") not in {"city", "town", "village"}:
            continue
        raw = tags.get("population")
        if not raw:
            continue
        try:
            pop = int(str(raw).replace(".", "").replace(",", "").replace(" ", ""))
        except ValueError:
            continue
        d = geodesic((lat, lon), (e.get("lat", lat), e.get("lon", lon))).km
        if d < best_d:
            best_d = d
            best_pop = pop
    return best_pop


async def enrich_osm(item: EnrichedListing, client: httpx.AsyncClient) -> EnrichmentResult:
    lat, lon = item.listing.lat, item.listing.lon
    if lat is None or lon is None:
        return EnrichmentResult(success=False, error="no coordinates")
    cache_key = (round(lat, 3), round(lon, 3))
    cached = _AMENITY_CACHE.get(cache_key)
    if cached is not None:
        return EnrichmentResult(success=True, payload=cached)
    query = _QUERY_TEMPLATE.format(lat=lat, lon=lon)
    try:
        data = await _fetch_overpass(client, query)
    except httpx.HTTPError as exc:
        return EnrichmentResult(success=False, error=f"{type(exc).__name__}: {exc}")
    elements = data.get("elements", [])
    schools = _count(elements, "amenity", "school") + _count(elements, "amenity", "kindergarten")
    healthcare = (
        _count(elements, "amenity", "hospital")
        + _count(elements, "amenity", "clinic")
        + _count(elements, "amenity", "doctors")
        + _count(elements, "amenity", "pharmacy")
    )
    payload = {
        "amenities_5km": {
            "supermarket": _count(elements, "shop", "supermarket"),
            "pharmacy": _count(elements, "amenity", "pharmacy"),
            "school": schools,
            "hospital": _count(elements, "amenity", "hospital"),
            "clinic": _count(elements, "amenity", "clinic") + _count(elements, "amenity", "doctors"),
            "park": _count(elements, "leisure", "park") + _count(elements, "leisure", "playground"),
            "healthcare_total": healthcare,
        },
        "nearest_station_km": _nearest_station_km(elements, lat, lon),
        "nearest_school_km": _nearest_km(
            elements, lat, lon, "amenity", {"school", "kindergarten"}
        ),
        "nearest_health_km": _nearest_km(
            elements, lat, lon, "amenity", {"hospital", "clinic", "doctors"}
        ),
        "nearest_motorway_km": _nearest_motorway_km(elements, lat, lon),
        "municipality_population": _municipality_population(elements, lat, lon),
    }
    _AMENITY_CACHE[cache_key] = payload
    return EnrichmentResult(success=True, payload=payload)
