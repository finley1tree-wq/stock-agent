#!/bin/bash
# Double-click to run the agent once, right now.
cd "$(dirname "$0")" && python3 -m agent.run; echo; read -p "Press enter to close"
