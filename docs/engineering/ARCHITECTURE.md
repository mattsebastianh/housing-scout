# Architecture — Housing Scout

_Last updated: 2026-07-14 (genericize-and-personalize refactor: package renamed to `scout` and split into `scout/core/` + `scout/providers/es/` with a provider registry; personal criteria moved to gitignored `profile.yaml` + setup wizard; AI prompts externalized to `agent_instructions/`; env vars renamed to `SCOUT_*`; DB default `data/scout.db`; 196 tests)_

Pipeline internals, tech stack, current status, known issues, and next steps.

---

## Scope & goals

**Goal:** A reusable, profile-driven property-scouting agent template. It scrapes
a real-estate portal, enriches listings from public data, scores them across 8
weighted dimensions, runs an AI analyst per listing, and delivers ranked results
via Telegram + Markdown report. Runs weekly via launchd and on demand from
Telegram (`/scout`).

All personal search criteria — country, portal, target cities (with lat/lon and
radius), price range, property type, preferred plot size, and the free-form
buyer profile — live in the user's **gitignored `profile.yaml`**
(`scout/core/profile.py`; created by the interactive wizard, `python -m scout
setup`). The committed `config.yaml` carries mechanical knobs only (scrape
provider/pages, report language/top-N/`app_name`, scoring weights, schedule).
The shipped reference implementation is **Spain / Idealista**
(`scout/providers/es/`).

---

## Package layout: core + providers

- **`scout/core/`** — country/portal-agnostic (today the registry abstracts
  scraping only — enrichers/regulatory are still wired directly; see the
  caveat below): `orchestrate.py`, `models.py`,
  `db.py`, `migrations.py`, `config.py`, `profile.py`, `registry.py`,
  `setup_wizard.py`, `logging_setup.py`, `runlock.py`, `utils.py`, and the
  subpackages `filter/`, `score/`, `report/`, `notify/`, `analyse/`
  (+ `prompt_builder.py`), `scrape/` (`base.py` dispatch), `enrich/`
  (`base.py`, `osm.py`, `osrm.py`).
- **`scout/providers/es/`** — Spain / Idealista reference implementation:
  `scrape/` (`brightdata.py`, `idealista.py`), `enrich/` (`catastro.py`,
  `ine.py`, `neighbourhood.py`, `sncziflood.py`, `environment.py`),
  `regulatory/` (`boe_alerts.py`, `zonas_tensionadas.py`), and `data/`
  (bundled CSVs).

**Provider registry** (`scout/core/registry.py`): `ProviderBundle` packages a
portal's scrape callable plus `geocode_country`, `portal_base` and a `slug_for`
city→slug mapping (and reserves `enrichers`/`regulatory` dicts for future
routing). `scout/providers/es/__init__.py` registers the ES bundle under
`("es", "idealista")` on import of `scout.providers`.
`scout/core/scrape/base.py::scrape_listings(cfg, profile, city_name)` resolves
the bundle from the profile's `country`/`portal` and dispatches, so the core
pipeline never imports a portal by name for scraping. Caveat: the ES enrichers
and regulatory inputs are still imported directly in `orchestrate.py` — moving
them behind the bundle fields is future work.

---

## Pipeline

`run_once(cfg, profile, conn, paths)` runs **one independent pipeline per
target city** (`_run_city()`): each city gets its own `run_id`, report
(`YYYY-MM-DD-{city}.md`) and Telegram message; one city failing does not abort
the others. Each city pipeline runs these stages:

1. **Scrape** (`scout/core/scrape/base.py` → `scout/providers/es/scrape/`) —
   two config-selectable transports via `scrape.provider` (shipped default
   **brightdata** since 2026-07-07):
   - **brightdata** (`brightdata.py`) — triggers a pre-built **Bright Data
     Scrapers collector** (`BRIGHTDATA_COLLECTOR_ID` env var, or
     `scrape.brightdata_collector_id` in config.yaml; built in Scraper
     Studio) that crawls the search page *and* each listing's detail page
     behind Bright Data's DataDome unblocking, then polls the dataset API
     (~2 min per job) and maps the structured records to `Listing`s. Full
     detail-page descriptions make bathroom/plot mining more reliable and
     make the ScrapeOps detail-page fetch unnecessary. Costs 1 credit per
     record against the renewable 5,000/month free tier (~30 records per
     city page). Requires `BRIGHTDATA_API_KEY`.
   - **scrapeops** (`idealista.py`, fallback) — fetches Idealista search
   pages through the **ScrapeOps Proxy Aggregator** (`bypass=datadome`), which
   runs a headless browser through a Spanish residential proxy to clear
   Idealista's **DataDome** bot protection.
   Price bounds come from the profile; the portal slug comes from the city's
   `portal_slug` override or the bundle's `slug_for` mapping. Fetches exactly
   **`scrape.pages`** pages per city (default 1; each page yields ~25–30
   listings before typology filtering). Results are **sorted by newest first**
   (`?orden=publicado-desc`) to avoid promoted listings repeating across runs.
   Pagination follows the next-page link with a `delay_ms` gap between pages.
   **Typology filter** at parse time keeps only detached/independent houses,
   rustic properties and standalone villas — flats and **semi-detached
   (pareado) / terraced (adosado)** listings are dropped. **Plot size** (m²)
   is mined from the description text into `Listing.plot_m2`. Result cards
   often omit bathrooms, so the top `scrape.details_limit` reported listings
   (default 5) get a detail-page fetch (`fetch_listing_details`, gated by
   `scrape.fetch_details`) to fill bathrooms / missing bedrooms / plot.
   Coordinates are geocoded from each listing's address via **Nominatim/geopy**
   (user agent `housing-scout`, country biased by the bundle's
   `geocode_country`; municipality fallback, since Idealista list pages carry
   no coordinates). Raises `ScrapingBlockedError` when a page yields nothing.

   Both transports share the typology filters, plot/bathroom mining regexes,
   geocoding and `ScrapingBlockedError` (defined in `idealista.py`), so the
   downstream pipeline is transport-agnostic.

