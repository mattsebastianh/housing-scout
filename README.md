# Housing Scout

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)
[![Version](https://img.shields.io/badge/version-3.0.0-informational.svg)](CHANGELOG.md)

A reusable, profile-driven **property-scouting agent template**. It scrapes a real-estate portal on a schedule (and on demand from Telegram), enriches every listing with public data, scores it across 8 dimensions, runs an AI analyst on each new listing, and delivers the results as Telegram property cards plus a ranked Markdown report — one independent pipeline per target city.

Everything personal — country, portal, target cities, price range, property type, buyer preferences — lives in a **gitignored `profile.yaml`** created by an interactive setup wizard. The committed code and config are generic. The template ships with one reference implementation: **Spain / Idealista** (`scout/providers/es/`), and a provider registry for adding other countries or portals.

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| macOS | 12+ | Intel or Apple Silicon (scheduling scripts use launchd; the pipeline itself is portable Python) |
| Python | 3.13 | Install via Homebrew: `brew install python@3.13` (requires ≥ 3.11) |
| Homebrew | any | [brew.sh](https://brew.sh) |

> **Apple Silicon:** Homebrew installs to `/opt/homebrew`. Replace `/usr/local/bin/python3.13` with `/opt/homebrew/bin/python3.13` throughout.

---

## Setup

```bash
git clone <your-repo-url>
cd <repo>

/usr/local/bin/python3.13 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env          # fill in the variables below

# Create your personal profile (gitignored) — cities, price range, buyer preferences
.venv/bin/python -m scout setup
```

The wizard writes `profile.yaml`. You can also copy `profile.example.yaml` to `profile.yaml` and edit it by hand. Both entry points (`run_daily.py`, `run_listener.py`) refuse to start without a profile and print `Run: python -m scout setup` (exit code 2).

### The two config layers

| File | Committed? | Contains |
|---|---|---|
| `profile.yaml` | No (gitignored) | Everything personal: `country`, `portal`, target cities (name/lat/lon/radius, optional `portal_slug`), price range, `property_type`, `preferred_plot_m2`, and a free-form buyer profile (household, purpose, priorities, investment angle, must-haves, deal-breakers, AI response language) |
| `config.yaml` | Yes | Mechanical knobs only: scrape provider/pages/delays, report language/top-N/output dir/timezone/`app_name`, scoring weights, run schedule |

### Environment variables

| Variable | Required | How to get it |
|---|---|---|
| `BRIGHTDATA_API_KEY` | Yes (default provider) | [brightdata.com](https://brightdata.com/) → Settings → API tokens |
| `BRIGHTDATA_COLLECTOR_ID` | Yes (default provider) | Build a collector in Bright Data Scraper Studio from your portal search URL, copy its ID (`c_xxx…`); can also be set as `scrape.brightdata_collector_id` in `config.yaml` |
| `SCRAPEOPS_API_KEY` | Only if `scrape.provider: scrapeops` | [scrapeops.io](https://scrapeops.io/) → Dashboard → API key |
| `TELEGRAM_BOT_TOKEN` | No | [@BotFather](https://t.me/BotFather) → `/newbot` |
| `TELEGRAM_CHAT_ID` | No | Send a message to your bot, visit `https://api.telegram.org/bot<TOKEN>/getUpdates`, copy `chat.id` |
| `OPENAI_API_KEY` | No | [platform.openai.com](https://platform.openai.com/) → API keys (enables the AI analyst + chat agent) |
| `SCOUT_ANALYST_MODEL` | No | Override the AI analyst model (default `gpt-5.4-mini`) |
| `SCOUT_CHAT_MODEL` | No | Override the Telegram chat agent model (default `gpt-5-nano`) |
| `SCOUT_DB_PATH` | No | Override the SQLite path (default `data/scout.db`) |
| `SCOUT_LOG_DIR` | No | Override the log directory (default `logs/`) |

Leave optional variables blank to disable those features.

### Verify the setup

Checks config + profile, initialises the SQLite DB, and exits without scraping:

```bash
.venv/bin/python run_daily.py --check
```

Expected output (with your own cities/prices):
```
Config loaded. Cities: <your cities>
Price range: <min> – <max> €
DB ready: data/scout.db
Log: logs/run-YYYY-MM-DD.log
```

---

## Run

```bash
# Full pipeline (hits live APIs)
.venv/bin/python run_daily.py

# Only specific cities (repeatable flag; must exist in profile.yaml)
.venv/bin/python run_daily.py --city <city>

# Alternate config / profile files
.venv/bin/python run_daily.py --config path/to/config.yaml --profile path/to/profile.yaml

# Test the scraper alone — prints listings, no DB write
.venv/bin/python scripts/manual_scrape.py [--city <city>]
```

Each run, per city:
1. Scrapes the portal via the provider bundle registered for your profile's `(country, portal)` pair — transport selected by `scrape.provider` in `config.yaml`: **brightdata** (default — a pre-built collector crawls the search page + each detail page) or **scrapeops** (fallback — HTML through a DataDome-bypassing proxy; pages configurable via `scrape.pages`)
2. Enriches survivors with public data (cadastre, OSM amenities, OSRM drive times, zonal median prices, neighbourhood stability, flood/air/noise/wildfire — in the Spain reference implementation)
3. Scores each listing across 8 weighted dimensions (weights in `config.yaml`)
4. Runs the AI analyst (default `gpt-5.4-mini`, reasoning) on all new listings, using a system prompt built from `agent_instructions/` + your profile — if `OPENAI_API_KEY` is set
5. Writes one report per city: `data/reports/YYYY-MM-DD-{city}.md`
6. Sends a Telegram summary per city — run stats plus one card per top-5 listing with a short AI summary — if credentials are set

---

## Customising the AI instructions

The AI system prompts are committed, editable Markdown templates in `agent_instructions/`:

- `property_analyst.md` — the per-listing analyst prompt
- `chat_agent.md` — the Telegram conversational agent prompt

English is the default; Spanish versions (`property_analyst.es.md`, `chat_agent.es.md`) ship alongside as ready-made alternatives — they are not loaded automatically, so to use one copy it over the default file or into a `.local.md` override.

The templates use placeholders filled at runtime from your `profile.yaml`, so no personal data lives in them: `property_analyst.md` uses all seven — `{cities}`, `{price_min}`, `{price_max}`, `{property_type}`, `{preferred_plot_m2}`, `{buyer_profile}`, `{response_language}` — while `chat_agent.md` uses five (all except `{property_type}` and `{preferred_plot_m2}`).

To customise a prompt without touching the committed file, create a gitignored local override next to it: `agent_instructions/property_analyst.local.md` (or `chat_agent.local.md`). If a `.local.md` file exists, it wins.

---

## Automated scheduling on macOS

Installs a launchd agent that runs the pipeline weekly (Tuesday 00:00 Europe/Madrid as shipped — edit the plist template to change it):

```bash
bash scripts/install_launchd.sh
```

To uninstall:
```bash
launchctl bootout "gui/$(id -u)/com.housing-scout.daily"
rm ~/Library/LaunchAgents/com.housing-scout.daily.plist
```

---

## On-demand runs from Telegram

Besides the schedule, you can trigger a run any time by messaging the bot:

- `/scout` — run all configured cities
- `/scout <city>` — just one city
- `/scout <city1>, <city2>` — any subset (space- or comma-separated, case/accent-insensitive)

Install the always-on listener (launchd, KeepAlive — restarts automatically):

```bash
bash scripts/install_listener.sh
```

To uninstall:
```bash
launchctl bootout "gui/$(id -u)/com.housing-scout.listener"
rm ~/Library/LaunchAgents/com.housing-scout.listener.plist
```

The listener acknowledges each `/scout`, runs the normal pipeline (`run_daily.py --city …`), and the results arrive as the usual Telegram cards + report. A shared lock ensures a manual run and the scheduled run never overlap.

Anything else you write to the bot is answered by a conversational AI agent (default `gpt-5-nano`; override with `SCOUT_CHAT_MODEL`) that knows your configured cities, price range, and buyer profile, and whether a search is currently running. Requires `OPENAI_API_KEY`; without it the bot replies with a static help message instead.

---

## Tests

```bash
.venv/bin/python -m pytest                   # all tests
.venv/bin/python -m pytest --cov=scout       # with coverage
.venv/bin/python -m pytest tests/core/test_db.py  # single file
```

---

## Scoring dimensions

Weights live in `config.yaml → scoring.weights` (must sum to 1.0). As shipped:

| Dimension | Weight | What it measures |
|---|---|---|
| Location | 0.20 | Supermarkets, parks, healthcare, schools nearby + municipality size |
| Price | 0.18 | €/m² vs. zonal median (negotiation bonus for stale listings) |
| Commute | 0.15 | Drive time to city centre, nearest station (≤ 1.5 km full score), motorway access |
| Legal | 0.15 | Cadastral use code, year built, urbanistic class |
| Environmental | 0.10 | Flood zone, wildfire hazard, noise (Lden), air (NO₂) |
| Neighbourhood | 0.10 | Commercial density, parks/schools, primary-residence %, tourism-rental activity |
| Regulatory | 0.07 | Stressed-housing-zone flag, recent official-bulletin housing alerts |
| Infrastructure | 0.05 | Nearest school/clinic walking distance, transit proximity, broadband |

A bounded plot-size bonus (≤ +0.3) nudges the composite for large plots: full bonus at your profile's `preferred_plot_m2`, ramping linearly from half that size; unknown plots are never penalised.

---

## Architecture: core + providers

```
scout/
├── core/                  # Country/portal-agnostic pipeline (agnostic for scraping today — see note below)
│   ├── orchestrate.py     #   scrape → filter → enrich → score → analyse → report → notify
│   ├── registry.py        #   ProviderBundle + register/resolve(country, portal)
│   ├── profile.py         #   Profile models + load_profile / profile_exists
│   ├── config.py          #   Mechanical config models (config.yaml)
│   ├── setup_wizard.py    #   Interactive wizard → profile.yaml
│   ├── scrape/base.py     #   Provider-agnostic scrape dispatch via the registry
│   ├── analyse/           #   AI analyst + profile-driven prompt builder
│   ├── enrich/            #   Generic enrichers (OSM, OSRM) + async runner
│   ├── filter/ score/ report/ notify/   # exclusions/dedup, dimensions, Markdown, Telegram
│   └── models.py db.py migrations.py runlock.py …
└── providers/
    └── es/                # Reference implementation: Spain / Idealista
        ├── scrape/        #   brightdata.py (default) + idealista.py (ScrapeOps fallback)
        ├── enrich/        #   catastro, ine, neighbourhood, sncziflood, environment
        ├── regulatory/    #   boe_alerts, zonas_tensionadas
        └── data/          #   Bundled CSVs (median €/m², neighbourhood, environment)
```

A provider bundle (`ProviderBundle`) packages a portal's scrape callable, geocoding country, portal base URL and city→slug mapping, and is registered under a `(country, portal)` key on import of `scout.providers`. `scout/core/scrape/base.py::scrape_listings()` resolves the bundle from your profile's `country`/`portal` and dispatches — the core pipeline never imports a portal by name for scraping. (The Spain-specific enrichers and regulatory inputs are currently wired directly in `orchestrate.py`; the bundle's `enrichers`/`regulatory` fields exist for moving them behind the registry.)

To add a new country/portal: implement a scrape function that returns `Listing` objects (raising `ScrapingBlockedError` when blocked), create `scout/providers/<cc>/__init__.py` that registers a `ProviderBundle`, and set `country`/`portal` in your profile.

---

## Directory layout (top level)

```
├── agent_instructions/     # Editable AI prompt templates (+ gitignored *.local.md overrides)
├── config.yaml             # Mechanical parameters (committed)
├── profile.example.yaml    # Template for your gitignored profile.yaml
├── scout/                  # Python package: core/ + providers/
├── data/
│   ├── scout.db            # SQLite database (created on first run)
│   └── reports/            # Generated Markdown reports
├── docs/                   # PRD, architecture, features, planning, prompt references, specs
├── logs/                   # Structured JSON logs per run
├── scripts/                # install_launchd, install_listener, manual_scrape
├── tests/                  # pytest suite (core, providers, enrich, score, notify, …)
├── run_daily.py            # Pipeline entry point (--check, --city, --config, --profile)
├── run_listener.py         # Always-on Telegram /scout listener entry point
├── run_setup.py            # Setup wizard entry point (same as python -m scout setup)
└── .env.example            # Environment variable template
```

---

## Migrate data to another machine

```bash
# On the old machine
scp data/scout.db user@newmac:/path/to/repo/data/scout.db
```

Reports live in `data/reports/` and can be copied the same way. Copy your `profile.yaml` and `.env` too — both are gitignored.

---

## Roadmap

Planned work lives in [`docs/planning/ROADMAP.md`](docs/planning/ROADMAP.md) and the current next move in [`docs/planning/NEXT_MOVE.md`](docs/planning/NEXT_MOVE.md). Up next: **initiation config wizard v2** — a sectioned, re-runnable `python -m scout setup` (search / buyer / goals / agent behavior) that lets you edit any part of your profile at any time and add freeform custom instructions for the AI analyst and chat agent.

---

## License

[MIT](LICENSE)
