# Housing Scout — Feature Status

All implemented features in pipeline order. Each feature is marked `[x]` once shipped and passing tests.

---

## Phase 0 — Project Foundation

- [x] SQLite database with WAL mode and foreign keys on (`data/scout.db`, override `SCOUT_DB_PATH`)
- [x] Ordered migration system (`scout/core/migrations.py`) — idempotent, append-only
- [x] `Listing`, `EnrichedListing`, `ScoredListing` dataclasses (`scout/core/models.py`)
- [x] Config loading from `config.yaml` (`scout/core/config.py`) — mechanical params: scrape provider/pages, report language/top-N/`app_name`, scoring weights, schedule
- [x] Structured logging via `structlog` (`scout/core/logging_setup.py`)
- [x] `launchd` scheduler script for macOS (`scripts/install_launchd.sh`) — weekly, Tuesday 00:00 Europe/Madrid as shipped

---

## Phase 1 — Filter Layer

- [x] Hard exclusion rules: price out of the profile's range, distance from city centre, description-pattern filters (ocupas, nuda propiedad, litigious, restricted title) (`scout/core/filter/hard_excl.py`)
- [x] Property deduplication — insert/upsert and cross-run dedup (`scout/core/filter/persist.py`, `scout/core/filter/dedup.py`)
- [x] `properties.reported_at` stamp — already-reported listings skipped in future runs

---

## Phase 2 — Scrape Layer (ES / Idealista reference provider)

