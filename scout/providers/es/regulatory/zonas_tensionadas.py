"""
Static lookup for Spanish "zonas tensionadas" (stressed residential housing market zones).

Catalunya declared ~140 municipalities under the ZMRT (Zones de Mercat Residencial Tens)
via Resolució TER/3618/2022 and subsequent decrees. The Comunitat Valenciana has not
declared any as of 2025 (they opposed the national housing law politically), so all
Valencia-area listings correctly return False.

The set uses lowercase names to match against Listing.municipality (case-insensitive).
Leading articles (el/la/l'/els/les) are normalised away on both sides.
"""

import re

# Official Catalan ZMRT municipalities — lowercase, accent-preserving
_TENSA_SET: frozenset[str] = frozenset({
    # Barcelonès
    "barcelona", "badalona", "l'hospitalet de llobregat", "hospitalet de llobregat",
    "sant adrià de besòs", "santa coloma de gramenet",
    # Baix Llobregat
    "castelldefels", "cornellà de llobregat", "prat de llobregat", "el prat de llobregat",
    "esplugues de llobregat", "gavà", "molins de rei", "olesa de montserrat",
    "pallejà", "sant andreu de la barca", "sant boi de llobregat",
    "sant feliu de llobregat", "sant joan despí", "sant just desvern",
    "sant vicenç dels horts", "vallirana", "viladecans",
    # Vallès Occidental
    "barberà del vallès", "castellbisbal", "cerdanyola del vallès",
    "montcada i reixac", "ripollet", "rubí", "sabadell",
    "sant cugat del vallès", "terrassa", "ullastrell", "vacarisses", "viladecavalls",
    # Vallès Oriental
    "granollers", "la llagosta", "llagosta",
    "les franqueses del vallès", "franqueses del vallès",
    "mollet del vallès", "montmeló", "montornès del vallès",
    "parets del vallès", "santa perpètua de mogoda",
    # Maresme
    "alella", "arenys de mar", "arenys de munt", "argentona", "cabrils",
    "cabrera de mar", "caldes d'estrac", "masnou", "el masnou",
    "malgrat de mar", "mataró", "montgat", "pineda de mar",
    "premià de dalt", "premià de mar", "sant andreu de llavaneres",
    "sant vicenç de montalt", "teià", "tiana",
    "vilassar de dalt", "vilassar de mar",
    # Garraf
    "cunit", "cubelles", "sitges", "vilanova i la geltrú",
    # Alt Penedès
    "gelida", "olèrdola", "subirats", "vilafranca del penedès",
    # Osona
    "vic",
    # Bages
    "manresa",
    # Anoia
    "igualada",
})

_ARTICLE_RE = re.compile(r"^(el |la |l'|els |les )", re.IGNORECASE)


def _normalise(name: str) -> str:
    return _ARTICLE_RE.sub("", name.strip().lower())


def is_tensionada(municipality: str | None) -> bool:
    """Return True if the municipality is in a declared Spanish zona tensionada."""
    if not municipality:
        return False
    n = _normalise(municipality)
    if n in _TENSA_SET:
        return True
    # Also check the raw lowercase (covers names without a leading article)
    raw = municipality.strip().lower()
    return raw in _TENSA_SET
