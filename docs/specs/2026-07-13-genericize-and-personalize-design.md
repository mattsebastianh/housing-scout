# Design Spec — Genericize & Personalize (`chalet-spain` → `property-scout`)

**Date:** 2026-07-13
**Status:** Approved (design) — pending implementation plan
**Branch:** `feat/genericize-and-personalize`

---

## 1. Goal

Turn this single-owner "Chalet Spain" tool into a clean, reusable **`property-scout`**
template where:

1. **No personal profile or preferences are committed to the repo.** All personal
   data (target cities, price range, buyer profile) lives in a **gitignored
   `profile.yaml`**, created by an interactive **setup wizard** on first use.
2. **The AI agent instructions are external, generic, and customizable** — the
   analyst/chat system prompts move out of Python into editable
   `agent_instructions/*.md` templates filled with placeholders from the user's
   profile. No hardcoded cities or buyer profile anywhere in `scout/`.
3. **The architecture is a portal/country-agnostic core with pluggable
   providers.** Spain/Idealista ships as the reference implementation under
   `scout/providers/es/`; the core pipeline is generic.
4. **Existing git-history exposure is fixed** (email + collector id purged from
   history).
5. Output structure, scoring behavior, and the existing feature set are preserved.

Non-goal: implementing a second country/portal now. We build clean extension
points and ship only the ES reference implementation.

---

## 2. Decisions (from brainstorming)

| # | Decision |
|---|---|
| Config split | `profile.yaml` (gitignored) for personal data + `profile.example.yaml` (committed template); `config.yaml` (committed) holds only mechanical settings |
| AI profile | Hybrid: structured buyer fields **plus** free-text notes, injected into external instruction templates via placeholders |
| Git history | `git-filter-repo` to purge email + collector id from all history; force-push to private origin |
| Reorg scope | Generic naming (`property-scout`, package `scout`) + `core/` + `providers/es/` layout |
| Multi-country | Framework + ES reference implementation only (pluggable, documented extension points) |
| Analyst prompt | Extracted to `agent_instructions/property_analyst.md` with generic placeholders; customizable per user; model via `SCOUT_ANALYST_MODEL` env (default `gpt-5.4-mini`, OpenAI) |
| Output format | **Unchanged** — `RESUMEN:` + ~180-word bullet analysis, `summary_md` / `analyst_md` split preserved |
| Wizard language | Spanish (matches domain; trivially switchable) |
| History prose | Only email + collector id purged from history; buyer-profile prose in old commits is not PII and remains — current & future tree is clean of it |

---

## 3. Target repository layout

```
property-scout/                      # repo/project (was chalet_spain_v2 / "Chalet Spain")
├── scout/                           # Python package (was chalet/)
│   ├── __init__.py
│   ├── core/                        # portal/country-agnostic pipeline
│   │   ├── orchestrate.py
│   │   ├── models.py
│   │   ├── db.py  migrations.py
│   │   ├── config.py                # mechanical config.yaml loader
│   │   ├── profile.py               # personal profile.yaml loader (pydantic)
│   │   ├── registry.py              # PROVIDERS registry + resolve(country, portal)
│   │   ├── logging_setup.py  runlock.py  utils.py
│   │   ├── filter/                  # hard_excl, dedup, persist
│   │   ├── score/                   # dimensions, compose
│   │   ├── report/                  # markdown + templates
│   │   ├── notify/                  # telegram, listener, chat_agent
│   │   ├── analyse/                 # property_analyst + prompt_builder
│   │   ├── scrape/base.py           # ScrapeProvider protocol + dispatcher
│   │   └── enrich/                  # base.py + osm.py, osrm.py (global enrichers)
│   └── providers/
│       ├── __init__.py              # imports es to trigger registration
│       └── es/                      # Spain reference implementation
│           ├── __init__.py          # registers bundle in core.registry
│           ├── scrape/              # brightdata.py, idealista.py
│           ├── enrich/              # catastro, ine, sncziflood, neighbourhood, environment
│           ├── regulatory/          # boe_alerts, zonas_tensionadas
│           └── data/                # ES reference CSVs (was data/ine/)
├── agent_instructions/
│   ├── property_analyst.md          # committed default template (placeholders)
│   └── chat_agent.md                # committed default template (placeholders)
│   # property_analyst.local.md / chat_agent.local.md — gitignored user overrides
├── config.yaml                      # mechanical, committed
├── profile.example.yaml             # committed template
│   # profile.yaml — gitignored (personal)
├── run_daily.py  run_listener.py  run_setup.py
├── scripts/                         # launchd installers, manual_scrape
├── data/                            # runtime state: scout.db, reports/, (logs/)
├── docs/  tests/  LICENSE  pyproject.toml  .env.example
```

