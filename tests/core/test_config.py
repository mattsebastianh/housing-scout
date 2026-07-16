from pathlib import Path

from scout.core.config import Config, load_config


def test_load_config_returns_typed_object(tmp_path):
    """Parses a valid YAML file into a typed Config with correct scrape, report, and weight fields."""
    yaml_text = """
scrape:
  pages: 1
report:
  language: es
  top_n: 10
  output_dir: data/reports
  timezone: Europe/Madrid
  app_name: Housing Scout
scoring:
  weights:
    price: 0.20
    location: 0.15
    commute: 0.15
    legal: 0.15
    regulatory: 0.10
    environmental: 0.10
    neighbourhood: 0.10
    infrastructure: 0.05
run:
  hour: 7
  minute: 0
"""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml_text)
    cfg = load_config(cfg_file)
    assert isinstance(cfg, Config)
    assert cfg.report.app_name == "Housing Scout"
    assert abs(sum(cfg.scoring.weights.model_dump().values()) - 1.0) < 1e-9


def test_report_app_name_defaults(tmp_path):
    """report.app_name defaults to 'Housing Scout' when omitted."""
    yaml_text = """
scrape:
  pages: 1
report:
  language: es
  top_n: 10
  output_dir: data/reports
  timezone: Europe/Madrid
scoring:
  weights:
    price: 0.20
    location: 0.15
    commute: 0.15
    legal: 0.15
    regulatory: 0.10
    environmental: 0.10
    neighbourhood: 0.10
    infrastructure: 0.05
run:
  hour: 7
  minute: 0
"""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml_text)
    cfg = load_config(cfg_file)
    assert cfg.report.app_name == "Housing Scout"


def test_weights_must_sum_to_one(tmp_path):
    """Raises ValueError when scoring weights do not sum to 1.0."""
    import pytest

    yaml_text = """
scrape:
  pages: 1
report:
  language: es
  top_n: 10
  output_dir: data/reports
  timezone: Europe/Madrid
scoring:
  weights:
    price: 0.5
    location: 0.1
    commute: 0.1
    legal: 0.1
    regulatory: 0.05
    environmental: 0.05
    neighbourhood: 0.05
    infrastructure: 0.01
run:
  hour: 7
  minute: 0
"""
    cfg_file = tmp_path / "bad.yaml"
    cfg_file.write_text(yaml_text)
    with pytest.raises(ValueError, match="weights must sum to 1.0"):
        load_config(cfg_file)


def test_scrape_provider_defaults_to_scrapeops():
    """Omitting scrape.provider keeps the ScrapeOps path (back-compat)."""
    from scout.core.config import Scrape

    assert Scrape(pages=1).provider == "scrapeops"


def test_brightdata_provider_requires_collector_id():
    """provider=brightdata without a collector id fails validation."""
    import pytest
    from scout.core.config import Scrape

    with pytest.raises(ValueError, match="brightdata_collector_id"):
        Scrape(pages=1, provider="brightdata")
    ok = Scrape(pages=1, provider="brightdata", brightdata_collector_id="c_abc")
    assert ok.brightdata_collector_id == "c_abc"


def _yaml_with_scrape(scrape_block: str) -> str:
    return f"""
scrape:
{scrape_block}
report:
  language: es
  top_n: 10
  output_dir: data/reports
  timezone: Europe/Madrid
scoring:
  weights:
    price: 0.20
    location: 0.15
    commute: 0.15
    legal: 0.15
    regulatory: 0.10
    environmental: 0.10
    neighbourhood: 0.10
    infrastructure: 0.05
run:
  hour: 7
  minute: 0
"""


def test_env_collector_id_satisfies_brightdata_requirement(tmp_path, monkeypatch):
    """BRIGHTDATA_COLLECTOR_ID env var fills the collector id when config.yaml omits it."""
    monkeypatch.setenv("BRIGHTDATA_COLLECTOR_ID", "c_from_env")
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(_yaml_with_scrape("  provider: brightdata\n  pages: 1"))
    cfg = load_config(cfg_file)
    assert cfg.scrape.brightdata_collector_id == "c_from_env"


def test_env_collector_id_overrides_yaml_value(tmp_path, monkeypatch):
    """The env var takes precedence over a collector id set in config.yaml."""
    monkeypatch.setenv("BRIGHTDATA_COLLECTOR_ID", "c_from_env")
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        _yaml_with_scrape(
            "  provider: brightdata\n  brightdata_collector_id: c_from_yaml\n  pages: 1"
        )
    )
    cfg = load_config(cfg_file)
    assert cfg.scrape.brightdata_collector_id == "c_from_env"


def test_missing_collector_id_still_fails_without_env(tmp_path, monkeypatch):
    """Without the env var, provider=brightdata still demands the id in config.yaml."""
    import pytest

    monkeypatch.delenv("BRIGHTDATA_COLLECTOR_ID", raising=False)
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(_yaml_with_scrape("  provider: brightdata\n  pages: 1"))
    with pytest.raises(ValueError, match="brightdata_collector_id"):
        load_config(cfg_file)
