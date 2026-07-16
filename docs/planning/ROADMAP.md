# Housing Scout — Project Review & Feature Roadmap

_Generated 2026-06-04 from code-architect, code-reviewer, and code-explorer agents. The buyer profile (target cities, radius, priorities, investment angle) now lives in the user's gitignored `profile.yaml`. Weights rebalanced 2026-07-07: **location 0.20 is now the top weight**, commute 0.15._

> **Dated snapshot (pre-refactor paths).** File paths and line numbers below predate the
> 2026-07-14 genericize refactor (`chalet/` → `scout/core/` + `scout/providers/es/`) and are
> not updated — map them via `docs/engineering/ARCHITECTURE.md`. Items are struck through
> (~~like this~~) when shipped; the live status of bugs and planned features is tracked in
> `docs/engineering/FEATURES.md`.

---

## Context

Three parallel agents reviewed the project after the recent restructure (module moves, test reorganization, dead-code removal). This plan consolidates: (1) remaining structural issues, (2) confirmed bugs silently degrading every run, and (3) a prioritized feature roadmap.

---

## Part 1 — Remaining Structural Issues

### High priority

**A. ~~Move `boe_alerts.py` + `zonas_tensionadas.py` into `chalet/regulatory/`~~** — ✅ **Shipped 2026-07-13** as `scout/providers/es/regulatory/` (see FEATURES.md Phase 3b).

They landed in the package root after being evicted from `enrich/`. Root is now a mix of infrastructure modules (`db`, `config`, `models`, `migrations`) and domain-specific ones. Both are regulatory signal providers and belong together.

```
chalet/regulatory/__init__.py
chalet/regulatory/boe_alerts.py
chalet/regulatory/zonas_tensionadas.py
tests/regulatory/__init__.py
tests/regulatory/test_boe_alerts.py
tests/regulatory/test_zonas_tensionadas.py
```

Blast radius: `chalet/orchestrate.py` lines 13–15 (2 imports), 2 test files. Low risk.

**B. Fix `compose.py` weights — config.yaml changes are silently ignored** — ✅ **Fixed 2026-07-07**: `composite(dim_scores, weights)` now receives `cfg.scoring.weights.model_dump()` from `orchestrate._run_city`; the hardcoded `WEIGHTS` dict is gone.

`chalet/score/compose.py` defines a hardcoded `WEIGHTS` dict. `orchestrate.py` calls `composite(dim_scores)` with no weights argument. Changes to `config.yaml → scoring.weights` have zero effect at runtime.

Fix: remove module-level `WEIGHTS`; change signature to `composite(dim_scores, weights: dict[str, float])`; pass `cfg.scoring.weights.model_dump()` from `orchestrate._score_property`. Blast radius: `compose.py`, `orchestrate.py`, `tests/score/test_compose.py`.

### Low priority (leave for now)

- `filter/persist.py` name is a misnomer but the grouping is pragmatic — not worth moving
- `enrich/environment.py` three-enricher split (air/noise/wildfire) loads the same CSV row three times — correct but redundant; refactor when adding new env sources
- `_DIM_LABELS` duplicated between `markdown.py` and `property_analyst.py` — intentionally different display contexts, leave separate

---

## Part 2 — Confirmed Bugs (Every Run Affected)

### Critical — fix before anything else

| # | Issue | File | Line |
|---|---|---|---|
| 1 | `province=None` always set on `Listing` — causes INE, neighbourhood, and environment enrichers to silently bail; `score_price` always `None` | `scrape/idealista.py` | 249 |
| 2 | `broadband` enricher referenced in `score_infrastructure` but never registered — broadband sub-score is always the constant `5` | `score/dimensions.py` | 165 |
| 3 | `or` short-circuit in `_nearest_station_km` returns wrong distance when nearest station is exactly 0.0 km | `enrich/osm.py` | 92 |

**Fix for #1:** Add a `_CITY_PROVINCE` dict in `idealista.py` mapping city name → province string; assign it when building `Listing`. This unblocks INE, neighbourhood, and all three environment enrichers for every listing.

**Fix for #2:** Remove the broadband branch from `score_infrastructure` and redistribute its 0.20 weight across the other three sub-scores (transit 0.25, school 0.45, health 0.30). Or implement a real enricher.

**Fix for #3:** Replace `or` with explicit `None` check:
```python
r = _nearest_km(elements, lat, lon, "railway", {"station"})
pt = _nearest_km(elements, lat, lon, "public_transport", {"station"})
return min((v for v in (r, pt) if v is not None), default=None)
```

### Important — fix soon

