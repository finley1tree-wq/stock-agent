#!/bin/bash
# Double-click to stop this Mac from sleeping during US market hours (6:25 AM–1:05 PM Pacific, Mon–Fri)
# while it is plugged in, so the autopilot checks actually fire. Uses macOS `caffeinate`; changes no system settings.
# Remove with:   bash keep-awake-mac.command stop
LABEL="com.finley.stock-agent-awake"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
mkdir -p "$HOME/Library/LaunchAgents"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null
if [ "$1" = "stop" ]; then rm -f "$PLIST"; pkill -f "caffeinate -s -t 24000" 2>/dev/null; echo "Keep-awake removed."; read -p "Press enter to close"; exit 0; fi
TIMES=""
for W in 1 2 3 4 5; do
  TIMES="$TIMES<dict><key>Hour</key><integer>6</integer><key>Minute</key><integer>25</integer><key>Weekday</key><integer>$W</integer></dict>"
done
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>/usr/bin/caffeinate</string><string>-s</string><string>-t</string><string>24000</string></array>
  <key>StartCalendarInterval</key><array>$TIMES</array>
  <key>RunAtLoad</key><false/>
</dict></plist>
PL
launchctl bootstrap "gui/$(id -u)" "$PLIST" && echo "Keep-awake installed: 6:25 AM–1:05 PM Pacific, Mon–Fri, while plugged in. (caffeinate -s only works on AC power.)" || echo "launchctl failed — send this to Claude."
echo "If the Mac is asleep at 6:25 it won't wake by itself: leave the lid open and plugged in overnight, or open it before 6:25."
read -p "Press enter to close"
