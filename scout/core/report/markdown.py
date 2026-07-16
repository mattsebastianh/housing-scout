from datetime import datetime
from pathlib import Path
from typing import Callable

from jinja2 import Environment, FileSystemLoader, select_autoescape

from scout.core.models import ScoredListing

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_env = Environment(loader=FileSystemLoader(_TEMPLATE_DIR), autoescape=select_autoescape([]))

_DIM_LABELS = {
    "price": "Eficiencia de precio",
    "location": "Localización",
    "commute": "Conmutación",
    "legal": "Legal / catastral",
    "regulatory": "Riesgo regulatorio",
    "environmental": "Riesgo ambiental",
    "neighbourhood": "Vecindario",
    "infrastructure": "Infraestructura",
}

_SPANISH_MONTHS = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio",
    7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre",
}


def _human_date(d: datetime) -> str:
    return f"{d.day} de {_SPANISH_MONTHS[d.month]} de {d.year}"


def _card(scored: ScoredListing, zone_lookup: Callable) -> dict:
    l = scored.listing
    zone = zone_lookup(l) or {}
    price_psqm = round(l.price_eur / l.size_m2) if l.size_m2 else 0
    dim_rows = []
    for k, label in _DIM_LABELS.items():
        v = scored.dim_scores.get(k)
        dim_rows.append({
            "label": label,
            "value": "No disponible" if v is None else f"{v:.1f} / 10",
        })
    return {
        "municipality": l.municipality,
        "province": l.province,
        "zone_class": zone.get("zone_class", "—"),
        "portal_label": "Idealista" if l.portal == "idealista" else "Fotocasa",
        "first_seen": l.first_seen_at.strftime("%Y-%m-%d"),
        "price": l.price_eur,
        "size_m2": l.size_m2,
        "plot_m2": l.plot_m2,
        "price_psqm": price_psqm,
        "bedrooms": l.bedrooms,
        "bathrooms": l.bathrooms,
        "composite": scored.composite,
        "distance_km": scored.distance_km,
        "drive_min": scored.drive_min,
        "dim_rows": dim_rows,
        "positives_md": scored.positives_md,
        "risks_md": scored.risks_md,
        "analyst_md": scored.analyst_md,
        "legal_status": zone.get("legal_status", "—"),
        "market_context": zone.get("market_context", "—"),
        "url": l.url,
    }


def render_report(
    *,
    scored: list[ScoredListing],
    run_id: int,
    app_name: str = "Housing Scout",
    generated_at: datetime,
    report_date: datetime,
    cities_label: str,
    price_min: int,
    price_max: int,
    top_n: int,
    summary: dict,
    zone_lookup: Callable,
) -> str:
    tpl = _env.get_template("daily.md.j2")
    return tpl.render(
        app_name=app_name,
        run={
            "id": run_id,
            "generated_at": generated_at.strftime("%Y-%m-%d %H:%M"),
            "human_date": _human_date(report_date),
            "new_total": summary["new_total"],
            "reported_total": summary["reported_total"],
        },
        top_n=top_n,
        cities_label=cities_label,
        price_min=price_min,
        price_max=price_max,
        cards=[_card(s, zone_lookup) for s in scored],
        summary=summary,
    )


def write_report(text: str, output_dir: Path, report_date: datetime, slug: str | None = None) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = f"-{slug}" if slug else ""
    path = output_dir / f"{report_date.strftime('%Y-%m-%d')}{suffix}.md"
    path.write_text(text, encoding="utf-8")
    return path