2. **Filter** (`scout/core/filter/`) — Hard exclusions (`hard_excl.py`: price
   out of the profile's range, outside the city radius), raw insert/upsert +
   property dedup (`persist.py`, `dedup.py`). Survivors continue.

3. **Enrich** (`scout/core/enrich/` + `scout/providers/es/enrich/`) — Async
   enrichers run concurrently per listing (`run_enrichers()` in
   `scout/core/enrich/base.py`):
   - `osm` (core) — Overpass amenities within 5 km (schools, kindergartens,
     healthcare, supermarkets, parks, playgrounds, transit); nearest distances
     and counts; also nearest motorway junction and the municipality population
     (place node)
   - `osrm` (core) — drive time to the profile's city centres
   - `catastro` (es) — Spanish cadastral registry lookup
   - `ine` (es) — zonal median €/m² from `scout/providers/es/data/municipal_price_psqm.csv`
   - `neighbourhood` (es) — primary-residence % + tourism-rental (VUT) density from
     `scout/providers/es/data/municipal_neighbourhood.csv`; yields
     `primary_residence_pct` and `investment_hits`
   - `flood` (es) — SNCZI flood-zone classification
   - `environment` (es: `air` / `noise` / `wildfire`) — per-municipality NO₂, Lden
     and wildfire hazard class from
     `scout/providers/es/data/municipal_environment.csv`; feeds the
     environmental score alongside flood

   Two regulatory inputs are **not** per-listing enrichers and live in
   `scout/providers/es/regulatory/`: `boe_alerts.py` fetches BOE/DOGC/DOGV RSS
   feeds once per city run (`recent_boe_hit` flag), and `zonas_tensionadas.py`
   is a static ZMRT lookup (`is_tensionada`). Both are consumed directly in
   `_run_city()` / `_score_property()` and feed the regulatory score.

4. **Score** (`scout/core/score/`) — 8 independent 0–10 dimensions
   (`dimensions.py`) combined into a weighted composite (`compose.py`, which
   receives the weights from `config.yaml → scoring.weights` — the single
   source of truth since 2026-07-07). Shipped weights: location 0.20 · price
   0.18 · commute 0.15 · legal 0.15 · environmental 0.10 · neighbourhood 0.10 ·
   regulatory 0.07 · infrastructure 0.05. Location is the top-weighted
   dimension (amenity weights favour shops/parks — everyday urban livability —
   over a school-dominant weighting); commute keeps a tight station threshold
   (≤ 1.5 km for full score). A small bounded **plot-size preference** bonus
   (`dim.plot_bonus`, ≤ +0.3) nudges ranking for plots approaching
   `profile.search.preferred_plot_m2` (profile default 1 000 m², linear ramp
   from half that size); unknown plots are never penalised.

5. **Analyse** (`scout/core/analyse/property_analyst.py`) — `gpt-5.4-mini`
   (reasoning, `reasoning_effort=low`; override `SCOUT_ANALYST_MODEL`) via
   OpenAI, run concurrently on **all new scored listings** (not just top-N):
   `analyse_top(scored, profile)`. The system prompt is built by
   `prompt_builder.build_system_prompt("property_analyst", profile)` from the
   committed template `agent_instructions/property_analyst.md` (gitignored
   `*.local.md` override wins), filling `{cities}`, `{price_min}`,
   `{price_max}`, `{property_type}`, `{preferred_plot_m2}`, `{buyer_profile}`
   and `{response_language}` from the profile — no personal literals in code.
   Each per-property prompt includes `Parcela` (plot size in m², shown as `—`
   when unknown). Produces a leading `SUMMARY:` paragraph (`RESUMEN:` in the Spanish backup template, used in Telegram)
   plus a ~180-word qualitative assessment in the profile's response language
   covering connectivity/commute, residential character, plot usability,
   investment potential, price vs. market, and pre-offer alerts. Skipped
   silently if `OPENAI_API_KEY` is absent.

6. **Report** (`scout/core/report/`) — Jinja2-rendered clean Markdown
   (`markdown.py`, `templates/daily.md.j2`), titled with `cfg.report.app_name`
   (default "Housing Scout"): plain headings + bullet lists, no emoji or bar
   graphics. Output: one file per city, `data/reports/YYYY-MM-DD-{city}.md`.

7. **Notify** (`scout/core/notify/telegram.py`) — compact HTML run-stats header
   (uses `cfg.report.app_name`), then one property card per top-5 listing
   (price, size, plot, score bar, distance, AI resumen) each with an inline
   **"Ver anuncio"** URL button, plus the Markdown report as a document
   attachment. Sends a failure alert on exception. Skipped silently if
   Telegram creds are absent.

8. **Persist** — Every run recorded in `runs`; per-listing scores in `scores`;
   `properties.reported_at` stamped so reported listings aren't repeated.

### Entry points & first-run gate

`run_daily.py` (`--check`, `--city`, `--config`, `--profile`) and
`run_listener.py` (`--profile`) both **exit 2 with "Run: python -m scout
setup"** when no `profile.yaml` exists. The wizard (`scout/core/setup_wizard.py`,
entry points `python -m scout setup` / `run_setup.py`) interactively builds a
`Profile` and writes `profile.yaml`; `profile.example.yaml` is the committed
hand-editable template. `--city` filters the profile's cities (unknown names
are rejected with the configured list).

### On-demand entry point (Telegram listener)

Besides the weekly launchd schedule, `scout/core/notify/listener.py` (entry
point `run_listener.py`, installed as an always-on KeepAlive launchd job via
`scripts/install_listener.sh`) long-polls `getUpdates` and, on a `/scout`
message from the authorised `TELEGRAM_CHAT_ID`, launches the pipeline as a
`run_daily.py --city …` subprocess. `/scout` alone runs all configured cities;
`/scout <city1> <city2>` (space/comma, case/accent-insensitive) runs a subset;
unknown cities get a help reply. The last `update_id` persists in
`data/telegram_listener.offset`; a shared pidfile lock (`scout/core/runlock.py`,
`data/run.lock`, acquired by `run_daily.py` itself) guarantees manual and
scheduled runs never overlap. Non-command messages are answered by a
conversational **chat agent** (`scout/core/notify/chat_agent.py`,
`ChatAgent(profile=...)`, OpenAI `gpt-5-nano`, `SCOUT_CHAT_MODEL` override)
whose system prompt is built from `agent_instructions/chat_agent.md` + the
profile; it degrades to a static `/scout` help reply without `OPENAI_API_KEY`.