Runtime state stays under `data/` (db renamed `chalet.db` → `scout.db`). ES
**reference data** (the INE/environment/neighbourhood CSVs) moves into
`scout/providers/es/data/`, owned by the provider.

---

## 4. Phase plan

### Phase 0 — Prep
- Feature branch `feat/genericize-and-personalize` (created).
- Local backup branch of `main` before any history rewrite.
- Verify `git-filter-repo` available (install if needed).

### Phase 1 — Config / profile separation
- **`scout/core/profile.py`** — pydantic `Profile` model + `load_profile(path)`.
  Loaded from gitignored `profile.yaml`. Shape:
  ```yaml
  country: es
  portal: idealista
  search:
    cities:
      - {name, lat, lon, radius_km, portal_slug?}   # portal_slug optional override
    price_min_eur: 150000
    price_max_eur: 250000
    property_type: chalet_independiente
    preferred_plot_m2: 2000
  buyer:
    household: "..."                 # free text
    purpose: primary_residence
    top_priorities: [...]            # ordered list
    investment_angle: true
    investment_notes: "..."
    must_haves: [...]
    deal_breakers: [...]
    response_language: es
    extra_notes: |                   # free-form catch-all
      ...
  ```
- **`config.yaml`** stripped to mechanical settings only: `scrape.*`,
  `scoring.weights`, `report.{language,top_n,output_dir,timezone,app_name}`,
  `run.*`. City/price/plot/buyer data **removed** (they move to `profile.yaml`).
- **`profile.example.yaml`** committed template with comments.
- `.gitignore` += `profile.yaml`, `agent_instructions/*.local.md`.
- The `cities`, `price_*`, `property_type`, `preferred_plot_m2` that
  `orchestrate` / scoring / scrape consume now come from `Profile`, not `Config`.

### Phase 2 — Setup wizard + first-run gate
- **`run_setup.py`** (and `python -m scout setup`) — interactive Spanish wizard.
  Prompts for cities (name/coords/radius), price range, property type, plot
  preference, and buyer fields (household, priorities, investment, must-haves,
  deal-breakers, language, notes). Writes `profile.yaml`. Optionally seeds
  `agent_instructions/*.local.md` from the committed defaults.
- **First-run gate:** `run_daily.py` / `run_listener.py` detect missing
  `profile.yaml` → print "ejecuta `python -m scout setup`…" and exit non-zero.
  No pipeline run without a profile.

### Phase 3 — Reorg + rename (`chalet` → `scout`, `core/` + `providers/es/`)
- Move modules per §3. Rename package and every import.
- **`scout/core/registry.py`** — `PROVIDERS: dict[country][portal] -> ProviderBundle`.
  A `ProviderBundle` carries: `scrape` callable, `enrichers` list (added on top
  of core global osm/osrm), `regulatory` callables, `geocode_country` string,
  `portal_base`, and a `slug_for(city)` function.
- **`scout/providers/es/__init__.py`** registers the ES/Idealista bundle.
  `scout/providers/__init__.py` imports `es` so registration happens on import.
- `core.orchestrate` resolves `PROVIDERS[profile.country][profile.portal]` at
  startup and drives the pipeline through the bundle (provider-agnostic).
- Env vars renamed: `CHALET_DB_PATH`→`SCOUT_DB_PATH` (default `data/scout.db`),
  `CHALET_LOG_DIR`→`SCOUT_LOG_DIR`, `CHALET_ANALYST_MODEL`→`SCOUT_ANALYST_MODEL`,
  `CHALET_CHAT_MODEL`→`SCOUT_CHAT_MODEL`. External-service vars unchanged.
- `pyproject.toml`: project `property-scout`, package `scout`.
- Tests move: ES-specific under `tests/providers/es/`, rest under `tests/core/…`.