| # | Issue | File | Line |
|---|---|---|---|
| 4 | Enrichment outer loop is sequential per listing — `asyncio.gather` inside `_enrich_one` is correct, but listings are enriched one-by-one. ~25 listings × 4 enrichers × ~3s = 300s instead of ~15s | `orchestrate.py` | 279–289 |
| 5 | `_fill_top_details` mutates `plot_m2` after scoring — persisted composite score is stale; report shows `plot_m2` the score never used | `orchestrate.py` | 221–244 |
| 6 | `migrate()` uses `executescript` (non-atomic, auto-commits) — a failed migration leaves schema half-applied | `db.py` | 37–41 |
| 7 | `score_infrastructure` falls back to hardcoded constants (transit=3, health=4) when distance data absent, producing fabricated scores instead of `None` | `score/dimensions.py` | 172–202 |

**Fix for #4:** Gather all listing enrichments concurrently:
```python
tasks = [_enrich_one(item, client) for item in items]
results = await asyncio.gather(*tasks)
```

**Fix for #5:** Re-call `_score_property` after `_fill_top_details` for any listing whose `plot_m2` changed.

---

## Part 3 — Feature Roadmap

### Tier 1 — Quick Wins (≤ 1 day each)

| # | Feature | Hooks into | Value |
|---|---|---|---|
| 1.1 | **Expand CSV seeds** from 9 → ~40 municipalities covering full commuter belts | `data/ine/*.csv` (data work only, no code changes) | Very High — `score_price` (weight 0.18) returns `None` for most listings today |
| 1.2 | **Add `plot_m2` to Telegram card** when known | `notify/telegram.py:131` | High — most important family metric, currently omitted from the primary interface |
| 1.3 | **Add Google Maps + Catastro links** to Telegram card | `notify/telegram.py:127` | High UX — removes friction from the two most common follow-up actions |
| 1.4 | **Fix hardcoded `zone_class`/`market_context` stub** — always renders "URBANO" and "Datos zonales no disponibles" in every report | `orchestrate.py:327` | Medium — report contains fabricated content today |
| 1.5 | **Persist AI analyst output to DB** — `summary_md` and `analyst_md` are lost after each run | `migrations.py` (new column), `orchestrate._persist_score` | Medium |
| 1.6 | **Min-bedrooms hard filter** (`search.min_bedrooms: 3` in config) | `filter/hard_excl.py`, `config.yaml`, `config.py` | Medium — avoids scoring 1–2 bedroom listings |

### Tier 2 — Medium Effort, High Value (1–3 days each)

| # | Feature | Hooks into | Value |
|---|---|---|---|
| 2.1 | **Price-drop tracking** — detect when a previously-seen listing drops in price; alert in Telegram with "📉 Precio reducido -X €" | `filter/persist.py`, `migrations.py` (new `price_history` table), `models.py`, `notify/telegram.py` | Very High — converts agent from discovery to opportunity detection |
| 2.2 | **Re-surface price-dropped past listings** — un-suppress a reported listing when price drops by > threshold | `orchestrate.py:139` | High — depends on 2.1 |
| 2.3 | **Automated INE CSV refresh script** — fetch INE data programmatically, regenerate the three CSVs | New `scripts/refresh_ine_data.py` | High — CSVs will silently go stale otherwise |
| 2.4 | **Persistent geocoding cache (SQLite)** — avoid re-geocoding the same addresses every run | `migrations.py` (new `geocode_cache` table), `scrape/idealista.py` | Medium-High |

### Tier 3 — Large Effort, Strategic Value (1–2 weeks each)

| # | Feature | Value |
|---|---|---|
| 3.1 | **Fotocasa second scraper** — `Listing.portal`, dedup logic, and DB schema are already ready | High — ~doubles listing coverage |
| 3.2 | **Point-level noise/air WMS enrichers** — replace municipal CSV averages with coordinate-level MITECO WMS calls (like `sncziflood.py` already does) | Medium |
| 3.3 | **Interactive Telegram bot** — `/top barcelona`, `/view {id}`, `/history` commands; reads from DB | High UX — transforms agent from push-only digest to on-demand tool |

### Recommended execution order

1. Fix bugs #1, #2, #3 (critical — silent scoring degradation on every run)
2. Fix bug #4 (enrichment concurrency — performance)
3. Feature 1.1 (expand CSV seeds — no code, just data)
4. Features 1.2 + 1.3 (Telegram UX — immediate payoff)
5. Feature 1.4 + 1.5 (report correctness + DB persistence)
6. Features 2.1 + 2.2 together (price-drop tracking — highest-value addition)
7. Feature 1.6, 2.3, 2.4 (filters + data hygiene)
8. Tier 3 when core is fully hardened

---

## Verification

After any code change, run:
```bash
.venv/bin/python -m pytest -q          # 196 tests must pass
.venv/bin/python run_daily.py --check  # pipeline boots cleanly
```

For bug #1 specifically: add a `print(listing.province)` in the orchestrator temporarily and confirm it's non-None after the fix.

For bug #4 (concurrency): time the enrichment stage before and after with `scrape.pages=2`.
