#!/bin/bash
# Double-click to STOP the agent trading (creates a PAUSE file). Double-click again to resume.
cd "$(dirname "$0")"
if [ -f PAUSE ]; then rm PAUSE; echo "Resumed — the agent will trade again at its next check."
else echo "paused by hand $(date)" > PAUSE; echo "PAUSED — the agent will not trade until you run this again."; fi
read -p "Press enter to close"