### Phase 4 — Externalize & genericize agent instructions
- **`agent_instructions/property_analyst.md`** and **`chat_agent.md`** —
  committed default templates holding the full instruction text with generic
  placeholders: `{cities}`, `{price_min}`, `{price_max}`, `{property_type}`,
  `{preferred_plot_m2}`, `{buyer_profile}`, `{response_language}`. **No hardcoded
  city names or buyer profile.**
- **`scout/core/analyse/prompt_builder.py`** — loads the instruction file
  (`*.local.md` override if present, else committed default), composes
  `{buyer_profile}` from `Profile.buyer`, and fills placeholders. Used by both
  the analyst and the chat agent.
- `property_analyst.py`: `_SYSTEM_PROMPT` removed; system prompt now built via
  `prompt_builder`. Output parsing (`_split_summary`) and payload shape
  (`RESUMEN:` + bullets, `max_completion_tokens`, `reasoning_effort`) **unchanged**.
  Model from `SCOUT_ANALYST_MODEL` (default `gpt-5.4-mini`), documented in
  `.env.example`.
- `chat_agent.py`: `_SYSTEM_TMPL` and the static help reply move to the
  instruction template / are built from configured cities. No hardcoded "pareja"
  or `/scout valencia` examples — examples derive from `profile.search.cities`.

### Phase 5 — Sweep remaining hardcoded values in `scout/`
Replace with config/profile/provider-driven values (inventory from audit):

| Location (old path) | Hardcoded value | Fix |
|---|---|---|
| `notify/telegram.py` | "Chalet Spain — Informe Diario", "…ciclo diario" | `config.report.app_name`; drop stale "Diario" |
| `scrape/idealista.py` | `CITY_SLUGS` (barcelona/valencia/girona → …-provincia) | per-city `portal_slug` (profile) or provider `slug_for(city)` |
| `scrape/idealista.py` | `_BASE = idealista.com` | provider `portal_base` |
| `scrape/idealista.py` | geocode `", España"` | `bundle.geocode_country` (from `profile.country`) |
| `scrape/idealista.py` | Nominatim `user_agent="chalet-spain-scout"` | generic app slug (`property-scout`) |
| `score/dimensions.py` | comment "Couple-weighted…" | neutral comment; amenity sub-weights stay as documented defaults |

### Phase 6 — Git history rewrite
- `git filter-repo --replace-text` mapping the owner's email address and
  the account-specific collector id → `***REDACTED***` across all history
  (the exact mapping lives in the implementation plan).
- Force-push `main` (and this branch after merge) to private origin. Local
  backup branch retained.

### Phase 7 — Docs (final step)
- Rewrite README, CLAUDE.md, PRD, ARCHITECTURE, FEATURES, docs/README index,
  prompt references for `property-scout`: generic framing, `core/providers`
  architecture, `profile.yaml` + wizard flow, `agent_instructions/`, ES as
  reference implementation, renamed env vars. No personal profile embedded.

---

## 5. Testing strategy
- **New code (TDD):** `profile.py` loader/validation, `prompt_builder` placeholder
  filling + `.local` override, `registry` resolution, setup-wizard file writing,
  first-run gate.
- **Refactors (keep green):** package rename and module moves update imports only;
  the 180 existing tests must stay green (relocated under `core/` vs `providers/es/`).
- Output-format regression: an analyst test asserts the `RESUMEN:` split and
  payload shape are unchanged after prompt externalization.

---

## 6. Risks & mitigations
- **Blast radius of rename + reorg** (touches ~all files/imports/tests) —
  mitigate by doing Phase 3 mechanically in one pass, running the suite after.
- **History rewrite is destructive/force-push** — local backup branch first;
  private single-user repo lowers coordination risk.
- **Over-engineering the provider registry** — keep it a minimal dict + bundle
  dataclass, not a plugin framework. Ship ES only.
- **Multi-country honesty** — Spanish enrichers stay ES-owned; "configurable"
  means clean extension points, not implemented second country.

---

## 7. Out of scope
- Second country/portal implementation.
- Multi-LLM-provider abstraction (OpenAI stays; model configurable via env).
- Changing scoring math, output format, or the enricher set.
- Making location amenity sub-weights user-configurable (kept as defaults).
