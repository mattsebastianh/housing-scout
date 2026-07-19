import pytest
from scout.core.profile import load_profile, profile_exists, Profile

_YAML = """
country: es
portal: idealista
search:
  cities:
    - {name: barcelona, lat: 41.3874, lon: 2.1686, radius_km: 30}
  price_min_eur: 150000
  price_max_eur: 250000
  property_type: chalet_independiente
  preferred_plot_m2: 2000
buyer:
  household: "hogar de dos personas"
  top_priorities: [urban_commute, plot_usability]
  investment_angle: true
  response_language: es
"""


def test_load_profile_parses(tmp_path):
    p = tmp_path / "profile.yaml"
    p.write_text(_YAML)
    prof = load_profile(p)
    assert isinstance(prof, Profile)
    assert prof.country == "es" and prof.portal == "idealista"
    assert prof.search.cities[0].name == "barcelona"
    assert prof.search.price_max_eur == 250000
    assert prof.buyer.investment_angle is True
    assert prof.buyer.top_priorities == ["urban_commute", "plot_usability"]


def test_price_range_validated(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text(_YAML.replace("price_min_eur: 150000", "price_min_eur: 300000"))
    with pytest.raises(ValueError, match="price_min_eur must be < price_max_eur"):
        load_profile(p)


def test_profile_exists(tmp_path):
    p = tmp_path / "profile.yaml"
    assert profile_exists(p) is False
    p.write_text(_YAML)
    assert profile_exists(p) is True
