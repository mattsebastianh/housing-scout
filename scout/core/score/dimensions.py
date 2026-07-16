import math
from typing import Optional

from scout.core.models import EnrichedListing


def _clamp(x: float, lo: float = 0.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, x))


def plot_bonus(plot_m2: Optional[int], threshold: int = 600, max_bonus: float = 0.3) -> float:
    """Composite bonus rewarding a large plot — a family preference.

    Returns ``max_bonus`` once the plot reaches ``threshold`` m², ramps linearly
    from half the threshold up to it, and ``0.0`` when the plot is unknown
    (so missing data is never penalised). This nudges ranking without disturbing
    the weighted 8-dimension model.
    """
    if not plot_m2 or plot_m2 <= 0:
        return 0.0
    if plot_m2 >= threshold:
        return max_bonus
    half = threshold / 2
    if plot_m2 <= half:
        return 0.0
    return round(max_bonus * (plot_m2 - half) / (threshold - half), 3)


def score_price(item: EnrichedListing, zone: Optional[dict]) -> Optional[float]:
    if zone is None or zone.get("price_psqm") is None:
        return None
    l = item.listing
    if not l.size_m2:
        return None
    price_psqm = l.price_eur / l.size_m2
    delta = (price_psqm - zone["price_psqm"]) / zone["price_psqm"]
    raw = _clamp(5 - 50 * delta)
    bonus = 1.0 if (l.days_on_market or 0) > 90 else 0.0
    return _clamp(raw + bonus)


def _tier(pop: int) -> float:
    if pop >= 250_000:
        return 10.0
    if pop >= 20_000:
        return 7.0
    return 4.0


def score_location(item: EnrichedListing, *, municipality_population: int) -> Optional[float]:
    osm = item.enrichments.get("osm") or {}
    amenities = osm.get("amenities_5km") or {}
    if not amenities:
        return None
    # Default amenity mix: urban livability — shops and parks alongside healthcare; schools secondary
    school_score = _clamp(amenities.get("school", 0) * 2.5)
    healthcare_score = _clamp(amenities.get("healthcare_total", 0) * 2.0)
    shop_score = _clamp(amenities.get("supermarket", 0) * 2.5)
    park_score = _clamp(amenities.get("park", 0) * 2.0)
    amenity = (0.20 * school_score + 0.25 * healthcare_score
               + 0.30 * shop_score + 0.25 * park_score)
    tier = _tier(municipality_population)
    return _clamp(0.40 * tier + 0.60 * amenity)


def score_commute(item: EnrichedListing, *, motorway_km: Optional[float]) -> Optional[float]:
    osrm = item.enrichments.get("osrm") or {}
    osm = item.enrichments.get("osm") or {}
    if "drive_min" not in osrm:
        return None
    drive_min = osrm["drive_min"]
    drive_score = _clamp(10 - (drive_min - 20) / 4)
    station_km = osm.get("nearest_station_km")
    station_score = 10 if station_km is not None and station_km <= 1.5 \
        else 5 if station_km is not None and station_km <= 3 else 0
    motorway_score = 10 if motorway_km is not None and motorway_km <= 5 \
        else 5 if motorway_km is not None and motorway_km <= 10 else 0
    return _clamp(0.5 * drive_score + 0.3 * station_score + 0.2 * motorway_score)


def score_legal(item: EnrichedListing, *, urbanistic_class: Optional[str]) -> Optional[float]:
    cat = item.enrichments.get("catastro") or {}
    base = 10.0
    if cat:
        use = (cat.get("use_code") or "")
        # Catastro `luso` is the human-readable use ("Residencial", "Industrial",
        # …) on the live JSON service; older captures used the single-char "V".
        # A non-residential primary-use code is a legal red flag for a home.
        is_residential = use == "V" or use.lower().startswith("residencial")
        if use and not is_residential:
            base -= 3
        if cat.get("year_built") is None:
            base -= 1
    if urbanistic_class == "no urbanizable":
        base -= 2
    elif urbanistic_class == "urbanizable":
        base -= 1
    return _clamp(base)


