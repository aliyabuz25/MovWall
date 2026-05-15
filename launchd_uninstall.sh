#!/usr/bin/env bash
set -euo pipefail

APP_LABEL="com.movwall.agent"
PLIST_PATH="$HOME/Library/LaunchAgents/${APP_LABEL}.plist"

launchctl unload "$PLIST_PATH" >/dev/null 2>&1 || true
rm -f "$PLIST_PATH"

echo "Kaldirildi: $APP_LABEL"
