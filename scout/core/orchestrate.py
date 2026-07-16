import asyncio
import sqlite3
from collections import Counter
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

import httpx
import structlog

import scout.providers  # noqa: F401  (registers provider bundles on import)
from scout.core.config import Config
from scout.core.profile import Profile
from scout.core.enrich.base import EnrichmentResult, run_enrichers
from scout.providers.es.regulatory.boe_alerts import fetch_alerts
from scout.providers.es.enrich.catastro import enrich_catastro
from scout.providers.es.regulatory.zonas_tensionadas import is_tensionada
from scout.providers.es.enrich.environment import enrich_air, enrich_noise, enrich_wildfire
from scout.providers.es.enrich.ine import enrich_zone_median
from scout.providers.es.enrich.neighbourhood import enrich_neighbourhood
from scout.core.enrich.osm import enrich_osm
from scout.core.enrich.osrm import enrich_drive_time
from scout.providers.es.enrich.sncziflood import enrich_flood
from scout.core.filter.hard_excl import check_listing
from scout.core.filter.persist import (
    insert_or_update_raw,
    record_exclusion,
    upsert_property_for_listing,
)
from scout.core.analyse.property_analyst import analyse_top
from scout.core.models import EnrichedListing, Listing, ScoredListing
from scout.core.utils import safe_exc_str as _safe_exc_str
from scout.core.notify.telegram import notify_failure, notify_success
from scout.core.report.markdown import render_report, write_report
from scout.core.score import dimensions as dim
from scout.core.score.compose import composite
from scout.core.scrape.base import scrape_listings
from scout.providers.es.scrape import idealista as ide

log = structlog.get_logger("orchestrate")

_ES_DATA = Path(__file__).resolve().parents[1] / "providers" / "es" / "data"
_INE_CSV = _ES_DATA / "municipal_price_psqm.csv"
_NEIGHBOURHOOD_CSV = _ES_DATA / "municipal_neighbourhood.csv"
_ENVIRONMENT_CSV = _ES_DATA / "municipal_environment.csv"


def _city_centres(profile: Profile) -> dict[str, tuple[float, float]]:
    return {c.name: (c.lat, c.lon) for c in profile.search.cities}


async def _enrich_one(item: EnrichedListing, client: httpx.AsyncClient) -> dict[str, EnrichmentResult]:
    centres = item.enrichments.pop("_city_centres", None) or {}

    async def _osrm(it, cl):
        return await enrich_drive_time(it, cl, city_centres=centres)

    async def _ine(it, cl):
        return await enrich_zone_median(it, cl, csv_path=_INE_CSV)

    async def _neighbourhood(it, cl):
        return await enrich_neighbourhood(it, cl, csv_path=_NEIGHBOURHOOD_CSV)

    async def _air(it, cl):
        return await enrich_air(it, cl, csv_path=_ENVIRONMENT_CSV)

    async def _noise(it, cl):
        return await enrich_noise(it, cl, csv_path=_ENVIRONMENT_CSV)

    async def _wildfire(it, cl):
        return await enrich_wildfire(it, cl, csv_path=_ENVIRONMENT_CSV)

    enrichers = {
        "catastro": enrich_catastro,
        "osm": enrich_osm,
        "flood": enrich_flood,
        "osrm": _osrm,
        "ine": _ine,
        "neighbourhood": _neighbourhood,
        "air": _air,
        "noise": _noise,
        "wildfire": _wildfire,
    }
    return await run_enrichers(item, client, enrichers)


def _start_run(conn: sqlite3.Connection) -> int:
    cur = conn.execute(
        "INSERT INTO runs (started_at, status) VALUES (?, 'running')",
        (datetime.now(UTC),),
    )
    return int(cur.lastrowid)


def _finish_run(conn: sqlite3.Connection, run_id: int, **fields: Any) -> None:
    sets = ", ".join(f"{k}=?" for k in fields)
    conn.execute(
        f"UPDATE runs SET finished_at=?, {sets} WHERE id=?",
        (datetime.now(UTC), *fields.values(), run_id),
    )


