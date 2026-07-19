"""
Property AI Analyst — per-property qualitative analysis for top-N scored listings.

Calls gpt-5.4-mini (reasoning; override with SCOUT_ANALYST_MODEL) via the
OpenAI API. Silently skips if OPENAI_API_KEY is not set. The system prompt is
built from the profile-driven ``agent_instructions/property_analyst.md``
template (see ``prompt_builder.build_system_prompt``).
"""
import asyncio
import os

import httpx
import structlog

from scout.core.analyse.prompt_builder import build_system_prompt
from scout.core.models import ScoredListing
from scout.core.profile import Profile

log = structlog.get_logger("analyst")

_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
# Newest mini-tier reasoning model ($0.75/$4.50 per 1M tok as of 2026-07) —
# ~$0.005/property at analyst volumes. Override with SCOUT_ANALYST_MODEL.
_MODEL = "gpt-5.4-mini"
_REASONING_EFFORT = "low"


def _model() -> str:
    return os.environ.get("SCOUT_ANALYST_MODEL") or _MODEL

_DIM_LABELS = {
    "price": "precio",
    "location": "localización",
    "commute": "desplazamiento",
    "legal": "legal/catastral",
    "regulatory": "regulatorio",
    "environmental": "ambiental",
    "neighbourhood": "vecindario",
    "infrastructure": "infraestructura",
}


def _build_prompt(s: ScoredListing) -> str:
    l = s.listing
    price_psqm = round(l.price_eur / l.size_m2) if l.size_m2 else 0
    dims = "; ".join(
        f"{_DIM_LABELS[k]}: {v:.1f}"
        for k, v in s.dim_scores.items()
        if v is not None
    )
    desc_snippet = (l.description or "")[:400].replace("\n", " ")
    lines = [
        f"**Propiedad:** {l.municipality}, {l.province}",
        f"**Precio:** {l.price_eur:,} € · {l.size_m2} m² · {price_psqm:,} €/m²",
        f"**Parcela:** {f'{l.plot_m2:,} m²' if l.plot_m2 else '—'}",
        f"**Habitaciones:** {l.bedrooms} hab / {l.bathrooms} baños",
        f"**En mercado:** {l.days_on_market or '?'} días",
        f"**Puntuación compuesta:** {s.composite:.2f}/10",
        f"**Dimensiones:** {dims}",
    ]
    if desc_snippet:
        lines.append(f"**Descripción (extracto):** {desc_snippet}")
    return "\n".join(lines)


def _split_summary(text: str) -> tuple[str, str]:
    """Split the model output into (summary_paragraph, detailed_analysis).

    The model is asked to lead with a ``SUMMARY: ...`` (or ``RESUMEN: ...`` for
    the Spanish template) paragraph. We pull that paragraph out for the
    Telegram card and keep the detailed remainder for the report. If neither
    marker is present, the summary falls back to the first paragraph and the
    full text is kept as the analysis.
    """
    markers = ("SUMMARY:", "RESUMEN:")
    idx = -1
    marker = ""
    for m in markers:
        idx = text.find(m)
        if idx != -1:
            marker = m
            break
    if idx == -1:
        summary = text.split("\n\n", 1)[0].strip()
        return summary, text
    after = text[idx + len(marker):].lstrip()
    parts = after.split("\n\n", 1)
    summary = parts[0].strip()
    detail = parts[1].strip() if len(parts) > 1 else ""
    return summary, detail


async def _analyse_one(
    s: ScoredListing,
    client: httpx.AsyncClient,
    api_key: str,
    system_prompt: str,
) -> None:
    payload = {
        "model": _model(),
        "max_completion_tokens": 1500,
        "reasoning_effort": _REASONING_EFFORT,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": _build_prompt(s)},
        ],
    }
    try:
        resp = await client.post(
            _OPENAI_URL,
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=90.0,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"].strip()
        s.summary_md, s.analyst_md = _split_summary(text)
        usage = data.get("usage", {})
        log.debug("analyst.done", property_id=s.property_id,
                  tokens_out=usage.get("completion_tokens"))
    except Exception as exc:
        log.warning("analyst.failed", property_id=s.property_id, error=str(exc))
        s.analyst_md = ""
        s.summary_md = ""


async def analyse_top(top: list[ScoredListing], profile: Profile) -> None:
    """Populate analyst_md on each ScoredListing in place.

    Silently no-ops if OPENAI_API_KEY is absent.
    """
    if not top:
        return
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        log.info("analyst.skip", reason="OPENAI_API_KEY not set")
        return

    system_prompt = build_system_prompt("property_analyst", profile)
    async with httpx.AsyncClient() as client:
        await asyncio.gather(
            *[_analyse_one(s, client, api_key, system_prompt) for s in top]
        )

    log.info("analyst.complete", count=len(top))
