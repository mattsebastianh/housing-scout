import sqlite3
from datetime import datetime, UTC

from scout.core.filter.dedup import dedup_key
from scout.core.filter.hard_excl import Exclusion
from scout.core.models import Listing


def insert_or_update_raw(conn: sqlite3.Connection, listing: Listing) -> int:
    now = datetime.now(UTC)
    # RETURNING id works for both INSERT and ON CONFLICT DO UPDATE (SQLite 3.35+),
    # avoiding the stale lastrowid bug where cursor.lastrowid keeps the value from
    # the previous INSERT when the DO UPDATE branch fires.
    row = conn.execute(
        """
        INSERT INTO raw_listings (
            portal, external_id, city, url, price_eur, size_m2,
            bedrooms, bathrooms, municipality, province, address,
            lat, lon, description, days_on_market, cadastral_ref,
            raw_json, first_seen_at, last_seen_at, plot_m2
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(portal, external_id) DO UPDATE SET
            price_eur = excluded.price_eur,
            description = excluded.description,
            days_on_market = excluded.days_on_market,
            raw_json = excluded.raw_json,
            last_seen_at = excluded.last_seen_at,
            plot_m2 = COALESCE(excluded.plot_m2, raw_listings.plot_m2)
        RETURNING id
        """,
        (
            listing.portal, listing.external_id, listing.city, listing.url,
            listing.price_eur, listing.size_m2, listing.bedrooms, listing.bathrooms,
            listing.municipality, listing.province, listing.address,
            listing.lat, listing.lon, listing.description, listing.days_on_market,
            listing.cadastral_ref, listing.raw_json,
            listing.first_seen_at, now, listing.plot_m2,
        ),
    ).fetchone()
    return int(row[0])


def upsert_property_for_listing(
    conn: sqlite3.Connection, listing: Listing, raw_id: int
) -> tuple[int, bool]:
    """Returns (property_id, override_occurred)."""
    key = dedup_key(listing)
    now = datetime.now(UTC)
    override = False

    row = conn.execute(
        "SELECT id, primary_raw_id FROM properties WHERE dedup_key=?", (key,)
    ).fetchone()

    if row is None:
        cur = conn.execute(
            "INSERT INTO properties (dedup_key, primary_raw_id, first_seen_at) VALUES (?, ?, ?)",
            (key, raw_id, now),
        )
        property_id = int(cur.lastrowid)
    else:
        property_id = int(row[0])
        current_primary = int(row[1])
        current_portal = conn.execute(
            "SELECT portal FROM raw_listings WHERE id=?", (current_primary,)
        ).fetchone()[0]
        if listing.portal == "idealista" and current_portal == "fotocasa":
            conn.execute(
                "UPDATE properties SET primary_raw_id=? WHERE id=?",
                (raw_id, property_id),
            )
            override = True

    conn.execute(
        "INSERT OR IGNORE INTO property_raw_link (property_id, raw_id) VALUES (?, ?)",
        (property_id, raw_id),
    )
    return property_id, override


def record_exclusion(conn: sqlite3.Connection, raw_id: int, exclusion: Exclusion) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO exclusions (raw_id, reason_code, reason_detail, excluded_at)
        VALUES (?, ?, ?, ?)
        """,
        (raw_id, str(exclusion.code), exclusion.detail, datetime.now(UTC)),
    )
