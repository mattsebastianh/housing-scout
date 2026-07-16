#!/usr/bin/env python3
"""Interactive setup: writes profile.yaml for personal use."""
import sys
from pathlib import Path

from scout.core.setup_wizard import run_wizard

PROJECT_ROOT = Path(__file__).resolve().parent

if __name__ == "__main__":
    run_wizard(path=PROJECT_ROOT / "profile.yaml")
    sys.exit(0)
