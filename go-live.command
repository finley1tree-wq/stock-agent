#!/bin/bash
# Double-click to turn off DRY_RUN so paper orders actually get placed.
cd "$(dirname "$0")" && sed -i '' 's/^DRY_RUN=.*/DRY_RUN=false/' .env && echo "DRY_RUN is now false — the agent will place paper orders." && read -p "Press enter to close"