---

## Tech stack

- **Python 3.13** (requires ≥3.11), venv at `.venv`
- **httpx** + **asyncio** — async HTTP and concurrent enrichment/analysis
- **BeautifulSoup4** parsing · **geopy** geocoding · **tenacity** retries
- **pydantic** + **pyyaml** — config (`config.yaml`) and profile (`profile.yaml`) models
- **structlog** JSON logging · **Jinja2** Markdown reports
- **SQLite** (WAL, FK on) at `data/scout.db` (override: `SCOUT_DB_PATH`);
  schema via ordered migration strings in `scout/core/migrations.py` —
  `db.migrate()` is idempotent on every startup
- **pytest** + pytest-asyncio + respx + pytest-cov (`[dev]` extras)
- **External services (ES provider):** Bright Data (default scrape transport) ·
  ScrapeOps (fallback) · OpenAI · Telegram · Nominatim / Overpass / OSRM /
  Catastro / SNCZI (free public APIs) · INE (bundled CSV)

---

## Key files

| Path | Purpose |
|---|---|
| `profile.yaml` (gitignored) | Personal search profile — cities, prices, buyer preferences |
| `profile.example.yaml` | Committed template for `profile.yaml` |
| `config.yaml` | Mechanical params (provider, pages, report, weights, schedule) |
| `agent_instructions/` | AI prompt templates (`property_analyst.md`, `chat_agent.md`); gitignored `*.local.md` overrides |
| `scout/core/orchestrate.py` | Main pipeline `run_once(cfg, profile, conn, paths)` |
| `scout/core/registry.py` | `ProviderBundle` + `register`/`resolve(country, portal)` |
| `scout/core/scrape/base.py` | Provider-agnostic scrape dispatch |
| `scout/core/profile.py` | Profile models + `load_profile`/`profile_exists` |
| `scout/core/setup_wizard.py` | Interactive wizard → `profile.yaml` |
| `scout/core/models.py` | `Listing`, `EnrichedListing`, `ScoredListing` |
| `scout/core/migrations.py` | SQLite DDL (append-only migration list) |
| `scout/core/enrich/` | Generic enrichers: osm, osrm (+ async runner `base.py`) |
| `scout/core/score/dimensions.py` + `compose.py` | 8 dimensions + composite |
| `scout/core/analyse/property_analyst.py` + `prompt_builder.py` | AI analyst + profile-driven prompt builder |
| `scout/core/report/markdown.py` + `templates/` | Markdown report renderer |
| `scout/core/notify/telegram.py` | Telegram notifier (stats header + property cards) |
| `scout/core/notify/listener.py` | Telegram `/scout` listener — on-demand runs |
| `scout/core/notify/chat_agent.py` | Conversational chat agent |
| `scout/core/runlock.py` | Cross-process pidfile lock (scheduled vs. on-demand) |
| `scout/providers/es/__init__.py` | Registers the Spain / Idealista bundle |
| `scout/providers/es/scrape/brightdata.py` | Bright Data collector client (default transport) |
| `scout/providers/es/scrape/idealista.py` | ScrapeOps scraper + parser + geocoding (fallback; shared helpers) |
| `scout/providers/es/enrich/` | catastro, ine, neighbourhood, sncziflood, environment |
| `scout/providers/es/regulatory/` | boe_alerts + zonas_tensionadas (regulatory inputs) |
| `scout/providers/es/data/` | Bundled CSVs: median €/m², neighbourhood, environment |
| `run_daily.py` / `run_listener.py` / `run_setup.py` | Entry points (all profile-aware) |
| `data/scout.db` | SQLite state — copy when migrating machines |

