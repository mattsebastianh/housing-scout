#!/usr/bin/env python3
"""Long-running Telegram listener: /scout messages trigger on-demand runs."""
import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from scout.core.logging_setup import setup_logging
from scout.core.profile import load_profile, profile_exists

PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--profile",
        default=str(PROJECT_ROOT / "profile.yaml"),
    )
    args = parser.parse_args()

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set.", file=sys.stderr)
        return 1

    if not profile_exists(args.profile):
        print(
            f"No profile found at {args.profile}. Run:  python -m scout setup",
            file=sys.stderr,
        )
        return 2

    profile = load_profile(args.profile)
    data_dir = Path(os.environ.get("SCOUT_DB_PATH", PROJECT_ROOT / "data" / "scout.db")).parent
    log_dir = Path(os.environ.get("SCOUT_LOG_DIR", PROJECT_ROOT / "logs"))
    setup_logging(log_dir / "listener.log")

    from scout.core.notify.chat_agent import ChatAgent
    from scout.core.notify.listener import listen_forever

    known_cities = [c.name for c in profile.search.cities]
    chat = ChatAgent(profile=profile)

    try:
        asyncio.run(
            listen_forever(
                token=token,
                chat_id=chat_id,
                known_cities=known_cities,
                project_root=PROJECT_ROOT,
                lock_path=data_dir / "run.lock",
                offset_path=data_dir / "telegram_listener.offset",
                chat=chat,
            )
        )
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