def _scrape_and_persist_city(
    conn: sqlite3.Connection, cfg: Config, profile: Profile, city
) -> tuple[list[tuple[int, Listing]], int, int, Counter]:
    fetched = 0
    dedup_overrides = 0
    excluded: Counter = Counter()
    survivors: list[tuple[int, Listing]] = []

    try:
        listings = scrape_listings(cfg, profile, city.name)
    except ide.ScrapingBlockedError as exc:
        log.warning("scrape.blocked", city=city.name, error=str(exc))
        excluded["scraping_blocked"] += 1
        return survivors, fetched, dedup_overrides, excluded

    fetched += len(listings)
    for l in listings:
        exc = check_listing(
            l,
            price_min=profile.search.price_min_eur,
            price_max=profile.search.price_max_eur,
            centre_lat=city.lat,
            centre_lon=city.lon,
            radius_km=city.radius_km,
        )
        raw_id = insert_or_update_raw(conn, l)
        if exc is not None:
            record_exclusion(conn, raw_id, exc)
            excluded[str(exc.code)] += 1
            continue
        pid, override = upsert_property_for_listing(conn, l, raw_id)
        if override:
            dedup_overrides += 1
        reported = conn.execute(
            "SELECT reported_at FROM properties WHERE id=?", (pid,)
        ).fetchone()[0]
        if reported is None:
            survivors.append((pid, l))

    return survivors, fetched, dedup_overrides, excluded


def _build_positives_risks(s: ScoredListing, plot_threshold: int) -> tuple[str, str]:
    pos: list[str] = []
    risks: list[str] = []
    if (s.dim_scores.get("price") or 0) >= 8:
        pos.append("- Precio competitivo vs mediana zonal")
    if (s.dim_scores.get("commute") or 0) >= 8:
        pos.append("- Buena conexión con el centro")
    if s.listing.plot_m2 and s.listing.plot_m2 >= plot_threshold:
        pos.append(f"- Parcela amplia (≥{plot_threshold} m²): {s.listing.plot_m2:,} m²".replace(",", "."))
    if s.listing.cadastral_ref:
        pos.append(f"- Catastro: {s.listing.cadastral_ref}")
    if (s.dim_scores.get("environmental") or 10) < 6:
        risks.append("- Riesgo ambiental elevado")
    if (s.dim_scores.get("legal") or 10) < 7:
        risks.append("- ⚠ Verificar catastro / urbanismo")
    risks.append(
        "- ⚠ VERIFICAR nota simple antes de oferta — "
        "[Solicitar](https://www.registradores.org/registro-online/registro-de-la-propiedad)"
    )
    return (
        "\n".join(pos or ["- (sin destacados automáticos)"]),
        "\n".join(risks),
    )


def _score_property(
    pid: int, l: Listing, enrichments: dict[str, EnrichmentResult],
    weights: dict[str, float],
    plot_threshold: int = 600, recent_boe_hit: bool = False,
) -> ScoredListing:
    item = EnrichedListing(
        listing=l,
        property_id=pid,
        enrichments={k: r.payload for k, r in enrichments.items() if r.success and r.payload},
    )
    osm = item.enrichments.get("osm") or {}
    cat = item.enrichments.get("catastro") or {}
    zone = item.enrichments.get("ine")
    nb = item.enrichments.get("neighbourhood") or {}
    municipality_population: int = osm.get("municipality_population") or 50_000
    motorway_km: float | None = osm.get("nearest_motorway_km")
    urbanistic_class: str | None = cat.get("urbanistic_class")
    primary_residence_pct: float | None = nb.get("primary_residence_pct")
    investment_hits: int = nb.get("investment_hits") or 0
    dim_scores = {
        "price": dim.score_price(item, zone),
        "location": dim.score_location(item, municipality_population=municipality_population),
        "commute": dim.score_commute(item, motorway_km=motorway_km),
        "legal": dim.score_legal(item, urbanistic_class=urbanistic_class),
        "regulatory": dim.score_regulatory(
            item, in_tensa=is_tensionada(l.municipality), recent_boe_hit=recent_boe_hit,
        ),
        "environmental": dim.score_environmental(item),
        "neighbourhood": dim.score_neighbourhood(
            item, primary_residence_pct=primary_residence_pct, investment_hits=investment_hits,
        ),
        "infrastructure": dim.score_infrastructure(item),
    }
    osrm = item.enrichments.get("osrm") or {}
    # Large plot is a family preference: a small, bounded boost to ranking that
    # never penalises listings with unknown plot size.
    comp = min(10.0, composite(dim_scores, weights) + dim.plot_bonus(l.plot_m2, plot_threshold))
    s = ScoredListing(
        listing=l,
        dim_scores=dim_scores,
        composite=comp,
        property_id=pid,
        distance_km=osrm.get("distance_km"),
        drive_min=osrm.get("drive_min"),
    )
    s.positives_md, s.risks_md = _build_positives_risks(s, plot_threshold)
    return s


