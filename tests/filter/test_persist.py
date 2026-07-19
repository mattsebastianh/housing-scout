import json
from datetime import datetime, UTC

from scout.core.db import connect, migrate
from scout.core.filter.hard_excl import Exclusion, ExclusionReason
from scout.core.filter.persist import (
    insert_or_update_raw,
    record_exclusion,
    upsert_property_for_listing,
)
from scout.core.models import Listing


def _conn(tmp_path):
    c = connect(tmp_path / "p.db")
    migrate(c)
    return c


def _l(**ov):
    base = dict(
        portal="idealista", external_id="x", city="barcelona",
        url="http://x", price_eur=150000, size_m2=120, bedrooms=3,
        bathrooms=2, municipality="Terrassa", province="Barcelona",
        address="Carrer X 1", lat=41.5, lon=2.0, description="",
        days_on_market=0, cadastral_ref=None,
        raw_json=json.dumps({"k": "v"}), first_seen_at=datetime.now(UTC),
    )
    base.update(ov)
    return Listing(**base)


def test_insert_raw_returns_id_and_is_idempotent(tmp_path):
    """Inserting the same listing twice returns the same raw ID and stores only one row."""
    conn = _conn(tmp_path)
    rid1 = insert_or_update_raw(conn, _l())
    rid2 = insert_or_update_raw(conn, _l())
    assert rid1 == rid2
    rows = conn.execute("SELECT COUNT(*) FROM raw_listings").fetchone()[0]
    assert rows == 1


def test_idealista_overrides_fotocasa_as_primary(tmp_path):
    """When Idealista and Fotocasa list the same property, Idealista becomes the primary raw source."""
    conn = _conn(tmp_path)
    f_id = insert_or_update_raw(conn, _l(portal="fotocasa", external_id="f1", cadastral_ref="C1"))
    pid_f, override_f = upsert_property_for_listing(conn, _l(portal="fotocasa", external_id="f1", cadastral_ref="C1"), f_id)
    assert override_f is False

    i_id = insert_or_update_raw(conn, _l(portal="idealista", external_id="i1", cadastral_ref="C1"))
    pid_i, override_i = upsert_property_for_listing(conn, _l(portal="idealista", external_id="i1", cadastral_ref="C1"), i_id)
    assert pid_i == pid_f
    assert override_i is True

    primary = conn.execute("SELECT primary_raw_id FROM properties WHERE id=?", (pid_i,)).fetchone()[0]
    assert primary == i_id


def test_record_exclusion(tmp_path):
    """Records an exclusion row linked to the raw listing with the correct reason code."""
    conn = _conn(tmp_path)
    rid = insert_or_update_raw(conn, _l(description="con inquilino sin contrato"))
    record_exclusion(conn, rid, Exclusion(ExclusionReason.OCUPAS, "test"))
    row = conn.execute("SELECT reason_code FROM exclusions WHERE raw_id=?", (rid,)).fetchone()
    assert row[0] == "OCUPAS"
