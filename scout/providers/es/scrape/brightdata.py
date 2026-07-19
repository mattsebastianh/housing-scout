"""Idealista scraping via the Bright Data Scrapers collector API.

Alternative transport to the ScrapeOps path in ``idealista.py``: instead of
fetching and parsing search-results HTML ourselves, a pre-built Bright Data
collector (Scraper Studio, self-healing) crawls the search page *and* each
listing's detail page, returning structured records with full descriptions.
Selected via ``scrape.provider: brightdata`` in config.yaml; the collector id
lives in ``scrape.brightdata_collector_id``. Requires ``BRIGHTDATA_API_KEY``.

Cost model: 1 credit per record against the renewable monthly free tier
(5,000 credits); a one-page city scrape yields ~30 records.
"""

import json
import os
import re
import time
from datetime import datetime, UTC

import httpx
import structlog
from tenacity import (
    Retrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from scout.core.models import Listing
from scout.providers.es.scrape.idealista import (
    GEOCODE_COUNTRY,
    _BASE,
    _BATH_RE,
    _BED_RE,
    _CITY_SLUGS,
    _geocode_listings,
    _is_attached,
    _is_flat,
    _is_retryable_fetch,
    _parse_plot_m2,
    _parse_price,
    ScrapingBlockedError,
)
from scout.core.utils import safe_exc_str as _safe_exc_str

log = structlog.get_logger("scrape.brightdata")

_TRIGGER_API = "https://api.brightdata.com/dca/trigger"
_DATASET_API = "https://api.brightdata.com/dca/dataset"

_TRIGGER_ATTEMPTS = 4

# The collector job runs ~1.5–2 min for a one-page crawl (search page plus
# each listing's detail page). The dataset endpoint answers 202/"building"
# until the results are packaged, then 200 with the record array.
_POLL_INTERVAL_S = 15
_POLL_TIMEOUT_S = 15 * 60

_INMUEBLE_ID_RE = re.compile(r"/inmueble/(\d+)/?")
_FIRST_M2_RE = re.compile(r"(\d[\d.]*)\s*m(?:²|2)")


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def _search_urls(
    city: str,
    price_min: int,
    price_max: int,
    pages: int,
    *,
    slug: str | None = None,
    portal_base: str = _BASE,
) -> list[str]:
    """One collector input per results page, mirroring the ScrapeOps search URL."""
    slug = slug or _CITY_SLUGS.get(city, city)
    base = (
        f"{portal_base}/venta-viviendas/{slug}/"
        f"con-precio-desde_{price_min},precio-hasta_{price_max},chalets/"
    )
    urls = [f"{base}?orden=publicado-desc"]
    for n in range(2, pages + 1):
        urls.append(f"{base}pagina-{n}.htm?orden=publicado-desc")
    return urls


def _trigger(client: httpx.Client, api_key: str, collector_id: str, urls: list[str]) -> str:
    """Start a collector run for the given inputs; returns the collection id."""
    for attempt in Retrying(
        stop=stop_after_attempt(_TRIGGER_ATTEMPTS),
        wait=wait_exponential_jitter(initial=2, max=30),
        retry=retry_if_exception(_is_retryable_fetch),
        reraise=True,
        before_sleep=lambda rs: log.warning(
            "brightdata.trigger.retry",
            attempt=rs.attempt_number,
            error=_safe_exc_str(rs.outcome.exception()),
        ),
    ):
        with attempt:
            resp = client.post(
                _TRIGGER_API,
                params={"collector": collector_id, "queue_next": 1},
                headers=_headers(api_key),
                json=[{"url": u} for u in urls],
                timeout=60,
            )
            resp.raise_for_status()
            payload = resp.json()
    collection_id = payload.get("collection_id") or payload.get("id")
    if not collection_id:
        raise ScrapingBlockedError(
            f"Bright Data trigger returned no collection id: {payload!r}"
        )
    return str(collection_id)


def _poll_dataset(client: httpx.Client, api_key: str, collection_id: str) -> list[dict]:
    """Poll the dataset endpoint until the record array is ready."""
    deadline = time.monotonic() + _POLL_TIMEOUT_S
    while True:
        resp = client.get(
            _DATASET_API,
            params={"id": collection_id},
            headers=_headers(api_key),
            timeout=60,
        )
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                return data
            # a 200 with a status object means the job errored server-side
            raise ScrapingBlockedError(f"Bright Data dataset not a list: {data!r}")
        if resp.status_code == 202:  # {"status": "building"} — keep waiting
            if time.monotonic() >= deadline:
                raise ScrapingBlockedError(
                    f"Bright Data job {collection_id} still building after "
                    f"{_POLL_TIMEOUT_S}s"
                )
            time.sleep(_POLL_INTERVAL_S)
            continue
        resp.raise_for_status()


def _price_eur(value) -> int | None:
    if isinstance(value, dict):
        v = value.get("value")
        return int(v) if v is not None else None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        return _parse_price(value)
    return None


def _first_m2(text: str | None) -> int:
    """Built area from e.g. '263 m² construidos, 215 m² útiles' (first figure)."""
    if not text:
        return 0
    m = _FIRST_M2_RE.search(text)
    if not m:
        return 0
    digits = re.sub(r"[^\d]", "", m.group(1))
    return int(digits) if digits else 0


def _count_from(text: str | None, pattern: re.Pattern) -> int:
    if not text:
        return 0
    m = pattern.search(text)
    return int(m.group(1)) if m else 0


def _street_from_title(title: str) -> str | None:
    """Street part of a detail-page title, e.g.
    'Casa o chalet independiente en venta en Calle N-3' → 'Calle N-3'."""
    marker = " en venta en "
    if marker in title:
        return title.split(marker, 1)[1].strip() or None
    if " en " in title:  # list-style title fallback
        return title.split(" en ", 1)[1].strip() or None
    return None


def _record_to_listing(record: dict, *, city: str) -> Listing | None:
    """Map one collector record onto the pipeline's Listing dataclass.

    Returns None for records the ScrapeOps parser would also drop: flats,
    attached dwellings (adosado/pareado) and records without a price.
    """
    title = record.get("title") or ""
    if _is_flat(title) or _is_attached(title):
        return None

    price_eur = _price_eur(record.get("price"))
    if price_eur is None:
        return None

    url = record.get("url") or ""
    external_id = record.get("property_id")
    if not external_id:
        m = _INMUEBLE_ID_RE.search(url)
        external_id = m.group(1) if m else None
    if not external_id:
        return None

    location = (record.get("location") or "").strip()
    municipality = location.rsplit(",", 1)[-1].strip() or None if location else None
    street = _street_from_title(title)
    address = ", ".join(p for p in (street, location) if p) or None

    description = record.get("description") or ""

    return Listing(
        portal="idealista",
        external_id=str(external_id),
        city=city,
        url=url,
        price_eur=price_eur,
        size_m2=_first_m2(record.get("size_m2")),
        bedrooms=_count_from(record.get("bedrooms"), _BED_RE),
        bathrooms=_count_from(description, _BATH_RE),
        municipality=municipality,
        province=None,
        address=address,
        lat=None,
        lon=None,
        description=description,
        days_on_market=0,
        cadastral_ref=None,
        raw_json=json.dumps(record, ensure_ascii=False),
        first_seen_at=datetime.now(UTC),
        plot_m2=_parse_plot_m2(description),
    )


def scrape(
    *,
    city: str,
    price_min: int,
    price_max: int,
    pages: int = 1,
    delay_ms: int = 3000,  # unused — the collector paces its own crawl
    geocode: bool = True,
    collector_id: str | None = None,
    slug: str | None = None,
    portal_base: str = _BASE,
    geocode_country: str = GEOCODE_COUNTRY,
) -> list[Listing]:
    """Scrape Idealista search results via a Bright Data collector run.

    Triggers the collector with one input per results page, polls until the
    job's dataset is ready (~2 min), and maps the structured records to
    ``Listing`` objects. Raises ``ScrapingBlockedError`` when the run yields
    no usable listings, matching the ScrapeOps path's contract.
    ``slug``/``portal_base``/``geocode_country`` normally come from the
    resolved provider bundle; the defaults are this provider's data.
    """
    api_key = os.environ.get("BRIGHTDATA_API_KEY")
    if not api_key:
        raise RuntimeError("BRIGHTDATA_API_KEY env var is not set")
    if not collector_id:
        raise RuntimeError("Bright Data collector id is not configured")

    urls = _search_urls(city, price_min, price_max, pages, slug=slug, portal_base=portal_base)

    with httpx.Client() as client:
        collection_id = _trigger(client, api_key, collector_id, urls)
        log.info("brightdata.triggered", city=city, collection_id=collection_id)
        records = _poll_dataset(client, api_key, collection_id)

    listings = [
        l for r in records if (l := _record_to_listing(r, city=city)) is not None
    ]
    log.info(
        "brightdata.collected",
        city=city,
        records=len(records),
        listings=len(listings),
    )
    if not listings:
        raise ScrapingBlockedError(
            f"Bright Data run for {city!r} yielded no usable listings "
            f"({len(records)} raw records)."
        )

    if geocode:
        _geocode_listings(listings, geocode_country)
    return listings
