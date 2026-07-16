from datetime import datetime

from scout.core.models import Listing, ScoredListing
from scout.core.report.markdown import render_report


def _scored(rank_price=180000, composite=8.4):
    l = Listing(
        portal="idealista", external_id="98765432", city="barcelona",
        url="https://www.idealista.com/inmueble/98765432/",
        price_eur=rank_price, size_m2=165, bedrooms=4, bathrooms=2,
        municipality="Sant Cugat del Vallès", province="Barcelona",
        address="Carrer Major 1", lat=41.47, lon=2.08,
        description="", days_on_market=42, cadastral_ref="1234567VK1213N0001AB",
        raw_json="{}", first_seen_at=datetime(2026, 5, 26, 7, 0),
    )
    return ScoredListing(
        listing=l,
        dim_scores={
            "price": 9.1, "location": 8.5, "commute": 7.8, "legal": 9.0,
            "regulatory": 8.0, "environmental": 7.5, "neighbourhood": 8.2,
            "infrastructure": None,
        },
        composite=composite,
        positives_md="- 12 % por debajo de la mediana zonal\n- Estación Renfe a 1.2 km",
        risks_md="- Zona SNCZI T500",
    )


def test_render_report_contains_card_and_summary():
    """Rendered report contains the listing card, composite score, date in Spanish, and run summary fields."""
    md = render_report(
        scored=[_scored()],
        run_id=42,
        generated_at=datetime(2026, 5, 26, 7, 14),
        report_date=datetime(2026, 5, 26),
        cities_label="Barcelona y Valencia",
        price_min=100_000, price_max=200_000, top_n=10,
        summary={
            "fetched_total": 87, "dedup_overrides": 12,
            "excluded_total": 28, "top_reason": "ocupas",
            "market_signal": "Neutral", "macro_alert": "Ninguna alerta relevante",
            "new_total": 47, "reported_total": 1,
        },
        zone_lookup=lambda l: {
            "zone_class": "URBANO",
            "market_context": "Sant Cugat +2.3 % vs. mediana 12 meses",
            "legal_status": "✅ Limpio",
        },
    )
    assert "26 de mayo de 2026" in md
    assert "Sant Cugat del Vallès" in md
    assert "8.4/10" in md
    assert "ocupas" in md
    assert "run #42" in md
