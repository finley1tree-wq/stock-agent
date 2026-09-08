#!/bin/bash
# Double-click to make this Mac run the agent every 30 minutes during US market hours (6:30 AM–1:00 PM Pacific, Mon–Fri).
# The Mac must be awake and logged in. Output goes to autopilot.log in this folder.
# Run again with "stop" to remove:   bash autopilot-mac.command stop
DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.finley.stock-agent"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PY="$(command -v python3)"
mkdir -p "$HOME/Library/LaunchAgents"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null
if [ "$1" = "stop" ]; then rm -f "$PLIST"; echo "Autopilot removed."; read -p "Press enter to close"; exit 0; fi

TIMES=""
for H in 6 7 8 9 10 11 12 13; do for M in 0 30; do
  [ "$H" = 6 ] && [ "$M" = 0 ] && continue      # market opens 6:30 Pacific
  [ "$H" = 13 ] && [ "$M" = 30 ] && continue    # market closes 13:00 Pacific
  for W in 1 2 3 4 5; do
    TIMES="$TIMES<dict><key>Hour</key><integer>$H</integer><key>Minute</key><integer>$M</integer><key>Weekday</key><integer>$W</integer></dict>"
  done
done; done

cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>-lc</string><string>cd "$DIR" &amp;&amp; "$PY" -m agent.run >> autopilot.log 2>&amp;1</string></array>
  <key>StartCalendarInterval</key><array>$TIMES</array>
  <key>RunAtLoad</key><false/>
</dict></plist>
PL
launchctl bootstrap "gui/$(id -u)" "$PLIST" && echo "Autopilot installed: every 30 min, 6:30 AM–1:00 PM Pacific, Mon–Fri, while this Mac is awake." || echo "launchctl failed — send this to Claude."
echo "Log: $DIR/autopilot.log   Portfolio: $DIR/portfolio.md"
read -p "Press enter to close"
