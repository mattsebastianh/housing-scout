from datetime import datetime, UTC

from scout.core.models import EnrichedListing, Listing
from scout.core.score import dimensions as d


def _enriched(price=180000, m2=160, days=10, enr=None):
    l = Listing(
        portal="idealista", external_id="x", city="barcelona", url="http://x",
        price_eur=price, size_m2=m2, bedrooms=4, bathrooms=2,
        municipality="Sant Cugat del Vallès", province="Barcelona",
        address="x", lat=41.5, lon=2.0, description="",
        days_on_market=days, cadastral_ref=None,
        raw_json="{}", first_seen_at=datetime.now(UTC),
    )
    return EnrichedListing(listing=l, enrichments=enr or {})


def test_price_dimension_10_when_far_below_median():
    """Price far below the zonal median scores 10."""
    e = _enriched(price=120000, m2=160)  # ~750 €/m² vs median 3850 → 80% below
    score = d.score_price(e, {"price_psqm": 3850})
    assert score == 10


def test_price_dimension_5_when_at_median():
    """Price at the zonal median scores approximately 5."""
    e = _enriched(price=160 * 3850, m2=160)
    score = d.score_price(e, {"price_psqm": 3850})
    assert 4.5 <= score <= 5.5


def test_price_dimension_negotiation_bonus_for_old_listings():
    """Listings on market longer than the threshold receive a bonus over fresher listings at the same price."""
    e_new = _enriched(price=160 * 3850, m2=160, days=5)
    e_old = _enriched(price=160 * 3850, m2=160, days=120)
    assert d.score_price(e_old, {"price_psqm": 3850}) > d.score_price(e_new, {"price_psqm": 3850})


def test_price_dimension_none_when_no_zone_data():
    """Returns None when no INE zonal median data is available."""
    e = _enriched(price=180000, m2=160)
    assert d.score_price(e, None) is None


def test_location_capital_with_all_amenities():
    """Large city with saturated family-relevant amenity counts scores 10."""
    # Large city + saturated amenities in each family-relevant category → score 10
    e = _enriched(enr={
        "osm": {"amenities_5km": {
            "supermarket": 5, "pharmacy": 3,
            "school": 5, "hospital": 2,
            "clinic": 3, "park": 6,
            "healthcare_total": 8,
        }},
    })
    s = d.score_location(e, municipality_population=1_700_000)
    assert s == 10


def test_commute_with_short_drive_and_close_station():
    """Short drive time and a nearby transit station produce a high commute score."""
    e = _enriched(enr={
        "osrm": {"drive_min": 18},
        "osm": {"nearest_station_km": 1.0},
    })
    s = d.score_commute(e, motorway_km=4.0)
    assert 8.5 <= s <= 10


def test_legal_penalises_conflict_and_no_urbanizable():
    """Non-residential use code combined with no-urbanizable class scores ≤ 5."""
    e = _enriched(enr={
        "catastro": {"use_code": "R", "year_built": 1998},
    })
    s = d.score_legal(e, urbanistic_class="no urbanizable")
    assert s <= 5


def test_environmental_renormalises_over_available():
    """With only flood and wildfire data, score renormalises over the two available sub-scores."""
    e = _enriched(enr={
        "flood": {"return_period": "T100"},
        "wildfire": {"hazard_class": 1},
    })
    s = d.score_environmental(e)
    assert 6 <= s <= 8


def test_environmental_none_when_all_missing():
    """Returns None when no environmental enrichment is present."""
    assert d.score_environmental(_enriched()) is None


def test_environmental_combines_flood_wildfire_noise_air():
    """Four environmental sub-scores (flood, wildfire, noise, air) average with equal weights."""
    e = _enriched(enr={
        "flood": {"return_period": "none"},      # 10
        "wildfire": {"hazard_class": 3},          # 10-(3-1)*2.5 = 5
        "noise": {"lden_db": 60},                 # <65 → 7
        "air": {"no2_avg": 25},                   # 10-(25-10)/3 = 5
    })
    s = d.score_environmental(e)
    assert abs(s - (10 + 5 + 7 + 5) / 4) < 0.01
