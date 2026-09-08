#!/bin/bash
# Double-click to push code changes to GitHub, where the agent runs on a schedule
# every 30 minutes during market hours WITHOUT your Mac being on.
set -e
cd "$(dirname "$0")"
if ! command -v gh >/dev/null; then echo "Install the GitHub CLI first: brew install gh"; read -p "Press enter to exit"; exit 1; fi
if [ ! -f .env ]; then echo "No .env yet — run setup.command first."; read -p "Press enter to exit"; exit 1; fi

echo "== 1/5  GitHub login =="
gh auth status >/dev/null 2>&1 || gh auth login

echo "== 2/5  Preparing the repository =="
[ -d .git ] || git init -q
git branch -M main 2>/dev/null || true
git check-ignore .env >/dev/null 2>&1 || { echo "   STOP: .env is NOT ignored — refusing to push keys."; exit 1; }
echo "   .env is ignored, no keys will be pushed"
# Vercel (Hobby, private repo) only deploys commits authored by the account that owns the project.
git config user.name finley1tree-wq
git config user.email 284499650+finley1tree-wq@users.noreply.github.com
git add -A
if git diff --cached --quiet; then echo "   nothing new to commit"; else git commit -qm "update $(date -u +%FT%H:%MZ)"; echo "   committed"; fi

echo "== 3/5  Repository =="
if gh repo view stock-agent >/dev/null 2>&1; then
  git remote get-url origin >/dev/null 2>&1 || git remote add origin "https://github.com/$(gh api user -q .login)/stock-agent.git"
  git pull --rebase --autostash origin main 2>/dev/null || true
  git push -u origin main
  echo "   pushed to the existing repo"
else
  gh repo create stock-agent --private --source=. --push
  echo "   private repo created"
fi

echo "== 4/5  Keys as repository secrets =="
gh secret set -f .env
echo "   uploaded (write-only — nobody can read them back)"

echo "== 5/5  Kick off a run now =="
gh workflow run agent.yml 2>/dev/null && echo "   triggered" || echo "   (the schedule will pick it up at the next slot)"
echo
echo "Repo:  $(gh repo view stock-agent --json url -q .url)"
echo "Runs:  $(gh repo view stock-agent --json url -q .url)/actions"
echo
echo "Reminder: only ONE place should trade. If this Mac still has its own schedule running,"
echo "turn it off with:   bash autopilot-mac.command stop"
read -p "Press enter to close"
