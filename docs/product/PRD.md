# Product Requirements Document — Housing Scout

**Version:** 2.0
**Date:** 2026-07-14 (originally 2026-06-03)
**Status:** Active

---

## 1. Problem Statement

Buying a house near a major city is a slow, noisy, high-stakes process. Listings appear and disappear daily across portal aggregators; manually evaluating each one across price fairness, commute time, transport links, flood risk, air quality, legal status, rental potential, and neighbourhood character is impractical. There is no tool that combines all of these signals into a single ranked shortlist tailored to one buyer's criteria.

---

## 2. Goal

Build a reusable, profile-driven scouting agent template that:

1. Fetches new listings from a real-estate portal for the user's configured cities (the shipped reference implementation targets **Idealista in Spain**).
2. Enriches each listing with objective third-party data (cadastre, OSM, OSRM, statistical medians, flood/wildfire/noise/air maps in the ES implementation).
3. Scores each listing across 8 configurable weighted dimensions.
4. Generates a qualitative AI analysis per listing, driven by the user's buyer profile.
5. Delivers a ranked Markdown report and Telegram property cards — weekly hands-off, plus on demand from Telegram (`/scout`).

The output is a curated shortlist, not a raw feed. The agent is personal infrastructure, not a hosted product — each user runs their own instance with their own profile.

---

## 3. Target User & Personalization

One household per instance. Everything that describes the buyer lives in the user's **gitignored `profile.yaml`** (created by the interactive wizard, `python -m scout setup`; hand-editable template: `profile.example.yaml`):

- `country` / `portal` — selects the provider bundle (shipped: `es` / `idealista`)
- `search.cities` — list of target cities with name, lat/lon, search radius (km), and optional portal slug override
- `search.price_min_eur` / `price_max_eur` — hard price bounds
- `search.property_type` — portal typology to target
- `search.preferred_plot_m2` — plot size at which the ranking bonus reaches full value
- `buyer.*` — free-form profile fed to the AI analyst and chat agent: household description, purpose, top priorities, investment angle/notes, must-haves, deal-breakers, response language, extra notes

No personal criteria are committed to the repository; the committed `config.yaml` holds mechanical parameters only.

---

## 4. Hard Constraints (from the profile)

| Parameter | Source |
|---|---|
| Property typology | ES implementation scrapes the portal's detached-house search and drops flats and semi-detached/terraced listings at parse time |
| Price range | `profile.search.price_min_eur` – `price_max_eur` |
| Cities + radius | `profile.search.cities` (each with its own radius) |
| Preferred plot | `profile.search.preferred_plot_m2` — a ranking bonus, not a filter |

Properties that fail a hard constraint (price out of range, outside the city radius) are dropped before enrichment.

---

## 5. Pipeline Stages

### 5.1 Scrape

- **Dispatch:** `scout/core/scrape/base.py::scrape_listings()` resolves the provider bundle registered for the profile's `(country, portal)` pair and calls its scrape function.
- **ES reference implementation:** Idealista search sorted newest-first, price bounds from the profile.
- **Transport:** Bright Data Scrapers collector (shipped default, `scrape.provider: brightdata`) — a pre-built collector crawls the search page and each listing's detail page behind Bright Data's DataDome unblocking, returning structured records. Fallback: ScrapeOps Proxy Aggregator (`bypass=datadome`) — a headless browser through a Spanish residential proxy.
- **Volume:** Configurable pages per city (`scrape.pages`, default 1; ~25–30 listings/page).
- **Filtering at parse time:** Drop flats (`_is_flat`). Drop semi-detached/terraced (`_is_attached`). Keep only rustic, independent, and standalone villa variants.
- **Plot extraction:** `_parse_plot_m2` mines plot size (m²) from listing description text.
- **Geocoding:** Nominatim (geopy) resolves lat/lon from address, biased by the bundle's `geocode_country`; falls back to municipality centroid.
- **Detail fetch (ScrapeOps fallback only):** For the top `details_limit` listings (default 5), one extra ScrapeOps request fetches the listing detail page to fill bathrooms and any missing bedrooms/plot. Gated by `scrape.fetch_details` flag (Bright Data records already carry full detail-page text).
- **Failure handling:** `ScrapingBlockedError` if a page returns zero listings.