---

## Current status

- All **196 tests pass** (`python -m pytest -q`)
- **Genericize & personalize refactor** (2026-07-13/14): package renamed
  `scout`, split into `core/` + `providers/es/` with a provider registry;
  personal criteria moved out of committed files into gitignored
  `profile.yaml` (+ wizard and first-run gate); AI prompts externalized to
  `agent_instructions/` templates with profile placeholders and `.local.md`
  overrides; env vars renamed to `SCOUT_*`; report/Telegram branding via
  `report.app_name`.
- Scrape transport **migrated to Bright Data** (2026-07-07, default;
  ZenRows → ScrapeOps → Bright Data) — verified live. ScrapeOps remains the
  config-selectable fallback.
- **On-demand `/scout` runs + chat agent shipped** (2026-07-07): always-on
  Telegram listener, flexible city selection, cross-process run lock,
  per-property Telegram cards with inline listing buttons.
- **Pre-public-release hardening** (2026-07-13): security audit (no code
  vulnerabilities), MIT license, account-specific collector id moved to the
  `BRIGHTDATA_COLLECTOR_ID` env var.
- Reports are **Markdown-only** (PDF generation removed 2026-05-29)

---

## Known issues & fragility

- **ES enrichers/regulatory not yet behind the registry.** `orchestrate.py`
  imports `scout.providers.es.*` directly for catastro/ine/neighbourhood/
  flood/environment and boe_alerts/zonas_tensionadas; `ProviderBundle` has
  `enrichers`/`regulatory` fields reserved for routing them. A second country
  provider requires that routing work first.

- **Scoring inputs are data-backed** (no hardcoded stubs left in
  `_score_property()`): `municipality_population` (OSM place-node population tag,
  fallback 50 000), `motorway_km` (nearest OSM motorway_junction), `in_tensa`
  (Catalan ZMRT static set), `urbanistic_class` (Catastro cadastral class: rústica
  → "no urbanizable", urbana → "urbano"), and `primary_residence_pct` /
  `investment_hits` (the `neighbourhood` enricher — see below). Note
  `urbanistic_class` resolves whenever Catastro returns a parcel — either from the
  listing's `cadastral_ref` or, when absent, from its coordinates via the WFS
  lookup.

- **`neighbourhood` enricher is a 9-municipality CSV seed, not live.**
  `scout/providers/es/data/municipal_neighbourhood.csv` carries
  `primary_residence_pct` (INE Censo 2021 viviendas principales) and
  `vut_per_1000_dwellings` (Catalunya RTC/HUT + CV VUT registries) for the same
  9 municipalities as the price CSV. `investment_hits` is derived as
  `min(5, vut_per_1000 // 5)`. Listings outside those 9 municipalities get no
  neighbourhood data (fails soft: `primary_residence_pct=None`,
  `investment_hits=0`). Refresh path: re-pull the INE census dwelling-type table
  and the regional tourism registries (MiraTuZona was evaluated and rejected: no
  API, Cloudflare-gated, paywalls the granular data, and is itself just a wrapper
  over these same INE/Interior/MITECO sources).

- **`environment` enricher (air/noise/wildfire) is a 9-municipality CSV seed.**
  `scout/providers/es/data/municipal_environment.csv` carries representative
  residential NO₂ (MITECO/EEA stations), Lden (MITECO END strategic noise maps)
  and a wildfire hazard class (Catalan DECRET 64/1995 + CV forest-interface) per
  municipality. These are hyper-local phenomena reduced to a municipal figure, so
  they're approximate; listings outside the seed set emit no key and
  `score_environmental` simply renormalises over the factors present (flood
  always available). Upgrade path: point-level WMS GetFeatureInfo (like `flood`)
  for noise, and a coordinate air-quality API for NO₂.

