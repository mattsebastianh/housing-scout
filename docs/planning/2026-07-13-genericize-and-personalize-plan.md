# Genericize & Personalize — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the single-owner `chalet-spain` tool into a reusable `property-scout` template: personal data in a gitignored `profile.yaml` (via a setup wizard), externalized generic agent instructions, a portal/country-agnostic `core/` + `providers/es/` architecture, and clean git history — preserving output format and scoring behavior.

**Architecture:** Python package renamed `chalet` → `scout`, split into `scout/core/` (agnostic pipeline) and `scout/providers/es/` (Spain/Idealista reference implementation) resolved through a small provider registry keyed by `profile.country`/`profile.portal`. Personal config (`profile.yaml`) is separate from mechanical config (`config.yaml`). AI system prompts live in editable `agent_instructions/*.md` templates filled from the profile.

**Tech Stack:** Python 3.13, pydantic v2, PyYAML, httpx, structlog, pytest + pytest-asyncio + respx, git-filter-repo.

## Global Constraints

- Python ≥ 3.11 (dev on 3.13); run tests with `.venv/bin/python -m pytest` (the venv console-scripts have a stale shebang).
- Package name: `scout`. Project/repo name: `property-scout`. No `chalet` identifiers remain in code after Task 3.
- **No personal data committed:** no target cities, price range, or buyer profile in any committed file. `profile.yaml`, `agent_instructions/*.local.md` are gitignored.
- **Output format preserved:** analyst response stays `RESUMEN:` + ~180-word bullet analysis; `summary_md`/`analyst_md` split via `_split_summary` unchanged; Telegram card structure unchanged.
- **Scoring math preserved:** dimension scores, weights flow, and `plot_bonus` unchanged.
- Env vars renamed `CHALET_*` → `SCOUT_*`; external-service vars (`BRIGHTDATA_*`, `SCRAPEOPS_*`, `TELEGRAM_*`, `OPENAI_*`) unchanged. Analyst model default `gpt-5.4-mini` via `SCOUT_ANALYST_MODEL`; chat model default `gpt-5-nano` via `SCOUT_CHAT_MODEL`.
- Keep all 180 existing tests green through the mechanical refactor tasks (2–3); new behavior added via TDD.
- Commit after every task. Work on branch `feat/genericize-and-personalize`.

---

## File map (post-refactor)

- `scout/core/` — orchestrate, models, db, migrations, config, **profile** (new), **registry** (new), logging_setup, runlock, utils; subpkgs filter/ score/ report/ notify/ analyse/ (+ **prompt_builder** new) scrape/base.py enrich/(base,osm,osrm)
- `scout/providers/es/` — scrape/(brightdata,idealista) enrich/(catastro,ine,sncziflood,neighbourhood,environment) regulatory/(boe_alerts,zonas_tensionadas) data/(CSVs) + `__init__.py` (registers bundle)
- `agent_instructions/property_analyst.md`, `chat_agent.md` — committed templates (placeholders)
- `config.yaml` (mechanical), `profile.example.yaml` (template), `profile.yaml` (gitignored)
- `run_daily.py`, `run_listener.py`, `run_setup.py`

---

## Task 1: Prep — safety backup + tooling

**Files:** none (git + environment only)

- [ ] **Step 1: Confirm branch and clean tree**

Run: `git branch --show-current && git status --short`
Expected: `feat/genericize-and-personalize` and a clean tree (only the committed spec).

- [ ] **Step 2: Create a local backup branch of main (pre-history-rewrite safety net)**

```bash
git branch backup/pre-genericize main
```

- [ ] **Step 3: Verify git-filter-repo is available (install if missing)**

```bash
git filter-repo --version || /usr/local/bin/python3.13 -m pip install --user git-filter-repo
```
Expected: a version string (needed later in Task 10; fine if install runs now).

- [ ] **Step 4: Baseline the test suite (green starting point)**

Run: `.venv/bin/python -m pytest -q`
Expected: `180 passed`.

- [ ] **Step 5: Commit (no-op marker via empty commit to mark plan start)**

```bash
git commit --allow-empty -m "chore: begin genericize-and-personalize refactor"
```

---

## Task 2: Rename package `chalet` → `scout` (flat, behavior-identical)

Mechanical rename only; **no** structural moves yet. Every import, entry point, test, and metadata reference switches from `chalet` to `scout`. Suite must stay green.

**Files:**
- Rename: `chalet/` → `scout/` (dir)
- Modify: every `*.py` under `scout/` and `tests/`, plus `run_daily.py`, `run_listener.py`, `scripts/manual_scrape.py`, `pyproject.toml`

**Interfaces:**
- Produces: importable package `scout` with the same module paths as before (`scout.config`, `scout.orchestrate`, `scout.scrape`, …).

- [ ] **Step 1: Move the package directory**

```bash
git mv chalet scout
```

- [ ] **Step 2: Rewrite all `chalet` import identifiers to `scout`**

```bash
grep -rl --include='*.py' -e 'chalet' scout tests run_daily.py run_listener.py scripts \
  | xargs sed -i '' -e 's/\bchalet\./scout./g' -e 's/from chalet\b/from scout/g' -e 's/import chalet\b/import scout/g'
```

- [ ] **Step 3: Update `pyproject.toml` package discovery and name**

Modify `pyproject.toml`:
```toml
[project]
name = "property-scout"
```
```toml
[tool.setuptools.packages.find]
include = ["scout*"]
```

- [ ] **Step 4: Update the Nominatim user-agent and any `chalet-spain` string literals that are identifiers (not user copy yet)**