def _fill_top_details(conn: sqlite3.Connection, scored: list[ScoredListing]) -> None:
    """Fetch detail pages for reported listings to fill the bathroom count (and
    any missing bedrooms/plot) that Idealista result cards omit. Best-effort and
    cost-bounded: one extra ScrapeOps request only for listings lacking the data.
    """
    with httpx.Client() as client:
        for s in scored:
            l = s.listing
            if l.bathrooms and l.bedrooms and l.plot_m2:
                continue  # nothing missing — skip the extra request
            details = ide.fetch_listing_details(l.url, client=client)
            if not details:
                continue
            if not l.bathrooms and details.get("bathrooms"):
                l.bathrooms = details["bathrooms"]
            if not l.bedrooms and details.get("bedrooms"):
                l.bedrooms = details["bedrooms"]
            if not l.plot_m2 and details.get("plot_m2"):
                l.plot_m2 = details["plot_m2"]
            conn.execute(
                "UPDATE raw_listings SET bathrooms=?, bedrooms=?, plot_m2=? "
                "WHERE id=(SELECT primary_raw_id FROM properties WHERE id=?)",
                (l.bathrooms, l.bedrooms, l.plot_m2, s.property_id),
            )


def _persist_score(conn: sqlite3.Connection, run_id: int, s: ScoredListing) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO scores (
            run_id, property_id, composite,
            dim_price, dim_location, dim_commute, dim_legal,
            dim_regulatory, dim_environmental, dim_neighbourhood, dim_infrastructure,
            positives_md, risks_md
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id, s.property_id, s.composite,
            s.dim_scores.get("price"), s.dim_scores.get("location"),
            s.dim_scores.get("commute"), s.dim_scores.get("legal"),
            s.dim_scores.get("regulatory"), s.dim_scores.get("environmental"),
            s.dim_scores.get("neighbourhood"), s.dim_scores.get("infrastructure"),
            s.positives_md, s.risks_md,
        ),
    )


