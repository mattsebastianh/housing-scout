"""Telegram Bot notifications for daily run results."""

import os
import re
from collections import Counter
from pathlib import Path
from typing import Optional

import httpx
import structlog

from scout.core.models import ScoredListing

log = structlog.get_logger("notify.telegram")

_API = "https://api.telegram.org/bot{token}/{method}"
_MAX_TOP = 5  # listings to include in the Telegram message


def _credentials() -> tuple[Optional[str], Optional[str]]:
    return os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")


def _escape(text: str) -> str:
    """Escape special chars for Telegram HTML — just enough for our use."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _price(p: Optional[int]) -> str:
    if p is None:
        return "—"
    return f"{p:,.0f} €".replace(",", ".")


def _summary_paragraph(s: ScoredListing) -> str:
    """Short summary paragraph for a listing's Telegram card.

    Prefers the AI analyst's ``summary_md``; falls back to the first few
    sentences of the listing description when the analyst did not run.
    """
    text = (s.summary_md or "").strip()
    if not text:
        desc = (s.listing.description or "").strip()
        if not desc:
            return ""
        sentences = re.split(r"(?<=[.!?])\s+", desc)
        text = " ".join(sentences[:3]).strip()
    return text[:400].rstrip()


async def _post(
    client: httpx.AsyncClient,
    token: str,
    chat_id: str,
    html: str,
    reply_markup: Optional[dict] = None,
) -> None:
    url = _API.format(token=token, method="sendMessage")
    payload: dict = {"chat_id": chat_id, "text": html, "parse_mode": "HTML",
                     "disable_web_page_preview": True}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        resp = await client.post(
            url,
            json=payload,
            timeout=15,
        )
        if resp.status_code != 200:
            log.warning("telegram.error", status=resp.status_code, body=resp.text[:200])
        else:
            log.info("telegram.sent")
    except httpx.RequestError as exc:
        log.warning("telegram.transport.failed", error=type(exc).__name__)
        raise


async def _send_document(
    client: httpx.AsyncClient, token: str, chat_id: str, path: Path
) -> None:
    url = _API.format(token=token, method="sendDocument")
    mime = "application/pdf" if path.suffix == ".pdf" else "text/markdown"
    files = {"document": (path.name, path.read_bytes(), mime)}
    data = {"chat_id": chat_id, "caption": f"📄 Informe {path.stem}"}
    try:
        resp = await client.post(url, data=data, files=files, timeout=30)
        if resp.status_code != 200:
            log.warning("telegram.document.error", status=resp.status_code, body=resp.text[:200])
        else:
            log.info("telegram.document.sent", filename=path.name)
    except Exception as exc:
        log.warning("telegram.document.failed", error=str(exc))


def _build_success_message(
    *,
    app_name: str,
    run_id: int,
    fetched: int,
    excluded: Counter,
    new_total: int,
    reported_total: int,
    top: list[ScoredListing],
    price_min: int,
    price_max: int,
    cities_label: str,
) -> str:
    excluded_total = sum(excluded.values())
    top_reason = excluded.most_common(1)[0][0] if excluded else "—"

    lines = [
        f"🏠 <b>{_escape(app_name)} — Informe</b>",
        "",
        f"🏙 Ciudades: <b>{_escape(cities_label)}</b>",
        f"💶 Rango objetivo: <b>{_price(price_min)} – {_price(price_max)}</b>",
        "",
        "📊 <b>Resumen del scrape</b>",
        f"• Anuncios obtenidos: <b>{fetched}</b>",
        f"• Excluidos: <b>{excluded_total}</b>  (principal: {_escape(top_reason)})",
        f"• Nuevas propiedades: <b>{new_total}</b>",
        f"• Incluidas en informe: <b>{reported_total}</b>",
    ]

    if top:
        lines += ["", f"🏆 <b>Top {min(len(top), _MAX_TOP)} propiedades</b> — detalle a continuación ⬇️"]
    else:
        lines += ["", "ℹ️ Sin propiedades nuevas en rango este ciclo."]

    lines += [
        "",
        f"🆔 Run #{run_id}",
    ]

    return "\n".join(lines)


def _build_property_message(rank: int, s: ScoredListing) -> tuple[str, dict]:
    """One self-contained Telegram card per property, plus its inline keyboard.

    Returns the HTML message body and a ``reply_markup`` dict with a single
    'Ver anuncio' URL button, so the listing opens with one tap instead of
    relying on an in-text link.
    """
    l = s.listing
    loc = ", ".join(p for p in [l.municipality, l.province] if p) or l.city
    score_bar = "█" * round(s.composite) + "░" * (10 - round(s.composite))

    lines = [
        f"🏡 <b>{rank}. {_escape(loc)}</b>",
        "",
        f"💶 <b>{_price(l.price_eur)}</b>  📐 {l.size_m2 or '—'} m²  "
        f"🛏 {l.bedrooms or '—'}  🚿 {l.bathrooms or '—'}",
    ]
    if l.plot_m2:
        lines.append(f"🌳 Parcela: {l.plot_m2:,} m²".replace(",", "."))
    lines.append(f"⭐ <b>{s.composite:.1f}/10</b>  {score_bar}")
    dist_parts = []
    if s.distance_km is not None:
        dist_parts.append(f"📍 {s.distance_km:.0f} km al centro")
    if s.drive_min is not None:
        dist_parts.append(f"🚗 {s.drive_min} min")
    if dist_parts:
        lines.append("  ".join(dist_parts))
    summary = _summary_paragraph(s)
    if summary:
        lines += ["", f"💬 <i>{_escape(summary)}</i>"]

    portal_label = "Idealista" if l.portal == "idealista" else l.portal.capitalize()
    keyboard = {
        "inline_keyboard": [[{"text": f"🔗 Ver anuncio en {portal_label}", "url": l.url}]]
    }
    return "\n".join(lines), keyboard


def _build_failure_message(*, app_name: str, run_id: int, error: str) -> str:
    return "\n".join([
        f"🚨 <b>{_escape(app_name)} — Error en el ciclo</b>",
        "",
        f"🆔 Run #{run_id}",
        f"❌ <code>{_escape(error[:400])}</code>",
        "",
        "Revisa los logs para más detalles.",
    ])


async def notify_success(
    *,
    app_name: str,
    run_id: int,
    fetched: int,
    excluded: Counter,
    new_total: int,
    reported_total: int,
    top: list[ScoredListing],
    price_min: int,
    price_max: int,
    cities_label: str,
    report_path: Optional[Path] = None,
) -> None:
    token, chat_id = _credentials()
    if not token or not chat_id:
        log.debug("telegram.skipped", reason="TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")
        return
    html = _build_success_message(
        app_name=app_name,
        run_id=run_id, fetched=fetched, excluded=excluded,
        new_total=new_total, reported_total=reported_total,
        top=top, price_min=price_min, price_max=price_max,
        cities_label=cities_label,
    )
    async with httpx.AsyncClient() as client:
        await _post(client, token, chat_id, html)
        for rank, s in enumerate(top[:_MAX_TOP], 1):
            card_html, keyboard = _build_property_message(rank, s)
            await _post(client, token, chat_id, card_html, reply_markup=keyboard)
        if report_path and report_path.exists():
            await _send_document(client, token, chat_id, report_path)


async def notify_failure(*, app_name: str, run_id: int, error: str) -> None:
    token, chat_id = _credentials()
    if not token or not chat_id:
        log.debug("telegram.skipped", reason="TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")
        return
    html = _build_failure_message(app_name=app_name, run_id=run_id, error=error)
    async with httpx.AsyncClient() as client:
        await _post(client, token, chat_id, html)
