# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

_Nothing yet._

## [3.0.0] - 2026-07-18

Rebrand and provider-agnostic refactor: `chalet` → `property-scout` → `housing-scout`.
Published as a fresh squashed snapshot — the root of public history.

- Split package into `scout/core/` (country/portal-agnostic) and `scout/providers/es/`
  (Spain / Idealista reference implementation), joined by a provider registry
- Added `Profile` model + loader for a gitignored `profile.yaml`, separating personal
  search criteria from the committed `config.yaml`
- Added interactive `python -m scout setup` wizard with a first-run profile gate
- Externalized AI prompts to `agent_instructions/*.md` with profile-driven placeholders
- Renamed `CHALET_*` env vars to `SCOUT_*`; default DB path `data/scout.db`
- Added `MEMORY.md` cross-session project memory conventions (later moved to
  `.claude/memory/`, gitignored)
- Replaced hardcoded profile/branding/country literals with config-driven values
- Made English the default agent-instruction language; Spanish templates kept
  alongside as `*.es.md` backups (not loaded automatically)
- Docs housekeeping: documented the Spanish prompt templates and the `/scout`
  listener uninstall in README, surfaced `scripts/manual_scrape.py`, used
  `python -m pytest` consistently, corrected ROADMAP staleness, added this
  `CHANGELOG.md` summarizing v1.0.0 onward
- Gitignored generated graphify knowledge-graph artifacts (`/graphify*`) and
  `.git-private/`; untracked `CLAUDE.md` and `.claude/memory/` (privacy)

## [2.0.0] - 2026-07-13

- Added Telegram `/scout` listener for on-demand pipeline runs with flexible city
  selection (space/comma-separated, case/accent-insensitive)
- Added conversational chat agent (`gpt-5-nano`) for non-command Telegram messages
- Upgraded Property AI Analyst to `gpt-5.4-mini`; added `CHALET_ANALYST_MODEL` /
  `CHALET_CHAT_MODEL` overrides
- Fixed `compose.py` ignoring configured scoring weights; retuned location/commute
  weights (0.20 / 0.15)
- Added per-property Telegram cards with inline "Ver anuncio" URL buttons
- Reorganized `docs/` into `product/`, `engineering/`, `planning/`, `prompts/`, `specs/`
- Pre-public-release security audit fixes; added MIT license

## [1.4.0] - 2026-07-07

- Migrated scrape stage to the Bright Data collector API (ScrapeOps kept as fallback)
- Ran AI analysis on all new scored listings, not just the top-N
- Included plot size in the AI analyst prompt and summary; sorted search results
  newest-first
- Added `neighbourhood` enricher (`primary_residence_pct`, `investment_hits`) and wired
  air/noise/wildfire enrichers into the environmental score
- Derived `urbanistic_class` from Catastro cadastral class; resolved Catastro reference
  from coordinates
- Wired `boe_alerts` regulatory enricher; installed launchd scheduler
- Security: redacted API keys from exception logs and Telegram alerts
- Replaced `per_city_limit` with pages-based scrape control
- Reorganized project structure; added PRD

## [1.3.0] - 2026-05-30

- Migrated scraper from ZenRows to ScrapeOps
- Added retry + caching for Overpass API to survive 429/504 rate limits
- Added per-city pipelines, typology + plot filters, AI summary via `gpt-5-mini`
- Simplified reports to clean Markdown (removed PDF generation)
- Geocoded Idealista listings via Nominatim with address/municipality fallback
- Renamed project from Chalet Finde Spain to Chalet Spain

## [1.2.0] - 2026-05-28

- Migrated scraper from Playwright to the ZenRows API (DataDome bypass)
- Sent the daily Markdown report as a Telegram document attachment
- Removed the Apify client, Fotocasa scraper, and their tests

## [1.1.0] - 2026-05-28

- Replaced the Apify Idealista scraper with Playwright + BeautifulSoup
- Added a Property AI Analyst per listing in the daily report (Anthropic → OpenRouter →
  Ollama, in that order, before settling on OpenAI)
- Added Telegram bot notifications; raised price range to €150k–250k
- Reweighted scoring for the primary family residence objective

## [1.0.0] - 2026-05-26

Initial working pipeline (Phases 0–7): project foundation, filter layer, scraping
adapters (Apify), enrichment layer, scoring engine, Markdown report renderer,
orchestration, and launchd scheduling.
