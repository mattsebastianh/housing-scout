import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

_PROFILE_YAML = """
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


def _profile_path(tmp_path) -> Path:
    p = tmp_path / "profile.yaml"
    p.write_text(_PROFILE_YAML)
    return p


def test_run_daily_check_exits_zero(tmp_path):
    """--check flag initialises the DB and exits 0 without scraping."""
    env = {
        **os.environ,
        "SCOUT_DB_PATH": str(tmp_path / "test.db"),
        "SCOUT_LOG_DIR": str(tmp_path / "logs"),
    }
    result = subprocess.run(
        [
            sys.executable, str(PROJECT_ROOT / "run_daily.py"),
            "--profile", str(_profile_path(tmp_path)),
            "--check",
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=PROJECT_ROOT,
    )
    assert result.returncode == 0, result.stderr
    assert "barcelona" in result.stdout
    assert "valencia" in result.stdout
    assert (tmp_path / "test.db").exists()


def _run(tmp_path, *extra):
    env = {
        **os.environ,
        "SCOUT_DB_PATH": str(tmp_path / "test.db"),
        "SCOUT_LOG_DIR": str(tmp_path / "logs"),
    }
    return subprocess.run(
        [
            sys.executable, str(PROJECT_ROOT / "run_daily.py"),
            "--profile", str(_profile_path(tmp_path)),
            "--check", *extra,
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=PROJECT_ROOT,
    )


def test_run_daily_city_flag_filters_cities(tmp_path):
    """--city restricts the run to the named cities only."""
    result = _run(tmp_path, "--city", "valencia")
    assert result.returncode == 0, result.stderr
    assert "valencia" in result.stdout
    assert "barcelona" not in result.stdout


def test_run_daily_city_flag_repeatable(tmp_path):
    """--city can be given more than once to select a subset."""
    result = _run(tmp_path, "--city", "valencia", "--city", "girona")
    assert result.returncode == 0, result.stderr
    assert "valencia" in result.stdout
    assert "girona" in result.stdout
    assert "barcelona" not in result.stdout


def test_run_daily_unknown_city_exits_nonzero(tmp_path):
    """An unconfigured city name aborts with a clear error."""
    result = _run(tmp_path, "--city", "madrid")
    assert result.returncode == 2
    assert "madrid" in result.stderr
