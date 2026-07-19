#!/usr/bin/env python3
"""Daily entry point for the property scouting agent."""
import argparse
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from scout.core.config import load_config
from scout.core.db import connect, migrate
from scout.core.logging_setup import setup_logging
from scout.core.profile import load_profile, profile_exists

PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")


def _paths(cfg) -> dict[str, Path]:
    db_path = Path(os.environ.get("SCOUT_DB_PATH", PROJECT_ROOT / "data" / "scout.db"))
    log_dir = Path(os.environ.get("SCOUT_LOG_DIR", PROJECT_ROOT / "logs"))
    log_path = log_dir / f"run-{date.today().isoformat()}.log"
    reports_dir = PROJECT_ROOT / cfg.report.output_dir
    return {"db": db_path, "log": log_path, "reports": reports_dir}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="Load config, init DB, log a heartbeat, exit. Do not run pipeline.",
    )
    parser.add_argument(
        "--config",
        default=str(PROJECT_ROOT / "config.yaml"),
    )
    parser.add_argument(
        "--profile",
        default=str(PROJECT_ROOT / "profile.yaml"),
    )
    parser.add_argument(
        "--city",
        action="append",
        dest="cities",
        help="Run only this city (repeatable). Default: all configured cities.",
    )
    args = parser.parse_args()

    if not profile_exists(args.profile):
        print(
            f"No profile found at {args.profile}. Run:  python -m scout setup",
            file=sys.stderr,
        )
        return 2

    cfg = load_config(args.config)
    profile = load_profile(args.profile)
    if args.cities:
        wanted = {c.lower() for c in args.cities}
        known = {c.name for c in profile.search.cities}
        unknown = wanted - known
        if unknown:
            print(
                f"Unknown city: {', '.join(sorted(unknown))}. "
                f"Configured: {', '.join(sorted(known))}",
                file=sys.stderr,
            )
            return 2
        profile = profile.model_copy(update={
            "search": profile.search.model_copy(update={
                "cities": [c for c in profile.search.cities if c.name in wanted]
            })
        })
    paths = _paths(cfg)
    setup_logging(paths["log"])

    conn = connect(paths["db"])
    migrate(conn)

    print(f"Config loaded. Cities: {', '.join(c.name for c in profile.search.cities)}")
    print(f"Price range: {profile.search.price_min_eur:,} – {profile.search.price_max_eur:,} €")
    print(f"DB ready: {paths['db']}")
    print(f"Log: {paths['log']}")

    if args.check:
        return 0

    from scout.core import runlock
    from scout.core.orchestrate import run_once

    lock_path = paths["db"].parent / "run.lock"
    try:
        with runlock.hold(lock_path):
            return run_once(cfg, profile, conn, paths)
    except runlock.LockHeld:
        print(f"Another run is already in progress ({lock_path}).", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