- [x] Idealista scraper via Bright Data Scrapers collector — default transport (`scrape.provider: brightdata`); detail-page crawl with structured records, renewable 5,000-credit/month free tier; collector id via `BRIGHTDATA_COLLECTOR_ID` env var or `scrape.brightdata_collector_id` (`scout/providers/es/scrape/brightdata.py`)
- [x] Idealista scraper via ScrapeOps Proxy Aggregator — config-selectable fallback (`scrape.provider: scrapeops`); DataDome bypass via Spanish residential proxy + headless browser (`scout/providers/es/scrape/idealista.py`)
- [x] Search URL targets the detached-house typology, sorted by newest first (`orden=publicado-desc`) — avoids repeated promoted listings; price bounds from the profile
- [x] Pages-based scrape control (`scrape.pages` in config, ~25–30 listings per page)
- [x] Property type filtering — keeps detached/independent houses, rustic, standalone villas; drops flats (`_is_flat`) and semi-detached/terraced (`_is_attached`: pareado/adosado)
- [x] Plot size extraction from listing description (`_parse_plot_m2`)
- [x] Detail-page fetch for top-N listings — fills bathrooms and missing bedrooms/plot via `_fill_top_details()` / `fetch_listing_details()` (gated by `scrape.fetch_details`, default top 5)
- [x] Geocoding via Nominatim (geopy, user agent `housing-scout`, country from the bundle's `geocode_country`) — resolves lat/lon from address, falls back to municipality (`_geocode_listings`)
- [x] `ScrapingBlockedError` raised when a page yields no listings
- [x] Manual scrape test script — no DB write (`scripts/manual_scrape.py`)

---

## Phase 3 — Enrichment Layer

All enrichers are async `(EnrichedListing, httpx.AsyncClient) → EnrichmentResult` and run concurrently via `run_enrichers()` (`scout/core/enrich/base.py`). Generic enrichers live in `scout/core/enrich/`, Spain-specific ones in `scout/providers/es/enrich/`.

- [x] **OSM** (core) — OpenStreetMap Overpass: amenities within 5 km (schools, kindergartens, healthcare, supermarkets, parks, playgrounds, transit stations); computes `nearest_station_km`, `nearest_school_km`, `nearest_health_km`, `healthcare_total`, `nearest_motorway_km`, `municipality_population` (`scout/core/enrich/osm.py`)
- [x] **OSRM** (core) — drive-time to the profile's city centres (`scout/core/enrich/osrm.py`)
- [x] **Catastro** (es) — Spanish cadastral registry lookup (`scout/providers/es/enrich/catastro.py`)
- [x] **INE** (es) — zonal median price per m² from `scout/providers/es/data/municipal_price_psqm.csv` (`scout/providers/es/enrich/ine.py`)
- [x] **Neighbourhood** (es) — INE Censo 2021 primary-residence % + regional VUT (tourism-rental) density from `scout/providers/es/data/municipal_neighbourhood.csv`; derives `primary_residence_pct` and `investment_hits` (`scout/providers/es/enrich/neighbourhood.py`)
- [x] **Flood** (es) — SNCZI flood-zone classification (`scout/providers/es/enrich/sncziflood.py`)
- [x] **Air / Noise / Wildfire** (es) — per-municipality NO₂ (µg/m³), Lden (dB), and wildfire hazard class from `scout/providers/es/data/municipal_environment.csv` (`scout/providers/es/enrich/environment.py`)

---

## Phase 3b — Regulatory Signal Providers (ES)

These are not enrichers — they produce direct inputs to `score_regulatory` rather than `EnrichmentResult` objects. They live in `scout/providers/es/regulatory/`.

- [x] **Zonas Tensionadas lookup** — static frozenset of ~140 Catalan ZMRT municipalities; `is_tensionada(municipality)` returns bool (`scout/providers/es/regulatory/zonas_tensionadas.py`)
- [x] **BOE/DOGC/DOGV RSS monitor** — fetches housing-related items from official bulletin feeds (BOE, Catalan DOGC, Valencian DOGV); `fetch_alerts()` filters by housing keyword regex (`scout/providers/es/regulatory/boe_alerts.py`)

---

## Phase 4 — Scoring Engine

- [x] 8 independent 0–10 dimension scores (`scout/core/score/dimensions.py`):
  - `score_commute` — OSRM drive-time to city centre, station ≤ 1.5 km, motorway access
  - `score_price` — vs. zonal median
  - `score_legal` — catastro validity, title risk
  - `score_location` — urban livability: shops/parks/healthcare/schools; municipality population tier
  - `score_environmental` — flood zone, wildfire hazard, noise (Lden), NO₂
  - `score_neighbourhood` — primary-residence %, commercial density, school/park density, tourism-rental activity
  - `score_regulatory` — `in_tensa` (zonas tensionadas) + `recent_boe_hit` (BOE alerts)
  - `score_infrastructure` — transit proximity, nearest school/clinic walking distance, broadband
- [x] Composite score via weighted sum (`scout/core/score/compose.py`) — weights passed from `config.yaml` (single source of truth since 2026-07-07); shipped: location 0.20, price 0.18, commute 0.15, legal 0.15, environmental 0.10, neighbourhood 0.10, regulatory 0.07, infrastructure 0.05
- [x] Plot-size preference bonus (`dim.plot_bonus`, ≤ +0.3) — full bonus at `profile.search.preferred_plot_m2` (profile default 1 000 m²), linear ramp from half that size; unknown plots not penalised

---

## Phase 5 — Report Renderer

- [x] Jinja2-rendered Markdown report — top-N listings sorted by composite score, titled with `report.app_name` (`scout/core/report/markdown.py`)
- [x] Per-city report files: `data/reports/YYYY-MM-DD-{city}.md`

---

## Phase 6 — Orchestration

- [x] `scout/core/orchestrate.py::run_once(cfg, profile, conn, paths)` — one independent pipeline per target city via `_run_city()`; one city failing does not abort the others
- [x] Per-city `run_id` and `runs` table — every run recorded in DB
- [x] `scores` table — per-listing scored output persisted after each run
- [x] API key redaction from exception logs and Telegram alerts (security)

---

## Phase 7 — Notifications

- [x] Telegram bot notifier — compact HTML run-stats header (uses `report.app_name`) + one property card per top-5 listing (price, size, plot, score bar, distance, AI resumen) with inline "Ver anuncio" URL button (`scout/core/notify/telegram.py`)
- [x] Markdown report attached as a Telegram document (archive copy)
- [x] Telegram failure alert on pipeline error
- [x] Silently skipped when `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` absent

---

## Phase 8 — AI Analyst

- [x] **Property AI Analyst** (`scout/core/analyse/property_analyst.py`) — calls `gpt-5.4-mini` (reasoning, `reasoning_effort=low`) via OpenAI API concurrently for **all new scored listings** (not just top-N): `analyse_top(scored, profile)`
- [x] System prompt built from the `agent_instructions/property_analyst.md` template + the buyer's profile (see Phase 10)
- [x] Prompt includes plot size (`Parcela`, shown as `—` when unknown)
- [x] Output: leading `SUMMARY:` paragraph (`RESUMEN:` in the Spanish backup template, surfaced per-property in Telegram) + ~180-word qualitative assessment in the profile's response language covering: connectivity, residential character, plot usability, investment potential, price vs. market, and pre-offer alerts
- [x] Silently skipped when `OPENAI_API_KEY` absent

---

## Phase 9 — On-Demand Runs & Chat (2026-07-07)

- [x] Telegram `/scout` listener — long-polls `getUpdates`; on-demand pipeline runs from the authorised chat (`scout/core/notify/listener.py`, entry point `run_listener.py`)
- [x] Flexible city selection — `/scout` runs all cities; `/scout <city1> <city2>` (space/comma, case/accent-insensitive) runs a subset; unknown cities get a help reply
- [x] Cross-process pidfile lock — scheduled and on-demand runs never overlap; concurrent `/scout` answers "búsqueda en curso" (`scout/core/runlock.py`)
- [x] Offset persistence (`data/telegram_listener.offset`) — restarts never replay processed updates
- [x] Always-on launchd KeepAlive installer (`scripts/install_listener.sh`)
- [x] Conversational chat agent — `gpt-5-nano` (override: `SCOUT_CHAT_MODEL`) answers plain chat messages with project context and run-in-progress awareness; degrades to a static help reply without `OPENAI_API_KEY` (`scout/core/notify/chat_agent.py`, `ChatAgent(profile=...)`)
- [x] Model overrides — `SCOUT_ANALYST_MODEL` (default `gpt-5.4-mini`) and `SCOUT_CHAT_MODEL` (default `gpt-5-nano`)

---

## Phase 10 — Genericize & Personalize (2026-07-13/14)

- [x] Package renamed to `scout` and split into `scout/core/` (agnostic pipeline) + `scout/providers/es/` (Spain / Idealista reference implementation)
- [x] Provider registry (`scout/core/registry.py`) — `ProviderBundle`, `register`, `resolve(country, portal)`; ES bundle registered in `scout/providers/es/__init__.py`; `scout/core/scrape/base.py::scrape_listings()` dispatches scraping through it
- [x] Personal criteria moved to gitignored `profile.yaml` (`scout/core/profile.py`: `Profile`/`ProfileSearch`/`ProfileCity`/`ProfileBuyer`); committed template `profile.example.yaml`; `config.yaml` reduced to mechanical params
- [x] Interactive setup wizard (`scout/core/setup_wizard.py`, `python -m scout setup` / `run_setup.py`) — writes `profile.yaml`
- [x] First-run gate — `run_daily.py` / `run_listener.py` exit 2 with "Run: python -m scout setup" when no profile exists; entry points take `--profile` (and `--config`)
- [x] AI prompts externalized to committed generic templates `agent_instructions/property_analyst.md` + `chat_agent.md` with profile placeholders; gitignored `*.local.md` overrides win; builder `scout/core/analyse/prompt_builder.py` (`build_system_prompt`, `compose_buyer_profile`); analyst output contract unchanged (`SUMMARY:`/`RESUMEN:` + ~180-word analysis)
- [x] Env vars renamed: `SCOUT_DB_PATH` (default `data/scout.db`), `SCOUT_LOG_DIR`, `SCOUT_ANALYST_MODEL`, `SCOUT_CHAT_MODEL`; external-service vars unchanged
- [x] Branding via `config.yaml → report.app_name` (default "Housing Scout") in Telegram headers and report title; Nominatim user agent `housing-scout`; geocode country from the provider bundle

---

## Known Bugs (not yet fixed)

> See `docs/planning/ROADMAP.md` Part 2 for full details and fix recipes (paths there predate the `scout/` split).

- [ ] `province=None` always set on `Listing` — INE, neighbourhood, and environment enrichers silently bail; `score_price` always `None` (`scout/providers/es/scrape/idealista.py`)
- [ ] `broadband` enricher referenced in `score_infrastructure` but never registered — broadband sub-score is always the constant `5` (`scout/core/score/dimensions.py`)
- [ ] `or` short-circuit in `_nearest_station_km` returns wrong distance when nearest station is exactly 0.0 km (`scout/core/enrich/osm.py`)
- [ ] Enrichment loop is sequential per listing — listings enriched one-by-one instead of concurrently (`scout/core/orchestrate.py::_run_city`)
- [ ] `_fill_top_details` mutates `plot_m2` after scoring — persisted composite score is stale (`scout/core/orchestrate.py`)
- [ ] `migrate()` uses `executescript` (non-atomic) — failed migration leaves schema half-applied (`scout/core/db.py`)
- [ ] `score_infrastructure` falls back to hardcoded constants (transit=3, health=4) when distance data absent — fabricated scores instead of `None` (`scout/core/score/dimensions.py`)
- [x] ~~`compose.py` has hardcoded `WEIGHTS` dict — `config.yaml` scoring weight changes are silently ignored at runtime~~ — **fixed 2026-07-07**: `composite(scores, weights)` receives the config weights from `orchestrate._run_city`

---

## Planned Features (not yet built)

> See `docs/planning/ROADMAP.md` Part 3 for the full prioritised roadmap.

- [ ] Route the ES enrichers/regulatory inputs through `ProviderBundle.enrichers`/`regulatory` (drop the direct `scout.providers.es.*` imports in `orchestrate.py`)
- [ ] Min-bedrooms hard filter (`search.min_bedrooms` in the profile, `scout/core/filter/hard_excl.py`)
- [ ] Expand the ES CSV seeds from 9 → ~40 municipalities (full commuter belts)
- [x] ~~Plot size on Telegram card~~ — **shipped 2026-07-07** with the per-property cards
- [ ] Google Maps + Catastro deep-links on Telegram card
- [ ] Fix hardcoded `zone_class`/`market_context` stub in report
- [ ] Persist AI analyst output to DB (`summary_md`, `analyst_md`)
- [ ] Price-drop tracking — detect and alert when a listed price falls
- [ ] Re-surface price-dropped past listings
- [ ] Persistent geocoding cache (SQLite)
- [ ] Automated CSV refresh script for the ES data seeds
- [x] ~~Move `boe_alerts.py` + `zonas_tensionadas.py` into a `regulatory/` package~~ — **shipped 2026-07-13** as `scout/providers/es/regulatory/`
- [ ] Second portal scraper (e.g. Fotocasa) as a new provider bundle
- [ ] Point-level noise/air WMS enrichers (replace municipal CSV averages)
- [ ] Interactive Telegram bot (`/top`, `/view`, `/history` commands) — first slice (`/scout` + chat agent) shipped 2026-07-07 as Phase 9
