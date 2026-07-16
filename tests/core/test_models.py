from datetime import datetime, UTC

from scout.core.models import EnrichedListing, Listing, ScoredListing


def test_listing_from_dict_round_trip():
    """Listing dataclass stores all fields passed at construction."""
    raw = {
        "portal": "idealista",
        "external_id": "12345",
        "city": "barcelona",
        "url": "https://www.idealista.com/inmueble/12345/",
        "price_eur": 175000,
        "size_m2": 150,
        "bedrooms": 4,
        "bathrooms": 2,
        "municipality": "Sant Cugat del Vallès",
        "province": "Barcelona",
        "address": "Carrer Major 1",
        "lat": 41.47,
        "lon": 2.08,
        "description": "Chalet luminoso",
        "days_on_market": 30,
        "cadastral_ref": "1234567VK1213N0001AB",
    }
    listing = Listing(**raw, raw_json="{}", first_seen_at=datetime.now(UTC))
    assert listing.price_eur == 175000
    assert listing.portal == "idealista"


def test_enriched_listing_holds_dict_payloads():
    """EnrichedListing carries per-enricher dict payloads keyed by enricher name."""
    listing = Listing(
        portal="idealista",
        external_id="x",
        city="barcelona",
        url="http://x",
        price_eur=150000,
        size_m2=120,
        bedrooms=3,
        bathrooms=2,
        municipality="Terrassa",
        province="Barcelona",
        address=None,
        lat=41.5,
        lon=2.0,
        description="",
        days_on_market=0,
        cadastral_ref=None,
        raw_json="{}",
        first_seen_at=datetime.now(UTC),
    )
    enriched = EnrichedListing(listing=listing, enrichments={"catastro": {"use": "V"}})
    assert enriched.enrichments["catastro"]["use"] == "V"


def test_scored_listing_carries_dim_scores_and_composite():
    """ScoredListing stores dimension scores (including None) and the composite value."""
    listing = Listing(
        portal="fotocasa",
        external_id="y",
        city="valencia",
        url="http://y",
        price_eur=120000,
        size_m2=100,
        bedrooms=2,
        bathrooms=1,
        municipality="Paterna",
        province="Valencia",
        address=None,
        lat=39.5,
        lon=-0.45,
        description="",
        days_on_market=0,
        cadastral_ref=None,
        raw_json="{}",
        first_seen_at=datetime.now(UTC),
    )
    scored = ScoredListing(
        listing=listing,
        dim_scores={"price": 8.0, "location": None},
        composite=8.0,
        positives_md="- bullet",
        risks_md="- risk",
    )
    assert scored.dim_scores["location"] is None
    assert scored.composite == 8.0
