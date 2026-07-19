import os
import re
import time
from datetime import datetime, UTC

import httpx
import structlog
from bs4 import BeautifulSoup
from geopy.exc import GeocoderServiceError
from geopy.extra.rate_limiter import RateLimiter
from geopy.geocoders import Nominatim
from tenacity import (
    Retrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from scout.core.models import Listing
from scout.core.utils import safe_exc_str as _safe_exc_str

log = structlog.get_logger("scrape.idealista")

# ScrapeOps Proxy Aggregator — bypasses Idealista's DataDome bot protection.
# `bypass=datadome` drives a headless browser (JS render included) through
# residential proxies geotargeted to Spain. Requires SCRAPEOPS_API_KEY.
_SCRAPEOPS_API = "https://proxy.scrapeops.io/v1/"

# ScrapeOps returns these transiently when the upstream fetch/render or proxy
# hop fails (429 = rate limit / concurrency, 408 = timeout, 5xx = gateway).
# A short backoff usually recovers, so they are retried.
_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
_FETCH_ATTEMPTS = 4

# Degraded-render guard. A healthy Idealista first results page lists ~30 cards.
# ScrapeOps' DataDome bypass intermittently returns a near-empty render with
# only a card or two even when the search has many results; because the parser
# still found >0 listings, this previously slipped through and produced a
# near-empty report. When the first page parses fewer than this many cards yet
# advertises far more results, treat the render as degraded and re-fetch.
_MIN_FIRST_PAGE_LISTINGS = 5
_LOW_YIELD_REFETCHES = 2


def _is_retryable_fetch(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUS
    # network-level failures: timeouts, connection resets, etc.
    return isinstance(exc, httpx.TransportError)

_CITY_SLUGS: dict[str, str] = {
    "barcelona": "barcelona-provincia",
    "valencia": "valencia-provincia",
    "girona": "girona-provincia",
}

_BASE = "https://www.idealista.com"

# Country suffix appended to Nominatim geocode queries — this provider's data,
# exported to the registry as the ES bundle's ``geocode_country``.
GEOCODE_COUNTRY = "España"

# Title prefixes for non-detached dwellings — used to drop flats that slip
# through Idealista's `chalets` typology filter.
_FLAT_TYPES = {
    "piso", "ático", "atico", "estudio", "dúplex", "duplex",
    "apartamento", "loft", "buhardilla",
}

# Attached-dwelling markers in the title's type prefix. We want only detached
# (independent) houses/chalets, rustic properties and standalone villas, so we
# drop semi-detached (pareado) and terraced (adosado) listings.
_ATTACHED_MARKERS = ("paread", "adosad")


class ScrapingBlockedError(RuntimeError):
    pass


def _parse_price(text: str) -> int | None:
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def _parse_detail(spans: list[str], keyword: str) -> int:
    for s in spans:
        if keyword in s.lower():
            digits = re.sub(r"[^\d]", "", s)
            return int(digits) if digits else 0
    return 0


def _parse_size(spans: list[str]) -> int:
    for s in spans:
        if "m²" in s or "m2" in s:
            digits = re.sub(r"[^\d]", "", s)
            return int(digits) if digits else 0
    return 0


# Plot/land size, e.g. "parcela de 800 m²", "terreno de 1.200 m2",
# "solar de 650m²" or "800 m² de parcela". Idealista list pages do not expose
# plot size as a structured field, so we mine it from the free-text description.
_PLOT_BEFORE = re.compile(
    r"(?:parcela|terreno|solar)\s+(?:de\s+)?(\d[\d.]*)\s*m(?:²|2)",
    re.IGNORECASE,
)
_PLOT_AFTER = re.compile(
    r"(\d[\d.]*)\s*m(?:²|2)\s+(?:de\s+)?(?:parcela|terreno|solar)",
    re.IGNORECASE,
)


def _parse_plot_m2(text: str) -> int | None:
    """Best-effort plot (land) size in m² from a listing description."""
    if not text:
        return None
    for pattern in (_PLOT_BEFORE, _PLOT_AFTER):
        m = pattern.search(text)
        if m:
            digits = re.sub(r"[^\d]", "", m.group(1))
            if digits:
                return int(digits)
    return None


# Detail-page feature parsing. Idealista result cards often omit the bathroom
# count, but the listing's detail page lists it as "<li>N baño(s)</li>" in the
# property-features block. We fetch the detail page only for reported listings.
_BATH_RE = re.compile(r"(\d+)\s*(?:baño|aseo)", re.IGNORECASE)
_BED_RE = re.compile(r"(\d+)\s*(?:habitaci|dormitor)", re.IGNORECASE)


def _parse_detail_page(html: str) -> dict[str, int | None]:
    """Parse bathrooms (and backup bedrooms/plot) from a listing detail page."""
    soup = BeautifulSoup(html, "html.parser")
    nodes = soup.select('[class*="details-property-feature"] li')
    text = " ".join(li.get_text(" ", strip=True) for li in nodes)
    if not text:  # fallback to the characteristics summary near the title
        text = " ".join(
            s.get_text(" ", strip=True)
            for s in soup.select(".info-features span, .details-property li")
        )
    mb = _BATH_RE.search(text)
    mr = _BED_RE.search(text)
    return {
        "bathrooms": int(mb.group(1)) if mb else None,
        "bedrooms": int(mr.group(1)) if mr else None,
        "plot_m2": _parse_plot_m2(text),
    }


def fetch_listing_details(url: str, *, client: httpx.Client | None = None) -> dict[str, int | None]:
    """Fetch a listing's detail page via ScrapeOps and parse fields missing from
    result cards (bathrooms, plus bedrooms/plot as backup). Best-effort: returns
    an empty dict if the API key is absent or the fetch fails."""
    api_key = os.environ.get("SCRAPEOPS_API_KEY")
    if not api_key:
        return {}
    own_client = client is None
    cl = client or httpx.Client()
    try:
        html = _fetch_via_scrapeops(cl, api_key, url)
    except httpx.HTTPError as exc:
        log.warning("detail.fetch.failed", url=url, error=str(exc))
        return {}
    finally:
        if own_client:
            cl.close()
    return _parse_detail_page(html)


def _address_from_title(title: str) -> str | None:
    """Full location string from an Idealista title (everything after ' en ')."""
    if " en " not in title:
        return None
    return title.split(" en ", 1)[1].strip() or None


def _municipality_from_title(title: str) -> str | None:
    """Idealista titles read '{type} en {street}, {area}, {municipality}'."""
    address = _address_from_title(title)
    if not address:
        return None
    return address.rsplit(",", 1)[-1].strip() or None


def _is_flat(title: str) -> bool:
    ptype = title.split(" en ", 1)[0].strip().lower()
    first_word = ptype.split()[0] if ptype else ""
    return first_word in _FLAT_TYPES


def _is_attached(title: str) -> bool:
    """True for semi-detached (pareado) or terraced (adosado) dwellings.

    Idealista titles lead with the type, e.g. "Chalet adosado en…" or
    "Casa pareada en…". We only want detached/independent houses, so these
    are dropped at parse time (same approach as flats).
    """
    ptype = title.split(" en ", 1)[0].strip().lower()
    return any(marker in ptype for marker in _ATTACHED_MARKERS)


def _parse_page(html: str, *, city: str) -> list[Listing]:
    """Extract chalet listings from raw Idealista search-results HTML."""
    soup = BeautifulSoup(html, "html.parser")
    now = datetime.now(UTC)
    listings: list[Listing] = []

    for article in soup.select("article.item"):
        external_id = article.get("data-element-id") or article.get("data-adid")
        if not external_id:
            continue

        link = article.select_one("a.item-link")
        if not link:
            continue
        title = link.get("title") or link.get_text(strip=True) or ""
        if _is_flat(title) or _is_attached(title):
            continue

        href = link.get("href", "")
        url = href if href.startswith("http") else f"{_BASE}{href}"

        price_tag = article.select_one(".item-price")
        price_eur = _parse_price(price_tag.get_text(strip=True)) if price_tag else None
        if price_eur is None:
            continue

        detail_spans = [s.get_text(strip=True) for s in article.select("span.item-detail")]
        size_m2 = _parse_size(detail_spans)
        bedrooms = _parse_detail(detail_spans, "hab")
        bathrooms = _parse_detail(detail_spans, "baño") or _parse_detail(detail_spans, "wc")

        address = _address_from_title(title)
        municipality = _municipality_from_title(title)

        desc_tag = article.select_one(".item-description")
        description = desc_tag.get_text(strip=True) if desc_tag else ""

        plot_m2 = _parse_plot_m2(" ".join([description, *detail_spans]))

        listings.append(Listing(
            portal="idealista",
            external_id=str(external_id),
            city=city,
            url=url,
            price_eur=price_eur,
            size_m2=size_m2,
            bedrooms=bedrooms,
            bathrooms=bathrooms,
            municipality=municipality,
            province=None,
            address=address,
            lat=None,
            lon=None,
            description=description,
            days_on_market=0,
            cadastral_ref=None,
            raw_json="{}",
            first_seen_at=now,
            plot_m2=plot_m2,
        ))

    return listings


def _next_page_url(html: str) -> str | None:
    """Extract the absolute URL of the next results page, if present."""
    soup = BeautifulSoup(html, "html.parser")
    nxt = soup.select_one("a.icon-arrow-right-after")
    href = nxt.get("href") if nxt else None
    if not href:
        return None
    return href if href.startswith("http") else f"{_BASE}{href}"


# Total result count Idealista prints in the page meta/heading, e.g.
# "1.120 casas y chalets". Used to tell a degraded render (few cards parsed
# despite many advertised) apart from a legitimately small result set.
_TOTAL_RE = re.compile(r"([\d.]+)\s+casas y chalets", re.IGNORECASE)


def _advertised_total(html: str) -> int | None:
    m = _TOTAL_RE.search(html)
    if not m:
        return None
    digits = re.sub(r"[^\d]", "", m.group(1))
    return int(digits) if digits else None


def _fetch_via_scrapeops(client: httpx.Client, api_key: str, url: str) -> str:
    """Fetch a URL through the ScrapeOps Proxy Aggregator (residential + anti-bot).

    `bypass=datadome` runs a headless browser through Spanish residential
    proxies to clear Idealista's DataDome protection. Retries transient
    ScrapeOps failures (408/429/5xx, timeouts, connection errors) with
    exponential backoff + jitter before giving up.
    """
    for attempt in Retrying(
        stop=stop_after_attempt(_FETCH_ATTEMPTS),
        wait=wait_exponential_jitter(initial=2, max=30),
        retry=retry_if_exception(_is_retryable_fetch),
        reraise=True,
        before_sleep=lambda rs: log.warning(
            "scrapeops.retry",
            attempt=rs.attempt_number,
            url=url,
            error=_safe_exc_str(rs.outcome.exception()),
        ),
    ):
        with attempt:
            resp = client.get(
                _SCRAPEOPS_API,
                params={
                    "api_key": api_key,
                    "url": url,
                    "bypass": "datadome",
                    "country": "es",
                    "residential": "true",
                },
                timeout=120,
            )
            resp.raise_for_status()
            return resp.text


def _build_geocoder():
    """Nominatim geocoder rate-limited to one request per second (usage policy)."""
    nominatim = Nominatim(user_agent="housing-scout")
    return RateLimiter(nominatim.geocode, min_delay_seconds=1.1, swallow_exceptions=False)


def _geocode_listings(listings: list[Listing], country: str = GEOCODE_COUNTRY) -> None:
    """Populate lat/lon in place by geocoding each listing (Nominatim).

    Idealista list pages carry no coordinates, so we resolve them from the
    address text, falling back to the municipality when the full street
    address does not resolve. Results are cached per query within the call to
    avoid duplicate lookups; any failure leaves lat/lon as None.
    """
    geocode = _build_geocoder()
    cache: dict[str, tuple[float | None, float | None]] = {}

    def lookup(query: str) -> tuple[float | None, float | None]:
        if query not in cache:
            cache[query] = _geocode_one(geocode, query, country)
        return cache[query]

    for listing in listings:
        coords: tuple[float | None, float | None] = (None, None)
        for query in (listing.address, listing.municipality):
            if not query:
                continue
            coords = lookup(query)
            if coords[0] is not None:
                break
        listing.lat, listing.lon = coords


def _geocode_one(geocode, query: str, country: str = GEOCODE_COUNTRY) -> tuple[float | None, float | None]:
    try:
        location = geocode(f"{query}, {country}")
    except GeocoderServiceError as exc:
        log.warning("geocode.failed", query=query, error=str(exc))
        return None, None
    if location is None:
        log.info("geocode.miss", query=query)
        return None, None
    return location.latitude, location.longitude


def scrape(
    *,
    city: str,
    price_min: int,
    price_max: int,
    pages: int = 1,
    delay_ms: int = 3000,
    geocode: bool = True,
    slug: str | None = None,
    portal_base: str = _BASE,
    geocode_country: str = GEOCODE_COUNTRY,
) -> list[Listing]:
    """Scrape Idealista search results via the ScrapeOps Proxy Aggregator.

    Fetches ``pages`` result pages per city (each page yields ~25–30 listings).
    Unless ``geocode`` is False, each returned listing's coordinates are
    resolved from its address via Nominatim (Idealista list pages carry no
    coordinates). ``slug``/``portal_base``/``geocode_country`` normally come
    from the resolved provider bundle; the defaults are this provider's data.
    """
    api_key = os.environ.get("SCRAPEOPS_API_KEY")
    if not api_key:
        raise RuntimeError("SCRAPEOPS_API_KEY env var is not set")

    slug = slug or _CITY_SLUGS.get(city, city)
    target_url: str | None = (
        f"{portal_base}/venta-viviendas/{slug}/"
        f"con-precio-desde_{price_min},precio-hasta_{price_max},chalets/"
        f"?orden=publicado-desc"
    )

    listings: list[Listing] = []
    pages_fetched = 0

    with httpx.Client() as client:
        while target_url and pages_fetched < pages:
            html = _fetch_via_scrapeops(client, api_key, target_url)
            page_listings = _parse_page(html, city=city)

            # Recover from intermittent degraded DataDome renders: when the
            # first page parses suspiciously few cards yet advertises many more
            # results, re-fetch (a fresh ScrapeOps call gets a new proxy/render)
            # before accepting. A genuinely small result set (advertised total
            # within the threshold) is accepted as-is, so this only spends an
            # extra credit when a render actually looks broken.
            if pages_fetched == 0:
                refetches = 0
                total = _advertised_total(html)
                while (
                    len(page_listings) < _MIN_FIRST_PAGE_LISTINGS
                    and total is not None
                    and total > _MIN_FIRST_PAGE_LISTINGS
                    and refetches < _LOW_YIELD_REFETCHES
                ):
                    refetches += 1
                    log.warning(
                        "scrape.low_yield_refetch",
                        city=city,
                        parsed=len(page_listings),
                        advertised_total=total,
                        attempt=refetches,
                    )
                    if delay_ms:
                        time.sleep(delay_ms / 1000)
                    html = _fetch_via_scrapeops(client, api_key, target_url)
                    page_listings = _parse_page(html, city=city)
                    total = _advertised_total(html) or total

            if not page_listings:
                raise ScrapingBlockedError(
                    f"No listings parsed for {city!r} at {target_url!r} "
                    "(DataDome block or empty results page)."
                )

            listings.extend(page_listings)
            pages_fetched += 1

            target_url = _next_page_url(html) if pages_fetched < pages else None
            if target_url and delay_ms:
                time.sleep(delay_ms / 1000)

    if geocode:
        _geocode_listings(listings, geocode_country)
    return listings