def score_regulatory(item: EnrichedListing, *, in_tensa: bool, recent_boe_hit: bool) -> Optional[float]:
    base = 10.0
    if in_tensa:
        base -= 4
    if recent_boe_hit:
        base -= 2
    return _clamp(base)


def score_environmental(item: EnrichedListing) -> Optional[float]:
    parts: list[float] = []
    flood = (item.enrichments.get("flood") or {}).get("return_period")
    if flood is not None:
        parts.append({"none": 10, "T500": 7, "T100": 4, "T10": 0}.get(flood, 5))
    wf = (item.enrichments.get("wildfire") or {}).get("hazard_class")
    if wf is not None:
        parts.append(_clamp(10 - (wf - 1) * 2.5))
    noise_db = (item.enrichments.get("noise") or {}).get("lden_db")
    if noise_db is not None:
        parts.append(
            10 if noise_db < 55 else 7 if noise_db < 65 else 4 if noise_db < 75 else 0
        )
    air_no2 = (item.enrichments.get("air") or {}).get("no2_avg")
    if air_no2 is not None:
        parts.append(_clamp(10 - (air_no2 - 10) / 3))
    if not parts:
        return None
    return _clamp(sum(parts) / len(parts))


def score_neighbourhood(
    item: EnrichedListing, *, primary_residence_pct: Optional[float], investment_hits: int
) -> Optional[float]:
    osm = item.enrichments.get("osm") or {}
    amenities = osm.get("amenities_5km") or {}
    shops = amenities.get("supermarket", 0)
    schools = amenities.get("school", 0)
    parks = amenities.get("park", 0)

    primary_score = (primary_residence_pct / 10) if primary_residence_pct is not None else None
    commercial_score = _clamp(math.log10(1 + shops * 4) * 5)
    # Schools and parks are key for family neighbourhood quality
    school_score = _clamp(schools * 2.5)
    park_score = _clamp(parks * 3.0)
    # High investment/tourism activity signals an unstable neighbourhood for families
    stability_score = _clamp(10 - investment_hits * 2)

    have_data = primary_score is not None or shops or schools or parks
    if not have_data:
        return None

    parts: list[tuple[str, float, float]] = []
    if primary_score is not None:
        parts.append(("p", 0.25, primary_score))
    parts.append(("school", 0.30, school_score))
    parts.append(("park", 0.15, park_score))
    parts.append(("commercial", 0.20, commercial_score))
    parts.append(("stability", 0.10, stability_score))
    w_total = sum(w for _, w, _ in parts)
    return _clamp(sum(w * v for _, w, v in parts) / w_total)


def score_infrastructure(item: EnrichedListing) -> Optional[float]:
    osm = item.enrichments.get("osm") or {}
    broadband = (item.enrichments.get("broadband") or {}).get("over_100mbps")
    amenities = osm.get("amenities_5km") or {}
    schools = amenities.get("school", 0)
    stations_km = osm.get("nearest_station_km")
    nearest_school_km = osm.get("nearest_school_km")
    nearest_health_km = osm.get("nearest_health_km")

    have_any = (broadband is not None or stations_km is not None
                or schools or nearest_health_km is not None)
    if not have_any:
        return None

    broadband_score = 10 if broadband else 5

    transit_score = (
        10 if stations_km is not None and stations_km < 1
        else 7 if stations_km is not None and stations_km < 3
        else 3
    )
    # Nearest school walking distance is a hard family requirement
    school_score = (
        10 if nearest_school_km is not None and nearest_school_km < 0.8
        else 8 if nearest_school_km is not None and nearest_school_km < 2.0
        else 5 if nearest_school_km is not None and nearest_school_km < 4.0
        else _clamp(schools * 2.5)  # fallback to count if no distance
    )
    # Nearest health centre (clinic / hospital)
    health_score = (
        10 if nearest_health_km is not None and nearest_health_km < 2.0
        else 7 if nearest_health_km is not None and nearest_health_km < 5.0
        else 4
    )
    return _clamp(
        0.20 * broadband_score
        + 0.20 * transit_score
        + 0.35 * school_score
        + 0.25 * health_score
    )
