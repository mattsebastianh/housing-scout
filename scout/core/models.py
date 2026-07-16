from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Optional


@dataclass
class Listing:
    portal: Literal["idealista", "fotocasa"]
    external_id: str
    city: str
    url: str
    price_eur: int
    size_m2: int
    bedrooms: int
    bathrooms: int
    municipality: Optional[str]
    province: Optional[str]
    address: Optional[str]
    lat: Optional[float]
    lon: Optional[float]
    description: str
    days_on_market: int
    cadastral_ref: Optional[str]
    raw_json: str
    first_seen_at: datetime
    plot_m2: Optional[int] = None


@dataclass
class EnrichedListing:
    listing: Listing
    property_id: Optional[int] = None
    enrichments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScoredListing:
    listing: Listing
    dim_scores: dict[str, Optional[float]]
    composite: float
    positives_md: str = ""
    risks_md: str = ""
    analyst_md: str = ""
    summary_md: str = ""
    property_id: Optional[int] = None
    distance_km: Optional[float] = None
    drive_min: Optional[int] = None
