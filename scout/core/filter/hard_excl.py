import math
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Optional

from scout.core.models import Listing


class ExclusionReason(StrEnum):
    OUT_OF_PRICE_RANGE = "OUT_OF_PRICE_RANGE"
    TOO_FAR = "TOO_FAR"
    OCUPAS = "OCUPAS"
    NUDA_PROPIEDAD = "NUDA_PROPIEDAD"
    LITIGIOUS = "LITIGIOUS"
    RESTRICTED_TITLE = "RESTRICTED_TITLE"
    UNVERIFIABLE = "UNVERIFIABLE"
    UNLICENSED_PARTY = "UNLICENSED_PARTY"


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


@dataclass
class Exclusion:
    code: ExclusionReason
    detail: str


_PATTERNS: list[tuple[ExclusionReason, re.Pattern[str]]] = [
    (
        ExclusionReason.OCUPAS,
        re.compile(
            r"\b(ocupa|ocupas|ocupado|ocupada|inquilino sin contrato|"
            r"situaci[oó]n especial|alquilado sin contrato|libre a convenir|"
            r"a tratar personalmente)\b",
            re.IGNORECASE,
        ),
    ),
    (
        ExclusionReason.NUDA_PROPIEDAD,
        re.compile(
            r"\b(nuda propiedad|usufructo vitalicio|usufructuario)\b",
            re.IGNORECASE,
        ),
    ),
    (
        ExclusionReason.LITIGIOUS,
        re.compile(
            r"\b(subasta|judicial|herencia litigiosa|concurso de acreedores)\b",
            re.IGNORECASE,
        ),
    ),
    (
        ExclusionReason.RESTRICTED_TITLE,
        re.compile(
            r"\b(derecho de tanteo|retracto|renting social|renta antigua|"
            r"alquiler social obligatorio)\b",
            re.IGNORECASE,
        ),
    ),
]


def check_listing(
    listing: Listing,
    *,
    price_min: int,
    price_max: int,
    centre_lat: Optional[float] = None,
    centre_lon: Optional[float] = None,
    radius_km: Optional[float] = None,
) -> Optional[Exclusion]:
    if listing.price_eur is None or not (price_min <= listing.price_eur <= price_max):
        return Exclusion(
            ExclusionReason.OUT_OF_PRICE_RANGE,
            f"price {listing.price_eur} outside [{price_min}, {price_max}]",
        )
    if (
        centre_lat is not None and centre_lon is not None and radius_km is not None
        and listing.lat is not None and listing.lon is not None
    ):
        dist = _haversine_km(centre_lat, centre_lon, listing.lat, listing.lon)
        if dist > radius_km:
            return Exclusion(
                ExclusionReason.TOO_FAR,
                f"{dist:.1f} km from city centre (limit {radius_km} km)",
            )
    desc = listing.description or ""
    for code, pattern in _PATTERNS:
        m = pattern.search(desc)
        if m:
            return Exclusion(code, f"matched '{m.group(0)}'")
    return None