### 5.2 Filter & Deduplicate

- Hard exclusion: price out of range, outside the city radius.
- Deduplication against the SQLite property store — listings already reported in a prior run are skipped in the report (they are still persisted for tracking).

### 5.3 Enrich

All enrichers run concurrently (`asyncio`) per listing. Each returns an `EnrichmentResult` dict merged into `EnrichedListing.enrichments`. Generic enrichers live in `scout/core/enrich/`; country-specific ones in `scout/providers/es/enrich/`.

| Enricher | Layer | Source | Key outputs |
|---|---|---|---|
| `osm` | core | OSM Overpass (5 km radius) | School/healthcare/supermarket/park/playground/transit counts; `nearest_station_km`, `nearest_school_km`, `nearest_health_km`, `nearest_motorway_km`, `municipality_population` |
| `osrm` | core | OSRM public routing | `drive_min` to city centre |
| `catastro` | es | Spanish Cadastral Registry (REST) | `use_code`, `year_built`, `urbanistic_class` |
| `ine` | es | `scout/providers/es/data/municipal_price_psqm.csv` | Zonal median price/m² |
| `neighbourhood` | es | `scout/providers/es/data/municipal_neighbourhood.csv` (INE Censo 2021 + VUT density) | `primary_residence_pct`, `investment_hits` |
| `flood` | es | SNCZI flood-zone API | `return_period` (none / T500 / T100 / T10) |
| `air` / `noise` / `wildfire` | es | `scout/providers/es/data/municipal_environment.csv` | `no2_avg` (µg/m³), `lden_db` (dB), `hazard_class` (1–5) |

### 5.4 Score

Eight independent 0–10 dimension scores, each clamped and null-safe. Composite = weighted sum, with weights from `config.yaml → scoring.weights` (must sum to 1.0). A bounded plot-size bonus (≤ +0.3) is added post-composition — full bonus at `profile.search.preferred_plot_m2`, linear ramp from half that size — without disturbing the weight model.

| Dimension | Shipped weight | Key signals |
|---|---|---|
| Location | 0.20 | Supermarkets (×2.5), healthcare (×2.0), parks, schools; municipality population tier |
| Price | 0.18 | Listing price/m² vs. zonal median; +1 bonus if > 90 days on market |
| Commute | 0.15 | Drive time to city centre (OSRM), nearest station ≤ 1.5 km, motorway access |
| Legal | 0.15 | Cadastral residential use classification, year built, urbanistic class |
| Environmental | 0.10 | Flood return period, wildfire hazard class, noise (Lden), NO₂ |
| Neighbourhood | 0.10 | Primary-residence %, schools, parks, commercial density, tourism-rental activity |
| Regulatory | 0.07 | Stressed-housing-zone flag, recent official-bulletin regulatory hit |
| Infrastructure | 0.05 | Transit proximity, nearest school/clinic walking distance, broadband |

The two regulatory inputs are sourced outside the per-listing enricher set: the stressed-zone flag comes from `scout/providers/es/regulatory/zonas_tensionadas.py` (static ZMRT lookup) and the bulletin hit from `scout/providers/es/regulatory/boe_alerts.py` (BOE/DOGC/DOGV RSS, fetched once per city run).

### 5.5 AI Analysis