- **Catastro coordinate lookup is best-effort.** When a listing has no
  `cadastral_ref`, `enrich_catastro` resolves one from its lat/lon via the INSPIRE
  WFS (~10 m bbox). This depends on geocoding accuracy — a municipality-centroid
  fallback (see Geocoding note) or a point landing on a road/gap returns no parcel,
  so Catastro fails soft for that listing (no `legal` penalty). It also picks the
  *first* parcel in the bbox, which near boundaries may not be the exact building.

- **Overpass rate-limiting.** The free OSM Overpass API returns 429/504 on busy
  days. `enrich_osm` retries 429/5xx/timeouts with exponential backoff
  (`_fetch_overpass`, `_FETCH_ATTEMPTS=4`) and memoises results by coordinates
  rounded to ~110 m (`_AMENITY_CACHE`) to cut request volume; persistent failures
  still fail soft. Note the memo means two listings in the same ~110 m cell share
  one amenity payload (nearest-distance error bounded by the cell size).

- **ScrapeOps intermittent degraded renders + 403.** On 2026-05-30 the ScrapeOps
  runs parsed only **1 listing** per city (`fetched: 1`). Root-caused (live
  capture, 2026-05-30): not dedup and not a parser regression — a fresh fetch
  returns a healthy page (30 `article.item` cards, parser yields 25) and
  `_parse_page` is correct. ScrapeOps' DataDome bypass just *intermittently*
  returns a near-empty render, which slipped through because `scrape()` only
  guarded against **zero** listings. **Fixed:** `scrape()` now re-fetches the
  first page when it parses fewer than `_MIN_FIRST_PAGE_LISTINGS` (5) cards yet
  the page advertises more results (`_advertised_total`), bounded by
  `_LOW_YIELD_REFETCHES` (2). Separately, one ScrapeOps request returned a **403**
  mid-day before later requests succeeded; the retry/backoff in
  `_fetch_via_scrapeops` covers transient 403/429/5xx, but persistent 403s would
  fail that city's run.

- **Scraper brittleness.** Idealista markup changes or DataDome updates can break
  the scraper. `ScrapingBlockedError` is caught per-city so one failure doesn't
  abort the whole run. Transient ScrapeOps failures (408/429/5xx, timeouts) are
  retried with exponential backoff in `_fetch_via_scrapeops` (`_FETCH_ATTEMPTS=4`);
  only persistent failures bubble up to fail that city's run.

- **Geocoding accuracy.** Nominatim falls back to municipality centroid, which can
  misplace listings and skew distance/amenity scores.

- **Cost:** Bright Data (default) charges **1 credit per record** against the
  renewable 5,000/month free tier — ~30 records per city page, so a weekly run
  over a handful of cities stays comfortably inside the tier even with extra
  `/scout` runs. The ScrapeOps fallback charges 40 credits per
  `bypass=datadome` request (cheaper bypasses do **not** clear Idealista's
  DataDome — empirically `generic_level_1` → 500, `generic_level_2` → empty
  page; `generic_level_3` works but also costs 40) against its 1,000/mo free
  tier. Plus small OpenAI cost per new listing analysed (all new listings, not
  just top-N).

---

## Next steps

1. **Route the ES enrichers/regulatory inputs through `ProviderBundle`**
   (`enrichers`/`regulatory` fields) so `orchestrate.py` drops its direct
   `scout.providers.es.*` imports — prerequisite for a second country/portal
   provider.
2. **Watch Bright Data credit burn against the live runs.** ~30 records per
   city page vs. the renewable 5,000/mo free tier — ample headroom for
   on-demand `/scout` runs. Adjust `scrape.pages` in `config.yaml` to trade
   coverage for credits.
3. **Monitor scraper health** — Idealista markup / DataDome changes and Bright
   Data collector drift (the collector is built in Scraper Studio and may need
   rebuilding if Idealista's pages change) remain the most likely causes of
   future breakage; `ScrapingBlockedError` is caught per-city so one failure
   doesn't abort the run.
4. **Widen the INE CSV seeds** (price / neighbourhood / environment) beyond the
   current 9 municipalities to the full commuter belts of the configured cities.
