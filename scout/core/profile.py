from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator


class ProfileCity(BaseModel):
    name: str
    lat: float
    lon: float
    radius_km: float
    portal_slug: str | None = None


class ProfileSearch(BaseModel):
    cities: list[ProfileCity]
    price_min_eur: int = Field(gt=0)
    price_max_eur: int = Field(gt=0)
    property_type: str
    preferred_plot_m2: int = Field(default=1000, gt=0)

    @model_validator(mode="after")
    def _range(self) -> "ProfileSearch":
        if self.price_min_eur >= self.price_max_eur:
            raise ValueError("price_min_eur must be < price_max_eur")
        return self


class ProfileBuyer(BaseModel):
    household: str = ""
    purpose: str = ""
    top_priorities: list[str] = Field(default_factory=list)
    investment_angle: bool = False
    investment_notes: str = ""
    must_haves: list[str] = Field(default_factory=list)
    deal_breakers: list[str] = Field(default_factory=list)
    response_language: str = "es"
    extra_notes: str = ""


class Profile(BaseModel):
    country: str
    portal: str
    search: ProfileSearch
    buyer: ProfileBuyer = Field(default_factory=ProfileBuyer)


def load_profile(path: Path | str) -> Profile:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return Profile.model_validate(raw)


def profile_exists(path: Path | str) -> bool:
    return Path(path).is_file()