Run to find remaining literal occurrences: `grep -rn --include='*.py' 'chalet' scout tests`
Expected after edits: only user-facing Spanish copy strings remain (handled in Task 8) — no `chalet` in import paths or module names.

- [ ] **Step 5: Reinstall the package so the new name resolves**

```bash
.venv/bin/python -m pip install -e ".[dev]" -q
```

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: `180 passed`. Fix any missed import until green.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: rename package chalet -> scout (behavior-identical)"
```

---

## Task 3: Reorg into `core/` + `providers/es/` + provider registry

Move modules into the agnostic core vs the Spain provider, add a minimal registry, and route scrape/enrich/regulatory through the resolved bundle. Suite stays green.

**Files:**
- Create: `scout/core/registry.py`, `scout/providers/__init__.py`, `scout/providers/es/__init__.py`
- Move (git mv) per the map below
- Modify: imports across `scout/` and `tests/`; `scout/core/orchestrate.py` (resolve + use bundle); `scout/core/scrape/base.py` (was `scout/scrape/__init__.py` dispatcher)

**Interfaces:**
- Produces:
  - `scout.core.registry.ProviderBundle` (dataclass): fields `scrape: Callable[[Profile, str], list[Listing]]`, `enrichers: dict[str, Callable]`, `regulatory: dict[str, Callable]`, `geocode_country: str`, `portal_base: str`, `slug_for: Callable[[str], str]`.
  - `scout.core.registry.register(country: str, portal: str, bundle: ProviderBundle) -> None`
  - `scout.core.registry.resolve(country: str, portal: str) -> ProviderBundle` (raises `KeyError` with a clear message if missing)

- [ ] **Step 1: Create the core/ and providers/ skeletons and move modules**

```bash
mkdir -p scout/core/scrape scout/core/enrich scout/providers/es/scrape scout/providers/es/enrich scout/providers/es/regulatory scout/providers/es/data
# core (agnostic)
git mv scout/orchestrate.py scout/models.py scout/db.py scout/migrations.py \
       scout/config.py scout/logging_setup.py scout/runlock.py scout/utils.py scout/core/
git mv scout/filter scout/score scout/report scout/notify scout/analyse scout/core/
git mv scout/enrich/base.py scout/enrich/osm.py scout/enrich/osrm.py scout/core/enrich/
git mv scout/scrape/__init__.py scout/core/scrape/base.py
# providers/es
git mv scout/scrape/brightdata.py scout/scrape/idealista.py scout/providers/es/scrape/
git mv scout/enrich/catastro.py scout/enrich/ine.py scout/enrich/sncziflood.py \
       scout/enrich/neighbourhood.py scout/enrich/environment.py scout/providers/es/enrich/
