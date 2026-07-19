MIGRATIONS: list[str] = [
    # v1: initial schema
    """
    CREATE TABLE schema_version (version INTEGER PRIMARY KEY);

    CREATE TABLE raw_listings (
        id              INTEGER PRIMARY KEY,
        portal          TEXT NOT NULL CHECK(portal IN ('idealista', 'fotocasa')),
        external_id     TEXT NOT NULL,
        city            TEXT NOT NULL,
        url             TEXT NOT NULL,
        price_eur       INTEGER,
        size_m2         INTEGER,
        bedrooms        INTEGER,
        bathrooms       INTEGER,
        municipality    TEXT,
        province        TEXT,
        address         TEXT,
        lat             REAL,
        lon             REAL,
        description     TEXT,
        days_on_market  INTEGER,
        cadastral_ref   TEXT,
        raw_json        TEXT NOT NULL,
        first_seen_at   TIMESTAMP NOT NULL,
        last_seen_at    TIMESTAMP NOT NULL,
        UNIQUE(portal, external_id)
    );

    CREATE TABLE properties (
        id              INTEGER PRIMARY KEY,
        dedup_key       TEXT NOT NULL UNIQUE,
        primary_raw_id  INTEGER NOT NULL REFERENCES raw_listings(id),
        first_seen_at   TIMESTAMP NOT NULL,
        reported_at     TIMESTAMP
    );

    CREATE TABLE property_raw_link (
        property_id     INTEGER NOT NULL REFERENCES properties(id),
        raw_id          INTEGER NOT NULL REFERENCES raw_listings(id),
        PRIMARY KEY (property_id, raw_id)
    );

    CREATE TABLE exclusions (
        raw_id          INTEGER PRIMARY KEY REFERENCES raw_listings(id),
        reason_code     TEXT NOT NULL,
        reason_detail   TEXT,
        excluded_at     TIMESTAMP NOT NULL
    );

    CREATE TABLE enrichments (
        property_id     INTEGER NOT NULL REFERENCES properties(id),
        source          TEXT NOT NULL,
        fetched_at      TIMESTAMP NOT NULL,
        success         INTEGER NOT NULL CHECK(success IN (0, 1)),
        payload_json    TEXT,
        PRIMARY KEY (property_id, source)
    );

    CREATE TABLE runs (
        id              INTEGER PRIMARY KEY,
        started_at      TIMESTAMP NOT NULL,
        finished_at     TIMESTAMP,
        status          TEXT NOT NULL CHECK(status IN ('running', 'ok', 'failed')),
        fetched_total   INTEGER,
        dedup_overrides INTEGER,
        excluded_total  INTEGER,
        new_total       INTEGER,
        reported_total  INTEGER,
        report_path     TEXT,
        error_message   TEXT
    );

    CREATE TABLE scores (
        run_id          INTEGER NOT NULL REFERENCES runs(id),
        property_id     INTEGER NOT NULL REFERENCES properties(id),
        composite       REAL NOT NULL,
        dim_price       REAL,
        dim_location    REAL,
        dim_commute     REAL,
        dim_legal       REAL,
        dim_regulatory  REAL,
        dim_environmental REAL,
        dim_neighbourhood REAL,
        dim_infrastructure REAL,
        positives_md    TEXT,
        risks_md        TEXT,
        PRIMARY KEY (run_id, property_id)
    );

    INSERT INTO schema_version(version) VALUES (1);
    """,
    # v2: plot/land size mined from listing descriptions (preference scoring)
    """
    ALTER TABLE raw_listings ADD COLUMN plot_m2 INTEGER;

    INSERT INTO schema_version(version) VALUES (2);
    """,
]
