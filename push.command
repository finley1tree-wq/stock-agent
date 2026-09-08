#!/bin/bash
# Double-click to put the agent on autopilot: creates a private GitHub repo, pushes, uploads your .env as secrets.
cd "$(dirname "$0")"
if ! command -v gh >/dev/null; then echo "Install GitHub CLI first: https://cli.github.com (or: brew install gh)"; read -p "Press enter to exit"; exit 1; fi
gh auth status >/dev/null 2>&1 || gh auth login
[ -d .git ] || { git init -q && git add -A && git commit -qm "stock agent"; }
gh repo view stock-agent >/dev/null 2>&1 || gh repo create stock-agent --private --source=. --push
gh secret set -f .env
gh workflow run agent.yml 2>/dev/null && echo "Triggered a first run — check the Actions tab on github.com in a minute."
echo "Done. It now runs every 30 minutes during market hours, and commits site/data for the Vercel dashboard."
echo "Next: in Vercel, import this GitHub repo as a project (root directory = repo root) so the dashboard redeploys on every commit."
read -p "Press enter to close"
