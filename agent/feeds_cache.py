"""A small committed cache for the paid-data feeds (Financial Modeling Prep).

Why it exists. The free FMP plan allows a limited number of requests a day. While the model API is
out of credit the autopilot decides every two minutes, and each decision asked FMP for the insider
list and for Senate trades - 93 decisions by 14:00 ET on 2026-09-15, which used up the day's quota by
late morning ("429 Too Many Requests"), so the insider feed read "unavailable" for the rest of the
session. Form 4 filings arrive a few times a day; re-downloading the same list every two minutes
bought nothing.

Committed, not in .cache/: every GitHub Actions job starts on a fresh machine, so a gitignored file
would be gone by the next check.
"""
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILE = ROOT / "feeds_cache.json"


def load() -> dict:
    try:
        d = json.loads(FILE.read_text())
    except Exception:
        return {}
    return d if isinstance(d, dict) else {}


def update(key: str, value) -> None:
    d = load()
    d[key] = value
    try:
        FILE.write_text(json.dumps(d, separators=(",", ":"), sort_keys=True))
    except Exception:
        pass


def now() -> int:
    return int(time.time())
