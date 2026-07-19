"""Config-driven scrape dispatch through the registered provider bundle."""

from scout.core.registry import resolve


def scrape_listings(cfg, profile, city_name: str):
    """Scrape one city via the provider bundle registered for the profile's
    ``(country, portal)`` pair.

    Bundle contract: ``bundle.scrape`` returns ``list[Listing]`` or raises the
    provider's ``ScrapingBlockedError`` when nothing usable comes back. The
    portal slug comes from the city's ``portal_slug`` override when set,
    otherwise from the bundle's ``slug_for`` mapping.
    """
    import scout.providers  # noqa: F401  (registers provider bundles on import)

    bundle = resolve(profile.country, profile.portal)
    city = next((c for c in profile.search.cities if c.name == city_name), None)
    slug = (city.portal_slug if city is not None else None) or bundle.slug_for(city_name)
    return bundle.scrape(
        provider=cfg.scrape.provider,
        collector_id=cfg.scrape.brightdata_collector_id,
        city=city_name,
        slug=slug,
        portal_base=bundle.portal_base,
        geocode_country=bundle.geocode_country,
        price_min=profile.search.price_min_eur,
        price_max=profile.search.price_max_eur,
        pages=cfg.scrape.pages,
        delay_ms=cfg.scrape.delay_ms,
    )
