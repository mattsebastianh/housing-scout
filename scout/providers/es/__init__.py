"""Spain / Idealista reference provider. Imported for its registration side effect."""
from scout.core.registry import ProviderBundle, register
from scout.providers.es.scrape import brightdata, idealista
from scout.providers.es.scrape.idealista import _BASE, _CITY_SLUGS, GEOCODE_COUNTRY


def _scrape(*, provider: str, collector_id: str | None = None, **kwargs):
    """Dispatch to the configured transport: Bright Data collector or the
    ScrapeOps proxy fallback. Module-attribute lookup happens at call time so
    tests can monkeypatch ``brightdata.scrape`` / ``idealista.scrape``."""
    if provider == "brightdata":
        return brightdata.scrape(**kwargs, collector_id=collector_id)
    return idealista.scrape(**kwargs)


register(
    "es",
    "idealista",
    ProviderBundle(
        scrape=_scrape,
        geocode_country=GEOCODE_COUNTRY,
        portal_base=_BASE,
        slug_for=lambda name: _CITY_SLUGS.get(name, name),
    ),
)
