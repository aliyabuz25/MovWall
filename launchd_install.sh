#!/usr/bin/env bash
set -euo pipefail

APP_LABEL="com.movwall.agent"
PLIST_PATH="$HOME/Library/LaunchAgents/${APP_LABEL}.plist"
WORKDIR="$(cd "$(dirname "$0")" && pwd)"
APP_PATH="$WORKDIR/dist/MovWall.app"
APP_EXEC="$APP_PATH/Contents/MacOS/MovWall"
PYTHON_BIN="$(command -v python3)"

mkdir -p "$HOME/Library/LaunchAgents"

if [[ -x "$APP_EXEC" ]]; then
  PROGRAM="$APP_EXEC"
  ARGS=""
else
  PROGRAM="$PYTHON_BIN"
  ARGS="$WORKDIR/main.py"
fi

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${APP_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PROGRAM}</string>
$( [[ -n "$ARGS" ]] && echo "    <string>${ARGS}</string>" )
  </array>
  <key>WorkingDirectory</key>
  <string>${WORKDIR}</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>${HOME}/Library/Logs/MovWall.out.log</string>
  <key>StandardErrorPath</key><string>${HOME}/Library/Logs/MovWall.err.log</string>
</dict>
</plist>
EOF

launchctl unload "$PLIST_PATH" >/dev/null 2>&1 || true
launchctl load "$PLIST_PATH"

echo "Kuruldu ve baslatildi: $APP_LABEL"
