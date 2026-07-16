#!/usr/bin/env python3
"""
Test Idealista scrape for one or more cities without writing to the DB.
Usage:
  .venv/bin/python scripts/manual_scrape.py
  .venv/bin/python scripts/manual_scrape.py --city barcelona
  .venv/bin/python scripts/manual_scrape.py --city valencia
"""
import argparse
import sys
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

sys.path.insert(0, str(PROJECT_ROOT))

from scout.core.config import load_config
from scout.core.profile import load_profile, profile_exists
from scout.core.scrape.base import scrape_listings
from scout.core.filter.hard_excl import check_listing


def scrape_city(city_name: str, cfg, profile) -> None:
    city = next((c for c in profile.search.cities if c.name == city_name), None)
    if city is None:
        print(f"City '{city_name}' not in profile. Available: {[c.name for c in profile.search.cities]}")
        return

    print(f"\n=== IDEALISTA / {city_name.upper()} (provider: {cfg.scrape.provider}) ===")
    print(f"Price range: {profile.search.price_min_eur:,}–{profile.search.price_max_eur:,} €")
    print(f"Pages: {cfg.scrape.pages}  delay_ms: {cfg.scrape.delay_ms}")
    print("Running scrape… (this may take a few minutes)")

    listings = scrape_listings(cfg, profile, city.name)

    print(f"Listings returned: {len(listings)}")

    in_range = []
    excluded = []
    for l in listings:
        exc = check_listing(l, price_min=profile.search.price_min_eur, price_max=profile.search.price_max_eur)
        if exc:
            excluded.append((l, exc))
        else:
            in_range.append(l)

    print(f"\nIN RANGE ({len(in_range)}):")
    for l in in_range[:10]:
        print(f"  [{l.portal}] {l.price_eur:,} € | {l.size_m2}m² | {l.bedrooms}hab | {l.municipality} | {l.url[:70]}")

    print(f"\nEXCLUDED ({len(excluded)}):")
    price_excluded = [l for l, e in excluded if "OUT_OF_PRICE_RANGE" in str(e.code)]
    other_excluded = [(l, e) for l, e in excluded if "OUT_OF_PRICE_RANGE" not in str(e.code)]

    prices = sorted(l.price_eur for l, _ in excluded if l.price_eur)
    if prices:
        print(f"  Price range of excluded: {min(prices):,} – {max(prices):,} €")
        print(f"  OUT_OF_PRICE_RANGE: {len(price_excluded)}")

    for l, e in other_excluded:
        print(f"  [{e.code}] {l.price_eur:,} € | {l.url[:60]}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", default=None, help="City name (default: all cities in profile)")
    parser.add_argument("--config", default=str(PROJECT_ROOT / "config.yaml"))
    parser.add_argument("--profile", default=str(PROJECT_ROOT / "profile.yaml"))
    args = parser.parse_args()

    cfg = load_config(args.config)
    profile_path = args.profile
    if not profile_exists(profile_path):
        profile_path = PROJECT_ROOT / "profile.example.yaml"
    profile = load_profile(profile_path)

    cities = [args.city] if args.city else [c.name for c in profile.search.cities]
    for city_name in cities:
        scrape_city(city_name, cfg, profile)


if __name__ == "__main__":
    main()
