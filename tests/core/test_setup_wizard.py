from scout.core.setup_wizard import build_profile, write_profile, run_wizard
from scout.core.profile import load_profile


def test_build_profile_from_answers():
    prof = build_profile({
        "country": "es", "portal": "idealista",
        "cities": [{"name": "girona", "lat": 41.98, "lon": 2.82, "radius_km": 30}],
        "price_min_eur": 150000, "price_max_eur": 250000,
        "property_type": "chalet_independiente", "preferred_plot_m2": 2000,
        "household": "hogar de dos personas", "investment_angle": True,
        "response_language": "es",
    })
    assert prof.search.cities[0].name == "girona"
    assert prof.buyer.investment_angle is True


def test_write_then_load_roundtrip(tmp_path):
    prof = build_profile({
        "country": "es", "portal": "idealista",
        "cities": [{"name": "girona", "lat": 41.98, "lon": 2.82, "radius_km": 30}],
        "price_min_eur": 150000, "price_max_eur": 250000,
        "property_type": "chalet_independiente", "preferred_plot_m2": 2000,
    })
    p = tmp_path / "profile.yaml"
    write_profile(prof, p)
    assert load_profile(p).search.price_max_eur == 250000


def test_run_wizard_uses_injected_input(tmp_path):
    answers = iter([
        "es", "idealista",
        "girona", "41.98", "2.82", "30",   # one city
        "",                                  # blank name to stop the city loop
        "150000", "250000", "chalet_independiente", "2000",
        "hogar de dos personas", "primary_residence", "urban_commute",
        "si", "", "", "", "es", "",
    ])
    p = tmp_path / "profile.yaml"
    prof = run_wizard(input_fn=lambda _prompt="": next(answers), path=p)
    assert p.is_file()
    assert prof.search.cities[0].name == "girona"
