#!/usr/bin/env bash
# Install (or reinstall) a LaunchAgent that runs push.py at login and every minute (it only pushes when asked or every 30 min; see push.py).
# Usage: ./install-macos.sh [python3 path]   — that python needs Full Disk Access (chat.db).
# Config: ~/.config/money-coach/pusher.env with MONEY_URL= and MONEY_TOKEN= (mode 600).
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
py=${1:-$(command -v python3)}
label=com.money-coach.pusher
plist=~/Library/LaunchAgents/$label.plist
log=~/Library/Logs/money-coach-pusher.log
[ -f ~/.config/money-coach/pusher.env ] || { echo "missing ~/.config/money-coach/pusher.env" >&2; exit 1; }
cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$label</string>
  <key>ProgramArguments</key><array><string>$py</string><string>$here/push.py</string></array>
  <key>WorkingDirectory</key><string>$here</string>
  <key>StartInterval</key><integer>60</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$log</string>
  <key>StandardErrorPath</key><string>$log</string>
</dict></plist>
PLIST
launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$plist"
echo "installed $label ($py); log: $log"
