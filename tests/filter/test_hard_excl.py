from datetime import datetime, UTC

from scout.core.filter.hard_excl import ExclusionReason, check_listing
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
        address="Carrer X 1",
        lat=41.5,
        lon=2.0,
        description="Chalet luminoso con jardín",
        days_on_market=20,
        cadastral_ref=None,
        raw_json="{}",
        first_seen_at=datetime.now(UTC),
    )
    defaults.update(overrides)
    return Listing(**defaults)


def test_listing_in_price_range_passes():
    """A listing within the price range returns None (no exclusion)."""
    assert check_listing(_listing(), price_min=100_000, price_max=200_000) is None


def test_below_price_range_excluded():
    """Price below the minimum triggers OUT_OF_PRICE_RANGE."""
    r = check_listing(_listing(price_eur=80_000), price_min=100_000, price_max=200_000)
    assert r is not None
    assert r.code == ExclusionReason.OUT_OF_PRICE_RANGE


def test_above_price_range_excluded():
    """Price above the maximum triggers OUT_OF_PRICE_RANGE."""
    r = check_listing(_listing(price_eur=250_000), price_min=100_000, price_max=200_000)
    assert r is not None
    assert r.code == ExclusionReason.OUT_OF_PRICE_RANGE


def test_ocupas_excluded():
    """Description matching ocupas/situación especial patterns triggers OCUPAS."""
    r = check_listing(
        _listing(description="Vendido CON inquilino sin contrato, situación especial"),
        price_min=100_000,
        price_max=200_000,
    )
    assert r is not None
    assert r.code == ExclusionReason.OCUPAS


def test_nuda_propiedad_excluded():
    """Description mentioning nuda propiedad triggers NUDA_PROPIEDAD."""
    r = check_listing(
        _listing(description="Se vende la nuda propiedad de un chalet"),
        price_min=100_000,
        price_max=200_000,
    )
    assert r is not None
    assert r.code == ExclusionReason.NUDA_PROPIEDAD


def test_subasta_excluded():
    """Description mentioning subasta triggers LITIGIOUS."""
    r = check_listing(
        _listing(description="Chalet en subasta judicial, herencia"),
        price_min=100_000,
        price_max=200_000,
    )
    assert r is not None
    assert r.code == ExclusionReason.LITIGIOUS


def test_tanteo_excluded():
    """Description mentioning derecho de tanteo triggers RESTRICTED_TITLE."""
    r = check_listing(
        _listing(description="Sujeto a derecho de tanteo del Ayuntamiento"),
        price_min=100_000,
        price_max=200_000,
    )
    assert r is not None
    assert r.code == ExclusionReason.RESTRICTED_TITLE
