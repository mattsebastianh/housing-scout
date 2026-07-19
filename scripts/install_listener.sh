#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.housing-scout.listener"
TARGET="$HOME/Library/LaunchAgents/${LABEL}.plist"

mkdir -p "$HOME/Library/LaunchAgents"
sed "s|__PROJECT_ROOT__|$PROJECT_ROOT|g" \
    "$PROJECT_ROOT/scripts/${LABEL}.plist.template" \
    > "$TARGET"

if launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then
  launchctl bootout "gui/$(id -u)/$LABEL"
fi
launchctl bootstrap "gui/$(id -u)" "$TARGET"
echo "Installed: $TARGET"
echo "The Telegram /scout listener now runs continuously (KeepAlive)."
echo "Uninstall: launchctl bootout gui/$(id -u)/$LABEL && rm $TARGET"
