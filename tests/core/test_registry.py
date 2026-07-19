import pytest

from scout.core.registry import ProviderBundle, register, resolve


def test_provider_bundle_default_fields():
    """ProviderBundle default fields are sane: enrichers/regulatory default to empty dict, slug_for is identity."""
    def dummy_scrape():
        pass

    bundle = ProviderBundle(scrape=dummy_scrape)
    assert bundle.enrichers == {}
    assert bundle.regulatory == {}
    assert bundle.geocode_country == ""
    assert bundle.portal_base == ""
    assert bundle.slug_for("test_name") == "test_name"


def test_register_and_resolve_round_trip():
    """register() then resolve() returns the same bundle (round-trip)."""
    def scrape_func():
        return "scraped"

    def enricher_func():
        return "enriched"

    def slug_func(name: str) -> str:
        return f"slug_{name}"

    bundle = ProviderBundle(
        scrape=scrape_func,
        enrichers={"osm": enricher_func},
        regulatory={"housing_law": lambda: "law"},
        geocode_country="zz",
        portal_base="https://testportal.zz",
        slug_for=slug_func,
    )

    register("zz", "testportal", bundle)
    resolved = resolve("zz", "testportal")

    assert resolved.scrape is scrape_func
    assert resolved.enrichers["osm"] is enricher_func
    assert resolved.regulatory["housing_law"] is not None
    assert resolved.geocode_country == "zz"
    assert resolved.portal_base == "https://testportal.zz"
    assert resolved.slug_for("example") == "slug_example"


def test_resolve_unregistered_raises_key_error():
    """resolve() on unregistered (country, portal) raises KeyError with message naming the requested keys."""
    with pytest.raises(KeyError, match=r"country='zz_missing'.*portal='unknownportal'"):
        resolve("zz_missing", "unknownportal")


def test_resolve_error_message_contains_available():
    """KeyError message from resolve includes the 'Available:' hint."""
    with pytest.raises(KeyError, match=r"Available:"):
        resolve("zz_nothere", "noexist")


def test_es_bundle_resolves_with_provider_data():
    """Importing scout.providers registers the ES bundle with its slug map, portal base and geocode country."""
    import scout.providers  # noqa: F401  (registration side effect)

    bundle = resolve("es", "idealista")
    assert callable(bundle.scrape)
    assert bundle.geocode_country == "España"
    assert bundle.portal_base == "https://www.idealista.com"
    assert bundle.slug_for("barcelona") == "barcelona-provincia"
    assert bundle.slug_for("girona") == "girona-provincia"
    # unknown city names fall through to the name itself
    assert bundle.slug_for("somewhere-else") == "somewhere-else"


def test_scrape_listings_dispatches_through_bundle():
    """scrape_listings resolves the profile's bundle and passes slug/base/country;
    a per-city portal_slug overrides the bundle's slug map."""
    from types import SimpleNamespace

    from scout.core.profile import Profile
    from scout.core.scrape.base import scrape_listings

    seen: dict = {}

    def fake_scrape(**kwargs):
        seen.clear()
        seen.update(kwargs)
        return []

    register(
        "zz2",
        "portal2",
        ProviderBundle(
            scrape=fake_scrape,
            geocode_country="Testland",
            portal_base="https://portal2.zz",
            slug_for=lambda name: f"{name}-slug",
        ),
    )
    profile = Profile.model_validate({
        "country": "zz2",
        "portal": "portal2",
        "search": {
            "cities": [
                {"name": "alpha", "lat": 1.0, "lon": 2.0, "radius_km": 30},
                {"name": "beta", "lat": 3.0, "lon": 4.0, "radius_km": 30,
                 "portal_slug": "beta-custom"},
            ],
            "price_min_eur": 100_000,
            "price_max_eur": 200_000,
            "property_type": "house",
        },
    })
    cfg = SimpleNamespace(scrape=SimpleNamespace(
        provider="scrapeops", brightdata_collector_id=None, pages=2, delay_ms=10,
    ))

    scrape_listings(cfg, profile, "alpha")
    assert seen["city"] == "alpha"
    assert seen["slug"] == "alpha-slug"  # bundle's slug_for
    assert seen["portal_base"] == "https://portal2.zz"
    assert seen["geocode_country"] == "Testland"
    assert seen["provider"] == "scrapeops"
    assert seen["pages"] == 2

    scrape_listings(cfg, profile, "beta")
    assert seen["slug"] == "beta-custom"  # per-city portal_slug override wins
