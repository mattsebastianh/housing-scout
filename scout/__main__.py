import sys

if __name__ == "__main__" and sys.argv[1:2] == ["setup"]:
    from pathlib import Path

    from scout.core.setup_wizard import run_wizard

    run_wizard(path=Path.cwd() / "profile.yaml")