- **Model:** `gpt-5.4-mini` with `reasoning_effort=low` (OpenAI API; override with `SCOUT_ANALYST_MODEL`).
- **Scope:** All new scored listings (not just top-N).
- **System prompt:** Built at runtime by `scout/core/analyse/prompt_builder.py` from the committed template `agent_instructions/property_analyst.md`, filling `{cities}`, `{price_min}`, `{price_max}`, `{property_type}`, `{preferred_plot_m2}`, `{buyer_profile}`, `{response_language}` from the profile. A gitignored `agent_instructions/property_analyst.local.md` override wins if present.
- **User prompt includes:** Listing details including plot size (`Parcela`, shown as `—` if unknown), composite score and dimension breakdown, description excerpt.
- **Output format:** Response in the profile's `response_language`, beginning with `RESUMEN:` (surfaced in Telegram) followed by a ~180-word qualitative assessment covering: connectivity and commute, residential character, plot size and usability, investment potential, price vs. market, pre-offer alerts.
- **Graceful degradation:** Skips silently if `OPENAI_API_KEY` absent.

### 5.6 Report

- **Format:** Jinja2-rendered Markdown, titled with `report.app_name` (default "Housing Scout").
- **Filename:** `data/reports/YYYY-MM-DD-{city}.md`
- **Content:** Top-N listings sorted by composite score (default 10 per city), with AI analysis summary per listing.
- **Language:** `report.language` in `config.yaml` (shipped: `es`).

### 5.7 Notify

- **Channel:** Telegram Bot HTML messages (header uses `report.app_name`).
- **Content:** Compact run-stats header (listings found, survived filters, new), then one property card per top-5 listing (price, size, plot, score bar, distance, AI `RESUMEN`) with an inline "Ver anuncio" button opening the listing; the Markdown report attached as a document.
- **Failure alerts:** On pipeline error, sends an error alert (secrets redacted from exception text).
- **Graceful degradation:** Skips silently if `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` absent.

### 5.8 On-demand runs & chat (Telegram)

- **`/scout` listener:** An always-on launchd process long-polls `getUpdates`; `/scout` from the authorised chat runs all cities, `/scout <city1> <city2>` a subset (case/accent-insensitive). A shared pidfile lock prevents overlap with the scheduled run — a `/scout` during a run answers "búsqueda en curso".
- **Chat agent:** Non-command messages get conversational replies (OpenAI `gpt-5-nano`, override `SCOUT_CHAT_MODEL`) built from `agent_instructions/chat_agent.md` + the profile, with run-in-progress awareness; without `OPENAI_API_KEY` a static help reply points at `/scout`.

### 5.9 Persist

- SQLite (`data/scout.db`, WAL mode, foreign keys on; override with `SCOUT_DB_PATH`).
- Schema managed via ordered migration strings in `scout/core/migrations.py` — idempotent on every startup.
- Tables: `properties` (canonical listing store), `scores`, `runs` (per-run metadata).
- `properties.reported_at` is stamped at report time so already-reported listings are skipped in future runs.

---

## 6. Multi-City Architecture

`orchestrate.run_once(cfg, profile, conn, paths)` runs one independent pipeline per city in `profile.search.cities` via `_run_city()`:

- Each city gets its own `run_id`, report file (`YYYY-MM-DD-{city}.md`), and Telegram message.
- A failure in one city does not abort the others.

---

## 7. First-Run Setup & Schedule

- **Setup gate:** `run_daily.py` and `run_listener.py` exit 2 with "Run: `python -m scout setup`" when no `profile.yaml` exists. The wizard interactively collects country, portal, cities, prices, and the buyer profile, and writes `profile.yaml`.
- **Schedule:** Weekly via macOS launchd (`scripts/com.housing-scout.daily.plist.template`, shipped for Tuesday 00:00 Europe/Madrid). Install with `bash scripts/install_launchd.sh`. On-demand runs are available any time via Telegram `/scout` (listener installed with `bash scripts/install_listener.sh`).

---

## 8. External Dependencies

