from datetime import datetime, UTC

from scout.core.filter.dedup import dedup_key, normalise_address
from scout.core.models import Listing


def _listing(**overrides) -> Listing:
    defaults = dict(
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
        address="Carrer Major 1",
        lat=41.5,
        lon=2.0,
        description="",
        days_on_market=0,
        cadastral_ref=None,
        raw_json="{}",
        first_seen_at=datetime.now(UTC),
    )
    defaults.update(overrides)
    return Listing(**defaults)


def test_cadastral_ref_wins():
    """Two listings sharing a cadastral ref produce the same dedup key regardless of other fields."""
    a = _listing(cadastral_ref="1234567VK1213N0001AB")
    b = _listing(cadastral_ref="1234567VK1213N0001AB", municipality="Other")
    assert dedup_key(a) == dedup_key(b)


def test_address_normalised():
    """Punctuation, case, and ordinal markers are stripped before comparing addresses."""
    a = _listing(address="Carrer Major, 1, 2º A")
    b = _listing(address="carrer major 1 2 a")
    assert dedup_key(a) == dedup_key(b)


def test_address_different_municipalities_differ():
    """Same street address in different municipalities produces different dedup keys."""
    a = _listing(address="Carrer Major 1", municipality="Terrassa")
    b = _listing(address="Carrer Major 1", municipality="Sabadell")
    assert dedup_key(a) != dedup_key(b)


def test_approx_fallback_buckets_match_within_5pct_price_and_m2():
    """Listings within 5 % of each other on price and size land in the same approximate bucket."""
    a = _listing(address=None, cadastral_ref=None, price_eur=150000, size_m2=120)
    b = _listing(
        address=None, cadastral_ref=None, price_eur=151000, size_m2=121
    )  # within both buckets
    assert dedup_key(a) == dedup_key(b)


def test_approx_fallback_buckets_differ_for_clearly_different_listings():
    """Listings far apart on price and size land in different approximate buckets."""
    a = _listing(address=None, cadastral_ref=None, price_eur=120000, size_m2=100)
    b = _listing(address=None, cadastral_ref=None, price_eur=190000, size_m2=200)
    assert dedup_key(a) != dedup_key(b)


def test_normalise_address_strips_punctuation_and_lowercases():
    """normalise_address lowercases, strips punctuation, and appends the municipality."""
    assert normalise_address("Carrer Major, 1, 2º A", "Terrassa") == "carrer major 1 2 a|terrassa"
