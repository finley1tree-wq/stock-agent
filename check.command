#!/bin/bash
# Double-click to check that everything is healthy. Changes nothing.
cd "$(dirname "$0")" && python3 -m agent.doctor; echo; read -p "Press enter to close"
