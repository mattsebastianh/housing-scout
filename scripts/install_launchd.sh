#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.housing-scout.daily"
TARGET="$HOME/Library/LaunchAgents/${LABEL}.plist"

mkdir -p "$HOME/Library/LaunchAgents"
sed "s|__PROJECT_ROOT__|$PROJECT_ROOT|g" \
    "$PROJECT_ROOT/scripts/com.housing-scout.daily.plist.template" \
    > "$TARGET"

if launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then
  launchctl bootout "gui/$(id -u)/$LABEL"
fi
launchctl bootstrap "gui/$(id -u)" "$TARGET"
echo "Installed: $TARGET"
echo "Schedule: every Tuesday 00:00 CET / Europe/Madrid (Monday 18:00 Mac-local UTC-5). Run manually: .venv/bin/python run_daily.py"