| Dependency | Purpose | Required? |
|---|---|---|
| Bright Data Scrapers collector | Default scrape transport — structured portal records behind DataDome unblocking | Yes (shipped default; needs `BRIGHTDATA_API_KEY` + `BRIGHTDATA_COLLECTOR_ID`) |
| ScrapeOps Proxy Aggregator | Fallback scrape transport — HTML via DataDome bypass | Only if `scrape.provider: scrapeops` |
| Nominatim / geopy | Geocode listing addresses | Yes |
| OSM Overpass API | Amenity counts, distances | Yes |
| OSRM public API | Drive-time routing | Yes |
| Spanish Catastro REST | Legal/cadastral data (ES provider) | Yes (ES) |
| SNCZI REST | Flood zone classification (ES provider) | Yes (ES) |
| INE CSV files | Price/m², neighbourhood, environment data (ES provider) | Yes (bundled in `scout/providers/es/data/`) |
| OpenAI API | Qualitative AI analysis + chat agent | Optional |
| Telegram Bot API | Run notifications and on-demand runs | Optional |

---

## 9. Configuration Reference

Mechanical parameters live in `config.yaml`; personal criteria in `profile.yaml`. Key levers:

| Parameter | File | Default | Effect |
|---|---|---|---|
| `scrape.provider` | config | brightdata | Scrape transport: `brightdata` (collector API) or `scrapeops` (HTML proxy fallback) |
| `scrape.brightdata_collector_id` | config | — (env: `BRIGHTDATA_COLLECTOR_ID`) | Which Bright Data collector to trigger; the env var takes precedence |
| `scrape.pages` | config | 1 | Pages fetched per city per run (~25–30 listings each) |
| `scrape.fetch_details` | config | false (shipped) | Enable detail-page fetch for bathrooms (ScrapeOps fallback only; costs extra credits) |
| `scrape.details_limit` | config | 5 | How many top listings get a detail fetch (when enabled) |
| `report.top_n` | config | 10 | Listings shown in report and used for Telegram top-5 |
| `report.app_name` | config | Housing Scout | Branding in report title and Telegram headers |
| `scoring.weights.*` | config | see above | Per-dimension weight; must sum to 1.0 |
| `search.cities` | profile | — | Target cities (name, lat/lon, radius, optional portal slug) |
| `search.price_min_eur` / `price_max_eur` | profile | — | Hard price bounds |
| `search.preferred_plot_m2` | profile | 1000 | Plot size at which the composite bonus reaches full value |
| `buyer.*` | profile | — | Free-form buyer profile fed to the AI prompts |

---

## 10. Non-Goals

- No web UI or dashboard — output is Markdown files and Telegram messages.
- No multi-user support — single-owner personal tool; one profile per instance.
- No automated tourism-licence lookup — investment viability is assessed qualitatively by the AI analyst, not as a scored dimension.
- No price negotiation or offer automation.
- One portal per profile — the registry supports adding providers, but a run targets a single `(country, portal)` pair.
- No alerting on price drops for tracked properties (listings are skipped after first report).

---

## 11. Success Criteria

A run is successful if:

1. At least one portal page per city is fetched without `ScrapingBlockedError`.
2. At least one new listing survives filtering per city.
3. A Markdown report is written to `data/reports/`.
4. A Telegram message is sent (if configured).
5. The run is recorded in the `runs` table.

A run is a partial success if one city succeeds and another fails — outcomes are reported separately per city.

---

## 12. Out-of-Scope Risks

| Risk | Mitigation |
|---|---|
| The portal blocks the scrape transport (DataDome update, markup change) | Bright Data handles unblocking server-side (collector may need a Scraper Studio rebuild); ScrapeOps fallback rotates proxies/UA; `ScrapingBlockedError` is raised per city and a Telegram error alert is sent |
| Overpass / OSRM rate limits | Requests are sequential per listing; `asyncio` concurrency is across enrichers, not across listings |
| Bundled CSV staleness (ES) | CSV files are versioned in the repo; the user updates them manually when the sources publish new data |
| OpenAI API cost | Analysis is `reasoning_effort=low`; silently skipped if key absent |
