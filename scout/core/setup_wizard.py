"""Interactive setup wizard: builds and writes profile.yaml."""
from pathlib import Path

import yaml

from scout.core.profile import Profile, ProfileBuyer, ProfileCity, ProfileSearch


def build_profile(a: dict) -> Profile:
    search = ProfileSearch(
        cities=[ProfileCity(**c) for c in a["cities"]],
        price_min_eur=a["price_min_eur"],
        price_max_eur=a["price_max_eur"],
        property_type=a["property_type"],
        preferred_plot_m2=a.get("preferred_plot_m2", 1000),
    )
    buyer = ProfileBuyer(
        household=a.get("household", ""),
        purpose=a.get("purpose", ""),
        top_priorities=a.get("top_priorities", []),
        investment_angle=bool(a.get("investment_angle", False)),
        investment_notes=a.get("investment_notes", ""),
        must_haves=a.get("must_haves", []),
        deal_breakers=a.get("deal_breakers", []),
        response_language=a.get("response_language", "es"),
        extra_notes=a.get("extra_notes", ""),
    )
    return Profile(country=a["country"], portal=a["portal"], search=search, buyer=buyer)


def write_profile(profile: Profile, path: Path | str) -> None:
    Path(path).write_text(
        yaml.safe_dump(profile.model_dump(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def run_wizard(input_fn=input, path: Path | str = "profile.yaml") -> Profile:
    def ask(label, default=""):
        val = input_fn(f"{label}{f' [{default}]' if default else ''}: ").strip()
        return val or default

    print("== Configuración personal de Housing Scout ==")
    country = ask("País (código)", "es")
    portal = ask("Portal", "idealista")
    cities = []
    print("Añade ciudades objetivo (deja el nombre en blanco para terminar):")
    while True:
        name = ask("  Ciudad")
        if not name:
            break
        cities.append({
            "name": name,
            "lat": float(ask("  lat")),
            "lon": float(ask("  lon")),
            "radius_km": float(ask("  radio km", "30")),
        })
    answers = {
        "country": country, "portal": portal, "cities": cities,
        "price_min_eur": int(ask("Precio mínimo €", "100000")),
        "price_max_eur": int(ask("Precio máximo €", "200000")),
        "property_type": ask("Tipo de propiedad", "vivienda_unifamiliar"),
        "preferred_plot_m2": int(ask("Parcela preferida m²", "1000")),
        "household": ask("Describe tu hogar/perfil"),
        "purpose": ask("Propósito", "primary_residence"),
        "top_priorities": [p for p in ask("Prioridades (coma)").split(",") if p.strip()],
        "investment_angle": ask("¿Ángulo de inversión? (si/no)", "no").lower().startswith("s"),
        "investment_notes": ask("Notas de inversión"),
        "must_haves": [m for m in ask("Imprescindibles (coma)").split(",") if m.strip()],
        "deal_breakers": [d for d in ask("Descartes (coma)").split(",") if d.strip()],
        "response_language": ask("Idioma de respuesta IA", "es"),
        "extra_notes": ask("Notas extra para la IA"),
    }
    profile = build_profile(answers)
    write_profile(profile, path)
    print(f"Perfil guardado en {path}")
    return profile
