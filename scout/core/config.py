import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator


class Scrape(BaseModel):
    # Which transport fetches Idealista results: "scrapeops" (HTML via the
    # ScrapeOps proxy, SCRAPEOPS_API_KEY) or "brightdata" (structured records
    # from a Bright Data collector run, BRIGHTDATA_API_KEY).
    provider: Literal["scrapeops", "brightdata"] = "scrapeops"
    # Bright Data Scrapers collector to trigger; required when provider is
    # "brightdata" (not a secret — the account API key is the credential).
    brightdata_collector_id: str | None = None
    pages: int = Field(default=1, gt=0, le=10)  # pages to fetch per city (1 page ≈ 25–30 listings)
    delay_ms: int = Field(default=3000, gt=0)
    # Fetch a reported listing's detail page to fill bathrooms (and any missing
    # bedrooms/plot) that Idealista result cards omit. Costs one extra ScrapeOps
    # request per fetched listing — disable to save credits.
    fetch_details: bool = True
    # Cap how many of the top-N listings get a detail fetch (recommended: the
    # top 5, which match the listings surfaced in the Telegram summary). 0 = none.
    details_limit: int = Field(default=5, ge=0)

    @model_validator(mode="after")
    def _collector_required(self) -> "Scrape":
        if self.provider == "brightdata" and not self.brightdata_collector_id:
            raise ValueError(
                "scrape.brightdata_collector_id is required when "
                "scrape.provider is 'brightdata' — set it in config.yaml "
                "or via the BRIGHTDATA_COLLECTOR_ID env var"
            )
        return self


class Report(BaseModel):
    language: Literal["es", "en"] = "es"
    top_n: int = Field(gt=0, le=50)
    output_dir: str
    timezone: str
    app_name: str = "Housing Scout"


class Weights(BaseModel):
    price: float
    location: float
    commute: float
    legal: float
    regulatory: float
    environmental: float
    neighbourhood: float
    infrastructure: float


class Scoring(BaseModel):
    weights: Weights

    @model_validator(mode="after")
    def _sum_to_one(self) -> "Scoring":
        total = sum(self.weights.model_dump().values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"weights must sum to 1.0, got {total}")
        return self


class RunSchedule(BaseModel):
    hour: int = Field(ge=0, le=23)
    minute: int = Field(ge=0, le=59)


class Config(BaseModel):
    scrape: Scrape
    report: Report
    scoring: Scoring
    run: RunSchedule


def load_config(path: Path | str) -> Config:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    # Deploy-specific value kept out of the committed config: the env var
    # (usually from .env) takes precedence over any value in config.yaml.
    env_collector = os.environ.get("BRIGHTDATA_COLLECTOR_ID")
    if env_collector:
        raw.setdefault("scrape", {})["brightdata_collector_id"] = env_collector
    return Config.model_validate(raw)
