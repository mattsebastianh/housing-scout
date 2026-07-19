from scout.core.analyse.prompt_builder import compose_buyer_profile, build_system_prompt
from scout.core.profile import load_profile

_YAML = """
country: es
portal: idealista
search:
  cities: [{name: girona, lat: 41.98, lon: 2.82, radius_km: 30}]
  price_min_eur: 150000
  price_max_eur: 250000
  property_type: chalet_independiente
  preferred_plot_m2: 2000
buyer:
  household: "hogar de dos personas"
  investment_angle: true
  response_language: es
"""


def test_compose_buyer_profile_includes_fields(tmp_path):
    p = tmp_path / "profile.yaml"; p.write_text(_YAML)
    prof = load_profile(p)
    text = compose_buyer_profile(prof.buyer)
    assert "hogar de dos personas" in text
    assert "Inversión" in text


def test_build_system_prompt_fills_placeholders_no_hardcoded_city(tmp_path):
    p = tmp_path / "profile.yaml"; p.write_text(_YAML)
    prof = load_profile(p)
    out = build_system_prompt("property_analyst", prof)
    assert "girona" in out
    assert "{cities}" not in out and "{buyer_profile}" not in out