def _run_city(cfg: Config, profile: Profile, city, conn: sqlite3.Connection, paths: dict[str, Path]) -> int:
    """Run the full pipeline for a single target city as its own run."""
    run_id = _start_run(conn)
    log.info("run.start", run_id=run_id, city=city.name)

    try:
        survivors, fetched, dedup_overrides, excluded = _scrape_and_persist_city(conn, cfg, profile, city)
        log.info("run.scrape.done", city=city.name, fetched=fetched, survivors=len(survivors))

        centres = _city_centres(profile)

        async def _gather() -> list[tuple[int, Listing, dict[str, EnrichmentResult]]]:
            results: list[tuple[int, Listing, dict[str, EnrichmentResult]]] = []
            async with httpx.AsyncClient(headers={"User-Agent": "housing-scout/0.1"}) as client:
                for pid, l in survivors:
                    item = EnrichedListing(
                        listing=l, property_id=pid,
                        enrichments={"_city_centres": centres},
                    )
                    er = await _enrich_one(item, client)
                    results.append((pid, l, er))
            return results

        enriched = asyncio.run(_gather())

        plot_threshold = profile.search.preferred_plot_m2
        weights = cfg.scoring.weights.model_dump()
        try:
            boe_hit = bool(fetch_alerts())
        except Exception:
            log.warning("run.boe_alerts.failed", city=city.name)
            boe_hit = False
        scored = [_score_property(pid, l, er, weights, plot_threshold, boe_hit) for pid, l, er in enriched]
        scored.sort(key=lambda s: s.composite, reverse=True)
        top = scored[: cfg.report.top_n]
        if cfg.scrape.fetch_details and cfg.scrape.details_limit:
            _fill_top_details(conn, top[: cfg.scrape.details_limit])
        asyncio.run(analyse_top(scored, profile))
        for s in scored:
            _persist_score(conn, run_id, s)

        for s in top:
            conn.execute(
                "UPDATE properties SET reported_at=? WHERE id=?",
                (datetime.now(UTC), s.property_id),
            )

        now = datetime.now(UTC)
        report_dir = paths["reports"]
        cities_label = city.name.capitalize()
        summary = {
            "fetched_total": fetched,
            "dedup_overrides": dedup_overrides,
            "excluded_total": sum(excluded.values()),
            "top_reason": (excluded.most_common(1)[0][0] if excluded else ""),
            "market_signal": "Neutral",
            "macro_alert": "Ninguna alerta relevante en últimas 24 h",
            "new_total": len(survivors),
            "reported_total": len(top),
        }
        _zone_lookup = lambda _l: {
            "zone_class": "URBANO",
            "market_context": "Datos zonales no disponibles",
            "legal_status": "—",
        }
        text = render_report(
            app_name=cfg.report.app_name,
            scored=top,
            run_id=run_id,
            generated_at=now,
            report_date=now,
            cities_label=cities_label,
            price_min=profile.search.price_min_eur,
            price_max=profile.search.price_max_eur,
            top_n=cfg.report.top_n,
            summary=summary,
            zone_lookup=_zone_lookup,
        )
        report_path = write_report(text, report_dir, now, slug=city.name)
        _finish_run(
            conn, run_id,
            status="ok",
            fetched_total=fetched,
            dedup_overrides=dedup_overrides,
            excluded_total=sum(excluded.values()),
            new_total=len(survivors),
            reported_total=len(top),
            report_path=str(report_path),
        )
        log.info("run.done", city=city.name, report=str(report_path))
        asyncio.run(notify_success(
            app_name=cfg.report.app_name,
            run_id=run_id,
            fetched=fetched,
            excluded=excluded,
            new_total=len(survivors),
            reported_total=len(top),
            top=top,
            price_min=profile.search.price_min_eur,
            price_max=profile.search.price_max_eur,
            cities_label=cities_label,
            report_path=report_path,
        ))
        return 0
    except Exception as exc:
        safe_err = _safe_exc_str(exc)
        log.exception("run.failed", city=city.name, error=safe_err)
        _finish_run(conn, run_id, status="failed", error_message=safe_err)
        asyncio.run(notify_failure(
            app_name=cfg.report.app_name, run_id=run_id, error=f"[{city.name}] {safe_err}",
        ))
        paths["reports"].mkdir(parents=True, exist_ok=True)
        fail_path = paths["reports"] / f"{datetime.now(UTC).strftime('%Y-%m-%d')}-{city.name}.FAILED.md"
        fail_path.write_text(f"# Run failed\n\nrun_id: {run_id}\ncity: {city.name}\nerror: {safe_err}\n", encoding="utf-8")
        return 1


def run_once(cfg: Config, profile: Profile, conn: sqlite3.Connection, paths: dict[str, Path]) -> int:
    """Run one independent pipeline per target city. One city failing does not
    abort the others; returns 0 only if every city succeeded."""
    rc = 0
    for city in profile.search.cities:
        rc |= _run_city(cfg, profile, city, conn, paths)
    return rc
