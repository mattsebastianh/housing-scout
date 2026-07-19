# Bright Data scraper migration — design

**Date:** 2026-07-07
**Status:** approved (user requested the migration explicitly; design decisions
below follow the evaluation run performed the same day)

## Goal

Migrate the scrape stage (stage 1 of the pipeline) from the ScrapeOps Proxy
Aggregator to the Bright Data Scrapers collector API, while keeping the
ScrapeOps path intact as a config-selectable fallback. Bright Data's renewable
free tier (5,000 credits/month, 1 credit = 1 record, ~30 records per
city/week ≈ 400 credits/month) covers the workload at €0, and its collector
crawls each listing's detail page, yielding full descriptions.

## Background — evaluation results (2026-07-07)

A Scraper Studio collector (id redacted, named "idealista.com")
was AI-built from the pipeline's exact Barcelona search URL and run once:
31 pages crawled (search page + each listing's detail page), 30 records,
0 failures, 1 min 36 s, 33 credits. 10/10 overlap with the same-night
ScrapeOps baseline; all prices in range. Record fields: `title`,
`price {value,currency,symbol}`, `location`, `size_m2`, `bedrooms`,
`description` (full detail-page text, ~2,800 chars avg), `url`,
`property_id`, `input`. Missing vs our needs: `bathrooms`, `plot_size`
(mined from `description` instead — see mapping).

## API contract (verified empirically with the account API key)

- **Trigger:** `POST https://api.brightdata.com/dca/trigger?collector={id}&queue_next=1`
  with `Authorization: Bearer $BRIGHTDATA_API_KEY` and JSON body
  `[{"url": <search url>}, …]`. Returns a collection id.
- **Poll:** `GET https://api.brightdata.com/dca/dataset?id={collection_id}`.
  Returns `202 {"status":"building", …}` while running/packaging, then
  `200` with a JSON array of records. Bad key → `401`.

## Design

### New module: `chalet/scrape/brightdata.py`

Exposes `scrape(*, city, price_min, price_max, pages=1, delay_ms=3000,
geocode=True) -> list[Listing]` — the same signature as
`idealista.scrape()` so the orchestrator can dispatch on provider. The
Idealista-specific shared pieces (`_CITY_SLUGS`, `_BASE`, title-based
`_is_flat`/`_is_attached` filters, `_parse_plot_m2`, bathroom/bedroom
regexes, `_geocode_listings`, `ScrapingBlockedError`) are imported from
`chalet.scrape.idealista` — Bright Data is an alternative *transport* for
the same portal, so the parsing knowledge stays in one place.

Flow:
1. Build the same search URL as the ScrapeOps path; for `pages > 1`, add
   one input per extra page (`…/pagina-{n}.htm?orden=publicado-desc`).
2. Trigger the collector (retry transient HTTP errors, same policy shape
   as the ScrapeOps fetch).
3. Poll the dataset endpoint every 15 s until the array arrives
   (timeout 15 min → `ScrapingBlockedError`). `delay_ms` is accepted but
   unused (the collector paces its own crawl).
4. Map records → `Listing` (below), drop flats/attached types, geocode via
   the shared Nominatim helper (records carry no coordinates).
5. Empty dataset or job failure → `ScrapingBlockedError` (parity with the
   ScrapeOps path so orchestrate's handling is unchanged).

### Record → `Listing` mapping

| Listing field | Source |
|---|---|
| `portal` | `"idealista"` (same portal; dedup/enrichers unchanged) |
| `external_id` | `property_id`, falling back to `/inmueble/(\d+)/` in `url` |
| `price_eur` | `price.value` (dict) or digit-parse (string fallback) |
| `size_m2` | first `N m²` in `size_m2` text (built area) |
| `bedrooms` | digits in `bedrooms` ("5 habitaciones") |
| `bathrooms` | mined from `description` (`N baño(s)/aseo(s)` regex); 0 if absent |
| `plot_m2` | `_parse_plot_m2(description)` — full descriptions make this *more* reliable than list-page snippets |
| `municipality` | last comma-part of `location` |
| `address` | street from `title` (text after " en venta en ") + `location` |
| `description` | `description` as-is |
| `raw_json` | full record JSON (provenance; ScrapeOps path stores `"{}"`) |
| flat/attached filter | title prefix check (`title.split(" en ", 1)[0]`) — works for both "Chalet adosado en venta en…" and list-style titles |

### Config & env

- `Scrape.provider: Literal["scrapeops", "brightdata"] = "scrapeops"` —
  pydantic default preserves existing behaviour for tests/old configs.
- `Scrape.brightdata_collector_id: str | None = None`; validator requires it
  when `provider == "brightdata"`.
- `config.yaml` sets `provider: brightdata` and the collector id — this is
  the actual migration switch.
- New env var `BRIGHTDATA_API_KEY` (required at scrape time when provider is
  brightdata). `SCRAPEOPS_API_KEY` stays documented as the fallback path.

### Orchestrator & scripts

- A shared dispatcher `chalet.scrape.scrape_listings(cfg, city_name)`
  (in `chalet/scrape/__init__.py`) selects the provider module from
  `cfg.scrape.provider`; both `orchestrate._scrape_and_persist_city()` and
  `scripts/manual_scrape.py` call it. The `except ide.ScrapingBlockedError`
  clause is unchanged (both providers raise the same class).
- `_fill_top_details()` stays gated by `scrape.fetch_details` (currently
  `false`). Bright Data records are already detail-level, so the flag is
  irrelevant on that provider; if enabled it still works via ScrapeOps.
- `scripts/manual_scrape.py` dispatches by provider so the no-DB test path
  exercises whichever provider is configured.

### Testing

`tests/scrape/test_brightdata.py` (respx for httpx, matching existing
conventions): record→Listing mapping (price dict + string, size text,
bedrooms, bathroom mining, plot mining, municipality/address derivation,
external_id fallback), flat/adosado filtering, trigger+poll flow
(202-building then 200-array), empty dataset → `ScrapingBlockedError`,
poll timeout → `ScrapingBlockedError`, missing env key → `RuntimeError`,
`pages=2` → second input URL. Config tests: provider validation.

### Out of scope

- Deleting the ScrapeOps path (kept as fallback; switch back via config).
- Adding `bathrooms`/`plot_size` fields to the collector schema in Scraper
  Studio (would need another AI-chat iteration; description mining covers
  it for now).
- Web Unlocker integration (blocked on a payment method on the account).

### Trade-offs accepted

- Async job model: a scrape now takes ~2 min per city (trigger + poll)
  vs ~20 s; irrelevant for a weekly scheduled run.
- The collector is Bright Data's AI-generated, self-healing code; if
  Idealista changes layout we depend on their regeneration rather than our
  own parser fix. Mitigated by keeping the ScrapeOps path selectable.
