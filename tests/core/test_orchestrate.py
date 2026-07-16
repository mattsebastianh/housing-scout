import shutil
from pathlib import Path
from datetime import datetime, UTC

from scout.core.config import load_config
from scout.core.db import connect, migrate
from scout.core.models import Listing
from scout.core.profile import load_profile


def _make_listing(external_id: str, city: str, lat: float, lon: float) -> Listing:
    return Listing(
        portal="idealista",
        external_id=external_id,
        city=city,
        url=f"http://idealista.com/{external_id}",
        price_eur=175000,
        size_m2=160,
        bedrooms=4,
        bathrooms=2,
        municipality="Sant Cugat del Vallès",
        province="Barcelona",
        address="Carrer Major 1",
        lat=lat,
        lon=lon,
        description="Chalet luminoso",
        days_on_market=10,
        cadastral_ref="C1",
        raw_json="{}",
        first_seen_at=datetime.now(UTC),
    )


def test_orchestrate_end_to_end_with_fake_scraper(tmp_path, monkeypatch):
    """Full run_once() with stubbed scraper and enricher writes one report per city and exits 0."""
    project_root = Path(__file__).resolve().parents[2]
    cfg_path = tmp_path / "config.yaml"
    shutil.copy(project_root / "config.yaml", cfg_path)
    profile_yaml = """
country: es
portal: idealista
search:
  cities:
    - {name: barcelona, lat: 41.3874, lon: 2.1686, radius_km: 30}
    - {name: valencia, lat: 39.4699, lon: -0.3763, radius_km: 30}
    - {name: girona, lat: 41.9794, lon: 2.8214, radius_km: 30}
  price_min_eur: 150000
  price_max_eur: 250000
  property_type: chalet_independiente
  preferred_plot_m2: 2000
buyer:
  household: "hogar de dos personas"
"""
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(profile_yaml)
    profile = load_profile(profile_path)
    # The committed config.yaml deliberately omits the collector id (it is
    # deploy-specific); supply it the way production does — via the env var.
    monkeypatch.setenv("BRIGHTDATA_COLLECTOR_ID", "c_test")

    db = connect(tmp_path / "t.db")
    migrate(db)

    def fake_scrape(*, city, price_min, price_max, pages, delay_ms=3000, **kwargs):
        if city == "barcelona":
            return [_make_listing("I-1", "barcelona", 41.47, 2.08)]
        return []

    from scout.providers.es.scrape import brightdata as bda
    from scout.providers.es.scrape import idealista as ide
    from scout.core import orchestrate as orch

    # stub both providers so the test passes regardless of scrape.provider
    monkeypatch.setattr(ide, "scrape", fake_scrape)
    monkeypatch.setattr(bda, "scrape", fake_scrape)
    # detail-page fetch is exercised in its own unit tests; stub it here so the
    # orchestrate test makes no network calls regardless of environment.
    monkeypatch.setattr(ide, "fetch_listing_details", lambda *a, **k: {})

    async def fake_enrich(item, client):
        from scout.core.enrich.base import EnrichmentResult
        return {
            "catastro": EnrichmentResult(success=True, payload={"use_code": "V", "year_built": 1998, "built_m2": 160}),
            "osm": EnrichmentResult(success=True, payload={
                "amenities_5km": {"supermarket": 1, "pharmacy": 1, "school": 1, "hospital": 1},
                "nearest_station_km": 1.2,
            }),
            "osrm": EnrichmentResult(success=True, payload={"drive_min": 22}),
            "ine": EnrichmentResult(success=True, payload={"price_psqm": 1500, "quarter": "2026Q1"}),
            "flood": EnrichmentResult(success=True, payload={"return_period": "T500"}),
        }

    monkeypatch.setattr(orch, "_enrich_one", fake_enrich)

    cfg = load_config(cfg_path)
    paths = {
        "db": tmp_path / "t.db",
        "log": tmp_path / "x.log",
        "reports": tmp_path / "reports",
    }
    rc = orch.run_once(cfg, profile, db, paths)
    assert rc == 0
    # one independent report per configured city
    report_files = sorted((tmp_path / "reports").glob("*.md"))
    assert len(report_files) == len(profile.search.cities)
    names = {f.name for f in report_files}
    for city in profile.search.cities:
        assert any(city.name in n for n in names)
    bcn = next(f for f in report_files if "barcelona" in f.name)
    text = bcn.read_text()
    assert "Sant Cugat del Vallès" in text
    assert text.count("## 1.") == 1
