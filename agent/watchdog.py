"""Watchdog: if a scheduled check was missed while the market is open, dispatch one.

GitHub's cron is best-effort (runs are delayed at busy times and occasionally dropped). This runs from
.github/workflows/watchdog.yml between the agent's slots and, when the market is open and no check has
started in the last MAX_GAP_MIN minutes, fires agent.yml via workflow_dispatch. Standard library only,
so the workflow needs no pip install.

    python -m agent.watchdog            # decide and dispatch (needs GITHUB_TOKEN with actions: write)
    python -m agent.watchdog --dry-run  # decide, print, never dispatch
    python -m agent.watchdog --force    # dispatch even if a check ran recently (tests the wiring)
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .broker_sim import is_trading_day, close_time

ET = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parent.parent
API = "https://api.github.com"
MAX_GAP_MIN = 40            # one 30-minute slot plus grace for a late cron
ACTIVE = {"queued", "in_progress", "waiting", "pending", "requested"}

def market_open(now_et: datetime) -> bool:
    d = now_et.date()
    return is_trading_day(d) and time(9, 30) <= now_et.time() < close_time(d)

def decide(now_et: datetime, runs: list[dict], paused: bool, max_gap_min: int = MAX_GAP_MIN) -> tuple[bool, str]:
    """Pure decision: (dispatch?, reason). `runs` are agent.yml workflow runs, newest first or any order."""
    if paused:
        return False, "PAUSE file present"
    if not market_open(now_et):
        return False, "market closed"
    live = [r for r in runs if r.get("status") in ACTIVE]
    if live:
        return False, f"a check is already {live[0]['status']}"
    real = [r for r in runs if r.get("conclusion") not in ("cancelled", "skipped")]
    if not real:
        return True, "no checks recorded yet"
    last = max(_ts(r["created_at"]) for r in real)
    age = (now_et.astimezone(timezone.utc) - last).total_seconds() / 60
    if age <= max_gap_min:
        return False, f"last check started {age:.0f} min ago"
    return True, f"last check started {age:.0f} min ago (> {max_gap_min})"

def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))

def _api(repo: str, path: str, token: str, method: str = "GET", body: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"{API}/repos/{repo}{path}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
    return json.loads(raw) if raw else {}

def main(argv: list[str]) -> int:
    dry, force = "--dry-run" in argv, "--force" in argv
    repo = os.environ.get("GITHUB_REPOSITORY") or "finley1tree-wq/stock-agent"
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    if not token:
        print("watchdog: no GITHUB_TOKEN"); return 2
    now = datetime.now(ET)
    runs = _api(repo, "/actions/workflows/agent.yml/runs?per_page=12", token).get("workflow_runs", [])
    paused = (ROOT / "PAUSE").exists()
    go, why = decide(now, runs, paused)
    if force and not paused:
        go, why = True, "forced"
    print(f"watchdog {now:%Y-%m-%d %H:%M} ET: {'DISPATCH' if go else 'nothing to do'} — {why}")
    if go and not dry:
        _api(repo, "/actions/workflows/agent.yml/dispatches", token, "POST", {"ref": "main"})
        print("dispatched agent.yml")
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
