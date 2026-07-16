"""Profile-driven system prompt builder.

Loads editable Markdown templates from ``agent_instructions/`` and fills them
with values from the buyer's :class:`~scout.core.profile.Profile` — no
personal or city literals live in code; they arrive only at runtime.
"""
from pathlib import Path

from scout.core.profile import Profile, ProfileBuyer

_DIR = Path(__file__).resolve().parents[3] / "agent_instructions"


def _template_path(name: str) -> Path:
    local = _DIR / f"{name}.local.md"
    return local if local.is_file() else _DIR / f"{name}.md"


def compose_buyer_profile(buyer: ProfileBuyer) -> str:
    lines: list[str] = []
    if buyer.household:
        lines.append(f"Hogar: {buyer.household}")
    if buyer.purpose:
        lines.append(f"Propósito: {buyer.purpose}")
    if buyer.top_priorities:
        lines.append("Prioridades: " + ", ".join(buyer.top_priorities))
    if buyer.investment_angle:
        note = f" ({buyer.investment_notes})" if buyer.investment_notes else ""
        lines.append(f"Inversión: sí{note}")
    if buyer.must_haves:
        lines.append("Imprescindibles: " + "; ".join(buyer.must_haves))
    if buyer.deal_breakers:
        lines.append("Descartes: " + "; ".join(buyer.deal_breakers))
    if buyer.extra_notes:
        lines.append(buyer.extra_notes.strip())
    return "\n".join(lines)


def build_system_prompt(name: str, profile: Profile) -> str:
    template = _template_path(name).read_text(encoding="utf-8")
    s = profile.search
    repl = {
        "{cities}": ", ".join(c.name for c in s.cities),
        "{price_min}": f"{s.price_min_eur:,}".replace(",", "."),
        "{price_max}": f"{s.price_max_eur:,}".replace(",", "."),
        "{property_type}": s.property_type,
        "{preferred_plot_m2}": str(s.preferred_plot_m2),
        "{buyer_profile}": compose_buyer_profile(profile.buyer),
        "{response_language}": profile.buyer.response_language,
    }
    for k, v in repl.items():
        template = template.replace(k, v)
    return template