git mv scout/boe_alerts.py scout/zonas_tensionadas.py scout/providers/es/regulatory/
git mv data/ine/*.csv scout/providers/es/data/
touch scout/core/__init__.py scout/core/enrich/__init__.py scout/core/scrape/__init__.py \
      scout/providers/es/scrape/__init__.py scout/providers/es/enrich/__init__.py \
      scout/providers/es/regulatory/__init__.py
rmdir scout/scrape scout/enrich 2>/dev/null || true
```

- [ ] **Step 2: Rewrite import paths to the new module locations**

```bash
grep -rl --include='*.py' -e 'scout\.' scout tests | xargs sed -i '' \
  -e 's/scout\.orchestrate/scout.core.orchestrate/g' \
  -e 's/scout\.models/scout.core.models/g' \
  -e 's/scout\.db\b/scout.core.db/g' \
  -e 's/scout\.migrations/scout.core.migrations/g' \
  -e 's/scout\.config/scout.core.config/g' \
  -e 's/scout\.logging_setup/scout.core.logging_setup/g' \
  -e 's/scout\.runlock/scout.core.runlock/g' \
  -e 's/scout\.utils/scout.core.utils/g' \
  -e 's/scout\.filter/scout.core.filter/g' \
  -e 's/scout\.score/scout.core.score/g' \
  -e 's/scout\.report/scout.core.report/g' \
  -e 's/scout\.notify/scout.core.notify/g' \
  -e 's/scout\.analyse/scout.core.analyse/g' \
  -e 's/scout\.enrich\.base/scout.core.enrich.base/g' \
  -e 's/scout\.enrich\.osm/scout.core.enrich.osm/g' \
  -e 's/scout\.enrich\.osrm/scout.core.enrich.osrm/g' \
  -e 's/scout\.enrich\.catastro/scout.providers.es.enrich.catastro/g' \
  -e 's/scout\.enrich\.ine/scout.providers.es.enrich.ine/g' \
  -e 's/scout\.enrich\.sncziflood/scout.providers.es.enrich.sncziflood/g' \
  -e 's/scout\.enrich\.neighbourhood/scout.providers.es.enrich.neighbourhood/g' \
  -e 's/scout\.enrich\.environment/scout.providers.es.enrich.environment/g' \
  -e 's/scout\.boe_alerts/scout.providers.es.regulatory.boe_alerts/g' \
  -e 's/scout\.zonas_tensionadas/scout.providers.es.regulatory.zonas_tensionadas/g' \
  -e 's/scout\.scrape/scout.providers.es.scrape/g'
```
Note: `from scout.scrape import scrape_listings` (the old dispatcher) is handled in Step 4 — it becomes `scout.core.scrape.base`. Fix that import manually after this sed.

- [ ] **Step 3: Move the tests to mirror the layout**

```bash
mkdir -p tests/providers/es
git mv tests/scrape tests/providers/es/scrape
git mv tests/enrich/test_catastro.py tests/enrich/test_ine.py tests/enrich/test_sncziflood.py \
       tests/enrich/test_neighbourhood.py tests/enrich/test_environment.py tests/providers/es/
git mv tests/core/test_boe_alerts.py tests/core/test_zonas_tensionadas.py tests/providers/es/
touch tests/providers/__init__.py tests/providers/es/__init__.py
```
Then re-run the Step 2 sed over `tests/` if any import still points at an old path.

- [ ] **Step 4: Write `scout/core/registry.py`**

```python
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class ProviderBundle:
    scrape: Callable
    enrichers: dict[str, Callable] = field(default_factory=dict)
    regulatory: dict[str, Callable] = field(default_factory=dict)
    geocode_country: str = ""
    portal_base: str = ""
    slug_for: Callable[[str], str] = lambda name: name


_REGISTRY: dict[tuple[str, str], ProviderBundle] = {}


def register(country: str, portal: str, bundle: ProviderBundle) -> None:
    _REGISTRY[(country, portal)] = bundle


def resolve(country: str, portal: str) -> ProviderBundle:
    try:
        return _REGISTRY[(country, portal)]
    except KeyError:
        raise KeyError(
            f"No provider registered for country={country!r} portal={portal!r}. "
            f"Available: {sorted(_REGISTRY)}"
        )
```

- [ ] **Step 5: Write `scout/providers/es/__init__.py` registering the ES bundle**

```python
"""Spain / Idealista reference provider. Imported for its registration side effect."""
from scout.core.registry import ProviderBundle, register
from scout.providers.es.scrape import brightdata, idealista
from scout.providers.es.scrape.idealista import CITY_SLUGS, _BASE

register(
    "es",
    "idealista",
    ProviderBundle(
        scrape=None,  # dispatch stays in core.scrape.base for now (Task 8 wires slug/base/country)
        geocode_country="España",
        portal_base=_BASE,
        slug_for=lambda name: CITY_SLUGS.get(name, name),
    ),
)
```
And `scout/providers/__init__.py`:
```python
from scout.providers import es  # noqa: F401  (registers the ES bundle on import)
```

- [ ] **Step 6: Point the dispatcher and orchestrate at the new paths**

In `scout/core/scrape/base.py`, update the deferred import to `from scout.providers.es.scrape import brightdata, idealista`. In `scout/core/orchestrate.py`, ensure `import scout.providers` runs once (add `import scout.providers  # noqa: F401` near the top) so registration happens, and update the `idealista as ide` import to `from scout.providers.es.scrape import idealista as ide`. Update the CSV path constants:
```python
_ES_DATA = Path(__file__).resolve().parents[2] / "providers" / "es" / "data"
_INE_CSV = _ES_DATA / "municipal_price_psqm.csv"
_NEIGHBOURHOOD_CSV = _ES_DATA / "municipal_neighbourhood.csv"
_ENVIRONMENT_CSV = _ES_DATA / "municipal_environment.csv"
```

- [ ] **Step 7: Reinstall and run the suite**

```bash
.venv/bin/python -m pip install -e ".[dev]" -q
.venv/bin/python -m pytest -q
```
Expected: `180 passed`. Fix stragglers until green.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor: split into scout/core + scout/providers/es with provider registry"
```

---

## Task 4: `Profile` model + loader (TDD)

**Files:**
- Create: `scout/core/profile.py`, `tests/core/test_profile.py`

**Interfaces:**
- Produces:
  - `scout.core.profile.Profile` with `.country: str`, `.portal: str`, `.search: ProfileSearch`, `.buyer: ProfileBuyer`
  - `ProfileCity(name, lat, lon, radius_km, portal_slug: str | None)`
  - `ProfileSearch(cities: list[ProfileCity], price_min_eur, price_max_eur, property_type, preferred_plot_m2)`
  - `ProfileBuyer(household, purpose, top_priorities, investment_angle, investment_notes, must_haves, deal_breakers, response_language, extra_notes)`
  - `load_profile(path) -> Profile`; `profile_exists(path) -> bool`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_profile.py
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
  household: "pareja post-30"
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/core/test_profile.py -q`
Expected: FAIL — `ModuleNotFoundError: scout.core.profile`.

- [ ] **Step 3: Implement `scout/core/profile.py`**

```python
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator


class ProfileCity(BaseModel):
    name: str
    lat: float
    lon: float
    radius_km: float
    portal_slug: str | None = None


class ProfileSearch(BaseModel):
    cities: list[ProfileCity]
    price_min_eur: int = Field(gt=0)
    price_max_eur: int = Field(gt=0)
    property_type: str
    preferred_plot_m2: int = Field(default=2000, gt=0)

    @model_validator(mode="after")
    def _range(self) -> "ProfileSearch":
        if self.price_min_eur >= self.price_max_eur:
            raise ValueError("price_min_eur must be < price_max_eur")
        return self


class ProfileBuyer(BaseModel):
    household: str = ""
    purpose: str = ""
    top_priorities: list[str] = Field(default_factory=list)
    investment_angle: bool = False
    investment_notes: str = ""
    must_haves: list[str] = Field(default_factory=list)
    deal_breakers: list[str] = Field(default_factory=list)
    response_language: str = "es"
    extra_notes: str = ""


class Profile(BaseModel):
    country: str
    portal: str
    search: ProfileSearch
    buyer: ProfileBuyer = Field(default_factory=ProfileBuyer)


def load_profile(path: Path | str) -> Profile:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return Profile.model_validate(raw)


def profile_exists(path: Path | str) -> bool:
    return Path(path).is_file()
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/core/test_profile.py -q`
Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add scout/core/profile.py tests/core/test_profile.py
git commit -m "feat: Profile model + loader for gitignored profile.yaml"
```

---

## Task 5: Split config → mechanical `config.yaml` + wire pipeline to `Profile`

Move city/price/plot/property_type out of `Config` into `Profile`; `config.yaml` keeps only mechanical settings. Thread `Profile` through `orchestrate`, scrape dispatch, and entry points.

**Files:**
- Modify: `scout/core/config.py` (drop `cities`, `Search`; add `report.app_name`), `config.yaml`, `scout/core/orchestrate.py`, `scout/core/scrape/base.py`, `run_daily.py`, `run_listener.py`, `scripts/manual_scrape.py`
- Create: `profile.example.yaml`; `.gitignore` entry
- Modify tests: `tests/core/test_config.py`, `tests/core/test_orchestrate.py`, `tests/scrape`→`tests/providers/es/scrape` fixtures that build a Config

**Interfaces:**
- Consumes: `scout.core.profile.Profile` (Task 4)
- Produces:
  - `Config` without `cities`/`search`; `report.app_name: str` added.
  - `run_once(cfg: Config, profile: Profile, conn, paths) -> int`
  - `_run_city(cfg, profile, city, conn, paths)`, `scrape_listings(cfg, profile, city_name)`

- [ ] **Step 1: Write/adjust failing tests**

Add to `tests/core/test_orchestrate.py` (the e2e test) a `profile` built from `profile.example.yaml`, and change the call to `run_once(cfg, profile, conn, paths)`. Update `tests/core/test_config.py` to drop `cities`/`search` from the sample YAML and assert `cfg.report.app_name` parses. (Full sample YAML shown in Step 3.)

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/core/test_config.py tests/core/test_orchestrate.py -q`
Expected: FAIL (Config still requires `cities`; `run_once` arity mismatch).

- [ ] **Step 3: Edit `scout/core/config.py`**

Remove the `City` and `Search` models and the `cities`/`search` fields from `Config`. Keep `Scrape`, `Weights`, `Scoring`, `RunSchedule`. Extend `Report`:
```python
class Report(BaseModel):
    language: Literal["es", "en"] = "es"
    top_n: int = Field(gt=0, le=50)
    output_dir: str
    timezone: str
    app_name: str = "Property Scout"
```
`Config` becomes: `scrape: Scrape`, `report: Report`, `scoring: Scoring`, `run: RunSchedule`. Keep the `BRIGHTDATA_COLLECTOR_ID` env merge in `load_config`.

New mechanical `config.yaml`:
```yaml
scrape:
  provider: brightdata
  pages: 1
  delay_ms: 3000
  fetch_details: false
  details_limit: 5
report:
  language: es
  top_n: 10
  output_dir: data/reports
  timezone: Europe/Madrid
  app_name: Property Scout
scoring:
  weights: {price: 0.18, location: 0.20, commute: 0.15, legal: 0.15,
            regulatory: 0.07, environmental: 0.10, neighbourhood: 0.10, infrastructure: 0.05}
run: {hour: 0, minute: 0}
```

- [ ] **Step 4: Create `profile.example.yaml` (committed template, generic)**

```yaml
# Personal profile — copy to profile.yaml (gitignored) or run: python -m scout setup
country: es
portal: idealista
search:
  cities:
    - {name: your-city, lat: 0.0, lon: 0.0, radius_km: 30}
  price_min_eur: 100000
  price_max_eur: 200000
  property_type: chalet_independiente
  preferred_plot_m2: 2000
buyer:
  household: "describe your household"
  purpose: primary_residence
  top_priorities: [urban_commute, residential_character, plot_usability]
  investment_angle: true
  investment_notes: "seasonal rental / room rental viability"
  must_haves: ["grid electricity, mains water, sewage, paved access"]
  deal_breakers: ["attached / semi-detached"]
  response_language: es
  extra_notes: |
    Anything else the AI analyst should know about your priorities.
```

- [ ] **Step 5: Thread `Profile` through the pipeline**

In `scout/core/scrape/base.py`: change signature to `scrape_listings(cfg, profile, city_name)` and read `price_min/price_max` from `profile.search`; keep `pages`/`delay_ms` from `cfg.scrape`. In `scout/core/orchestrate.py`: `run_once(cfg, profile, conn, paths)` iterates `profile.search.cities`; `_run_city(cfg, profile, city, …)`; `_scrape_and_persist_city` reads price from `profile.search`, radius/centre from the `ProfileCity`; `plot_threshold = profile.search.preferred_plot_m2`; `_city_centres` maps over `profile.search.cities` using `.lat/.lon`; report `price_min/price_max` come from `profile.search`. Weights/top_n/scrape flags stay from `cfg`.

- [ ] **Step 6: Update entry points**

`run_daily.py` / `run_listener.py` / `scripts/manual_scrape.py`: `from scout.core.profile import load_profile, profile_exists`; load `profile.yaml` (path `PROJECT_ROOT / "profile.yaml"`), pass into `run_once`. The `--city` filter in `run_daily.py` now filters `profile.search.cities` (build a filtered `Profile` via `profile.model_copy(update={"search": profile.search.model_copy(update={"cities": [...]})})`).

- [ ] **Step 7: gitignore + example plumbing**

Append to `.gitignore`:
```
profile.yaml
agent_instructions/*.local.md
```

- [ ] **Step 8: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: green (update any test still constructing the old `Config(cities=…)`; those build a `Profile` instead). Target: all pass.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat: split personal profile out of config; wire pipeline to Profile"
```

---

## Task 6: Setup wizard + first-run gate (TDD)

**Files:**
- Create: `scout/core/setup_wizard.py`, `run_setup.py`, `tests/core/test_setup_wizard.py`
- Modify: `run_daily.py`, `run_listener.py` (first-run gate)

**Interfaces:**
- Consumes: `Profile`, `ProfileCity`, `ProfileSearch`, `ProfileBuyer` (Task 4)
- Produces:
  - `scout.core.setup_wizard.build_profile(answers: dict) -> Profile`
  - `scout.core.setup_wizard.write_profile(profile: Profile, path) -> None` (YAML dump)
  - `scout.core.setup_wizard.run_wizard(input_fn=input, path=...) -> Profile` (interactive; `input_fn` injected for tests)

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_setup_wizard.py
from scout.core.setup_wizard import build_profile, write_profile, run_wizard
from scout.core.profile import load_profile


def test_build_profile_from_answers():
    prof = build_profile({
        "country": "es", "portal": "idealista",
        "cities": [{"name": "girona", "lat": 41.98, "lon": 2.82, "radius_km": 30}],
        "price_min_eur": 150000, "price_max_eur": 250000,
        "property_type": "chalet_independiente", "preferred_plot_m2": 2000,
        "household": "pareja post-30", "investment_angle": True,
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
        "es", "idealista", "girona", "41.98", "2.82", "30", "",   # one city then blank to stop
        "150000", "250000", "chalet_independiente", "2000",
        "pareja post-30", "primary_residence", "urban_commute", "si", "", "", "", "es", "",
    ])
    p = tmp_path / "profile.yaml"
    prof = run_wizard(input_fn=lambda _prompt="": next(answers), path=p)
    assert p.is_file()
    assert prof.search.cities[0].name == "girona"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/core/test_setup_wizard.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `scout/core/setup_wizard.py`**

```python
from pathlib import Path

import yaml

from scout.core.profile import Profile, ProfileBuyer, ProfileCity, ProfileSearch


def build_profile(a: dict) -> Profile:
    search = ProfileSearch(
        cities=[ProfileCity(**c) for c in a["cities"]],
        price_min_eur=a["price_min_eur"],
        price_max_eur=a["price_max_eur"],
        property_type=a["property_type"],
        preferred_plot_m2=a.get("preferred_plot_m2", 2000),
    )
    buyer = ProfileBuyer(
        household=a.get("household", ""),
        purpose=a.get("purpose", ""),
        top_priorities=a.get("top_priorities", []),
        investment_angle=bool(a.get("investment_angle", False)),
        investment_notes=a.get("investment_notes", ""),
        must_haves=a.get("must_haves", []),
        deal_breakers=a.get("deal_breakers", []),
        response_language=a.get("response_language", "es"),
        extra_notes=a.get("extra_notes", ""),
    )
    return Profile(country=a["country"], portal=a["portal"], search=search, buyer=buyer)


def write_profile(profile: Profile, path: Path | str) -> None:
    Path(path).write_text(
        yaml.safe_dump(profile.model_dump(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def run_wizard(input_fn=input, path: Path | str = "profile.yaml") -> Profile:
    def ask(label, default=""):
        val = input_fn(f"{label}{f' [{default}]' if default else ''}: ").strip()
        return val or default

    print("== Configuración personal de Property Scout ==")
    country = ask("País (código)", "es")
    portal = ask("Portal", "idealista")
    cities = []
    print("Añade ciudades objetivo (deja el nombre en blanco para terminar):")
    while True:
        name = ask("  Ciudad")
        if not name:
            break
        cities.append({
            "name": name,
            "lat": float(ask("  lat")),
            "lon": float(ask("  lon")),
            "radius_km": float(ask("  radio km", "30")),
        })
    answers = {
        "country": country, "portal": portal, "cities": cities,
        "price_min_eur": int(ask("Precio mínimo €", "150000")),
        "price_max_eur": int(ask("Precio máximo €", "250000")),
        "property_type": ask("Tipo de propiedad", "chalet_independiente"),
        "preferred_plot_m2": int(ask("Parcela preferida m²", "2000")),
        "household": ask("Describe tu hogar/perfil"),
        "purpose": ask("Propósito", "primary_residence"),
        "top_priorities": [p for p in ask("Prioridades (coma)").split(",") if p.strip()],
        "investment_angle": ask("¿Ángulo de inversión? (si/no)", "no").lower().startswith("s"),
        "investment_notes": ask("Notas de inversión"),
        "must_haves": [m for m in ask("Imprescindibles (coma)").split(",") if m.strip()],
        "deal_breakers": [d for d in ask("Descartes (coma)").split(",") if d.strip()],
        "response_language": ask("Idioma de respuesta IA", "es"),
        "extra_notes": ask("Notas extra para la IA"),
    }
    profile = build_profile(answers)
    write_profile(profile, path)
    print(f"Perfil guardado en {path}")
    return profile
```
Note: `top_priorities` in the test passes a single token via the positional flow — adjust the test's city-stop sentinel so the injected iterator matches the prompt order; keep the iterator answers aligned with the prompts above.

- [ ] **Step 4: Create `run_setup.py`**

```python
#!/usr/bin/env python3
"""Interactive setup: writes profile.yaml for personal use."""
import sys
from pathlib import Path

from scout.core.setup_wizard import run_wizard

PROJECT_ROOT = Path(__file__).resolve().parent

if __name__ == "__main__":
    run_wizard(path=PROJECT_ROOT / "profile.yaml")
    sys.exit(0)
```
Also add `python -m scout setup` support: create `scout/__main__.py`:
```python
import sys

if __name__ == "__main__" and sys.argv[1:2] == ["setup"]:
    from pathlib import Path
    from scout.core.setup_wizard import run_wizard
    run_wizard(path=Path.cwd() / "profile.yaml")
```

- [ ] **Step 5: Add the first-run gate to entry points**

In `run_daily.py` and `run_listener.py`, before loading the profile:
```python
from scout.core.profile import profile_exists
_PROFILE = PROJECT_ROOT / "profile.yaml"
if not profile_exists(_PROFILE):
    print("No hay profile.yaml. Ejecuta:  python -m scout setup", file=sys.stderr)
    sys.exit(4)
```

- [ ] **Step 6: Run the suite**

Run: `.venv/bin/python -m pytest tests/core/test_setup_wizard.py -q && .venv/bin/python -m pytest -q`
Expected: wizard tests pass; full suite stays green.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: interactive setup wizard + first-run profile gate"
```

---

## Task 7: Externalize agent instructions + generic prompt builder (TDD)

**Files:**
- Create: `agent_instructions/property_analyst.md`, `agent_instructions/chat_agent.md`, `scout/core/analyse/prompt_builder.py`, `tests/core/test_prompt_builder.py`
- Modify: `scout/core/analyse/property_analyst.py`, `scout/core/notify/chat_agent.py`, callers (`orchestrate`, `run_listener`), `tests/analyse/test_property_analyst.py`, `tests/notify/test_chat_agent.py`

**Interfaces:**
- Consumes: `Profile` (Task 4)
- Produces:
  - `scout.core.analyse.prompt_builder.compose_buyer_profile(buyer: ProfileBuyer) -> str`
  - `build_system_prompt(name: str, profile: Profile) -> str` — loads `agent_instructions/{name}.local.md` if present else `{name}.md`, replaces `{cities} {price_min} {price_max} {property_type} {preferred_plot_m2} {buyer_profile} {response_language}` tokens.
  - `analyse_top(top, profile)` (profile arg added)
  - `ChatAgent(profile=..., api_key=None, model=None)` (constructed from a Profile)

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_prompt_builder.py
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
  household: "pareja post-30"
  investment_angle: true
  response_language: es
"""


def test_compose_buyer_profile_includes_fields(tmp_path):
    p = tmp_path / "profile.yaml"; p.write_text(_YAML)
    prof = load_profile(p)
    text = compose_buyer_profile(prof.buyer)
    assert "pareja post-30" in text
    assert "Inversión" in text


def test_build_system_prompt_fills_placeholders_no_hardcoded_city(tmp_path):
    p = tmp_path / "profile.yaml"; p.write_text(_YAML)
    prof = load_profile(p)
    out = build_system_prompt("property_analyst", prof)
    assert "girona" in out
    assert "{cities}" not in out and "{buyer_profile}" not in out
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/core/test_prompt_builder.py -q`
Expected: FAIL — module + instruction files missing.

- [ ] **Step 3: Create the instruction templates (generic, placeholders)**

`agent_instructions/property_analyst.md` — the current analyst system prompt with every hardcoded city/profile replaced by placeholders. Header block:
```
Eres un analista inmobiliario que evalúa propiedades para el siguiente perfil de comprador,
en estas ciudades objetivo: {cities} (máximo su radio configurado del centro urbano).

PERFIL DEL COMPRADOR
{buyer_profile}

CRITERIOS
- Precio objetivo: {price_min}–{price_max} €. Tipo: {property_type}. Parcela preferida ≥ {preferred_plot_m2} m².
- Señala incumplimientos como alerta crítica (tipo, radio, servicios urbanos, parcela).
```
Keep the existing EVALUACIÓN priorities, the exact `RESUMEN:` + 6-bullet output contract, and "Responde SIEMPRE en {response_language}". **Do not change the output contract.**

`agent_instructions/chat_agent.md` — the chat system template with `{cities}`, `{price_min}`, `{price_max}`, `{buyer_profile}`, `{response_language}` placeholders; no "pareja"/city literals; the `/scout` command help stays generic (examples derived at call time from cities).

- [ ] **Step 4: Implement `scout/core/analyse/prompt_builder.py`**

```python
from pathlib import Path

from scout.core.profile import Profile, ProfileBuyer

_DIR = Path(__file__).resolve().parents[3] / "agent_instructions"


def _template_path(name: str) -> Path:
    local = _DIR / f"{name}.local.md"
    return local if local.is_file() else _DIR / f"{name}.md"


def compose_buyer_profile(buyer: ProfileBuyer) -> str:
    lines: list[str] = []
    if buyer.household:
        lines.append(f"Hogar: {buyer.household}")
    if buyer.purpose:
        lines.append(f"Propósito: {buyer.purpose}")
    if buyer.top_priorities:
        lines.append("Prioridades: " + ", ".join(buyer.top_priorities))
    if buyer.investment_angle:
        note = f" ({buyer.investment_notes})" if buyer.investment_notes else ""
        lines.append(f"Inversión: sí{note}")
    if buyer.must_haves:
        lines.append("Imprescindibles: " + "; ".join(buyer.must_haves))
    if buyer.deal_breakers:
        lines.append("Descartes: " + "; ".join(buyer.deal_breakers))
    if buyer.extra_notes:
        lines.append(buyer.extra_notes.strip())
    return "\n".join(lines)


def build_system_prompt(name: str, profile: Profile) -> str:
    template = _template_path(name).read_text(encoding="utf-8")
    s = profile.search
    repl = {
        "{cities}": ", ".join(c.name for c in s.cities),
        "{price_min}": f"{s.price_min_eur:,}".replace(",", "."),
        "{price_max}": f"{s.price_max_eur:,}".replace(",", "."),
        "{property_type}": s.property_type,
        "{preferred_plot_m2}": str(s.preferred_plot_m2),
        "{buyer_profile}": compose_buyer_profile(profile.buyer),
        "{response_language}": profile.buyer.response_language,
    }
    for k, v in repl.items():
        template = template.replace(k, v)
    return template
```

- [ ] **Step 5: Rewire the analyst (output format unchanged)**

In `scout/core/analyse/property_analyst.py`: delete `_SYSTEM_PROMPT`; rename model constant/env to `SCOUT_ANALYST_MODEL` (default `gpt-5.4-mini`). Change `analyse_top(top)` → `analyse_top(top, profile)` and `_analyse_one(s, client, api_key, system_prompt)`; build `system_prompt = build_system_prompt("property_analyst", profile)` once in `analyse_top` and pass down. Leave `_build_prompt`, `_split_summary`, payload keys (`max_completion_tokens`, `reasoning_effort`) untouched. Update the caller in `orchestrate._run_city`: `asyncio.run(analyse_top(scored, profile))`.

- [ ] **Step 6: Rewire the chat agent**

In `scout/core/notify/chat_agent.py`: replace `_SYSTEM_TMPL` usage with `build_system_prompt("chat_agent", profile)`; constructor becomes `ChatAgent(*, profile, api_key=None, model=None)`; model env `SCOUT_CHAT_MODEL`. Derive the `/scout` example cities from `profile.search.cities`. Update `run_listener.py` to pass the loaded `profile`.

- [ ] **Step 7: Update analyst/chat tests for the new signatures**

Adjust `tests/analyse/test_property_analyst.py` and `tests/notify/test_chat_agent.py` to pass a `Profile` (build a minimal one). Add an assertion that the analyst still splits on `RESUMEN:` (format-preservation regression).

- [ ] **Step 8: Run the suite**

Run: `.venv/bin/python -m pytest -q`
Expected: green.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat: externalize generic agent instructions; profile-driven prompts"
```

---

## Task 8: Sweep remaining hardcoded values in `scout/`

**Files:**
- Modify: `scout/core/notify/telegram.py`, `scout/providers/es/scrape/idealista.py`, `scout/providers/es/__init__.py`, `scout/core/orchestrate.py`, `scout/core/score/dimensions.py`

**Interfaces:**
- Consumes: `Config.report.app_name`, `bundle.geocode_country`, `bundle.slug_for`, `bundle.portal_base` (Task 3/5)

- [ ] **Step 1: Make Telegram headers use `app_name`**

In `scout/core/notify/telegram.py`, replace the two literals `"🏠 <b>Chalet Spain — Informe Diario</b>"` and `"🚨 <b>Chalet Spain — Error en el ciclo diario</b>"` with the passed `app_name` (thread `app_name: str` from `cfg.report.app_name` through `notify_success`/`notify_failure`); drop the stale "Diario". Update `orchestrate` callers and `tests/notify/test_telegram_notify.py`.

- [ ] **Step 2: Make Idealista slug/base/country provider-driven**

In `scout/providers/es/scrape/idealista.py`: keep `CITY_SLUGS` and `_BASE` as the ES provider's data, but have `scrape()` accept `slug_for`/`portal_base`/`geocode_country` (or read them from the resolved bundle). Replace the hardcoded `geocode(f"{query}, España")` with the bundle's `geocode_country`, and `Nominatim(user_agent="chalet-spain-scout")` with `"property-scout"`. Per-city `portal_slug` from `ProfileCity` overrides `CITY_SLUGS` when set.

- [ ] **Step 3: Neutralize the scoring comment**

In `scout/core/score/dimensions.py`, change the `# Couple-weighted: …` comment to a profile-neutral description (amenity sub-weights stay as documented defaults). No behavior change.

- [ ] **Step 4: Grep to confirm no personal/branding literals remain in code**

Run: `grep -rniE 'chalet|pareja|barcelona|valencia|girona|post-30|españa' scout | grep -v '\.pyc'`
Expected: no matches in `scout/` except ES provider data filenames/paths (CSV column docs) that are legitimately Spain-specific and non-personal. Fix any stray literal.

- [ ] **Step 5: Run the suite**

Run: `.venv/bin/python -m pytest -q`
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: replace hardcoded profile/branding/country literals with config-driven values"
```

---

## Task 9: Env var renames + db rename + `.env.example`

**Files:**
- Modify: `run_daily.py`, `run_listener.py`, `scripts/manual_scrape.py`, `scout/core/**` (any `CHALET_*`), `.env.example`, `scripts/*.plist.template`

**Interfaces:** none new (string/env changes)

- [ ] **Step 1: Rename env vars**

```bash
grep -rl 'CHALET_' scout run_daily.py run_listener.py scripts | xargs sed -i '' \
  -e 's/CHALET_DB_PATH/SCOUT_DB_PATH/g' \
  -e 's/CHALET_LOG_DIR/SCOUT_LOG_DIR/g' \
  -e 's/CHALET_ANALYST_MODEL/SCOUT_ANALYST_MODEL/g' \
  -e 's/CHALET_CHAT_MODEL/SCOUT_CHAT_MODEL/g'
```
Default DB path becomes `data/scout.db` in `run_daily.py`/`run_listener.py`.

- [ ] **Step 2: Update `.env.example`**

Add `SCOUT_ANALYST_MODEL` (default `gpt-5.4-mini`), `SCOUT_CHAT_MODEL` (default `gpt-5-nano`), keep `BRIGHTDATA_*`, `SCRAPEOPS_*`, `TELEGRAM_*`, `OPENAI_*`. Fix the stale "gpt-5-mini" analyst comment.

- [ ] **Step 3: Run the suite**

Run: `.venv/bin/python -m pytest -q`
Expected: green (update any test asserting `CHALET_*`).

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor: rename CHALET_* env vars to SCOUT_*; default db data/scout.db"
```

---

## Task 10: Git history rewrite (redact email + collector id)

> **Superseded (2026-07-14):** publication decision changed to a fresh HEAD-only public repository (old repo stays private), so this history-rewrite step will not run as written.

> **Execution order:** This is the VERY LAST task — run it only after Task 11 (docs) is committed and the branch is merged to `main`. It is numbered 10 for grouping but executes after 11. History rewrite + force-push must come after all content is final.

**Files:** none (history rewrite)

- [ ] **Step 1: Confirm backup exists and note current main HEAD**

Run: `git rev-parse backup/pre-genericize && git log --oneline -1 main`
Expected: backup SHA prints.

- [ ] **Step 2: Merge this feature branch to main first (so the rewrite covers final state)**

This step runs only when Tasks 1–9 + 11 are merged. Fast-forward `main`:
```bash
git checkout main && git merge --ff-only feat/genericize-and-personalize
```

- [ ] **Step 3: Write the replacement map and run filter-repo**

Substitute `<OWNER_EMAIL>` and `<COLLECTOR_ID>` below with your real email address and Bright Data collector id when building `/tmp/scout-redactions.txt` locally — do not commit the real values anywhere.

```bash
printf '<OWNER_EMAIL>==>***REDACTED***\n<COLLECTOR_ID>==>***REDACTED***\n' > /tmp/scout-redactions.txt
git filter-repo --replace-text /tmp/scout-redactions.txt --force
```

- [ ] **Step 4: Verify redaction across all history**

Run (substituting your real values for the placeholders): `git log -p --all | grep -nE '<OWNER_EMAIL>|<COLLECTOR_ID>' | head`
Expected: no output (clean).

- [ ] **Step 5: Re-add origin and force-push (filter-repo drops the remote)**

```bash
git remote add origin https://github.com/mattsebastianh/chalet-spain-v2.git
git push --force origin main
```

- [ ] **Step 6: Commit** — none (history operation). Keep `backup/pre-genericize` until verified in the GitHub UI.

---

## Task 11: Docs rewrite (final step)

**Files:**
- Modify: `README.md`, `CLAUDE.md`, `docs/README.md`, `docs/product/PRD.md`, `docs/engineering/ARCHITECTURE.md`, `docs/engineering/FEATURES.md`, `docs/prompts/*` (note prompts now live in `agent_instructions/`)
- Rename references: project → `property-scout`, package → `scout`

**Interfaces:** none

- [ ] **Step 1: README** — rewrite for `property-scout`: generic intro (no couple/city profile), setup = `python -m scout setup` → `profile.yaml`, `config.yaml` mechanical, `agent_instructions/` customization, `core/providers/es` architecture, ES as reference implementation, renamed env vars, License section retained.

- [ ] **Step 2: CLAUDE.md** — update "What this project does" to the generic framing; architecture section to `core/` + `providers/es/`; env-var table to `SCOUT_*`; add profile.yaml/wizard + agent_instructions to Key files.

- [ ] **Step 3: PRD / ARCHITECTURE / FEATURES** — describe the generic pipeline with ES reference impl, profile/config split, wizard, externalized instructions, provider registry. Remove embedded personal profile (state it lives in the user's gitignored `profile.yaml`). Move the analyst/chat prompt references to point at `agent_instructions/`.

- [ ] **Step 4: docs/README.md index** — add profile/setup + agent_instructions; add this spec + plan under specs/planning.

- [ ] **Step 5: Verify no personal data or stale names in committed docs**

Run (substituting `<OWNER_EMAIL>` with your real email): `grep -rniE 'pareja|couple|post-30|<OWNER_EMAIL>|CHALET_' README.md CLAUDE.md docs | grep -v 'specs/2026-07-07' | grep -v 'planning/2026-07-13'`
Expected: no matches (except historical spec/plan files that legitimately record past state).

- [ ] **Step 6: Full suite + `--check` smoke**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python run_daily.py --check`
Expected: tests green; `--check` either runs (if a local `profile.yaml` exists) or prints the setup-gate message and exits 4.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "docs: rewrite for property-scout (generic template, profile-driven, core/providers)"
```

---

## Self-review notes
- **Spec coverage:** Phases 1–7 of the spec map to Tasks 4–5 (config/profile), 6 (wizard+gate), 3 (reorg+registry) & 2 (rename), 7 (instructions), 8 (hardcoded sweep) & 9 (env), 10 (history), 11 (docs). Implementation reorders rename/reorg before the new code for a single green refactor pass.
- **Output format:** Task 7 Steps 3/5/7 explicitly preserve the `RESUMEN:` contract and payload shape.
- **Type consistency:** `Profile`/`ProfileSearch`/`ProfileBuyer`/`ProfileCity` names and `build_system_prompt`/`compose_buyer_profile`/`analyse_top(top, profile)`/`ChatAgent(profile=…)` signatures are used identically across Tasks 4–8.
- **No personal data committed:** enforced by Task 8 Step 4 and Task 11 Step 5 greps.
