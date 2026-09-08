"""Write the dashboard's data files into site/data/ so the Vercel site can show them.

Called at the end of every check (and via `python -m agent.run --publish`). The site is static:
it reads these files plus live quotes from its own /api functions. No keys ever land here.
"""
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from . import state, safety
from .broker_sim import HOLIDAYS, EARLY_CLOSE_1PM

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "data"
ET = ZoneInfo("America/New_York")

def _copy(name: str, default: str) -> None:
    src = ROOT / name
    (OUT / name).write_text(src.read_text() if src.exists() else default)

def _copy_tail(name: str, keep: int) -> None:
    """journal.json grows forever locally (learn.py needs all of it); the site only needs recent rows."""
    src = ROOT / name
    try:
        rows = json.loads(src.read_text()) if src.exists() else []
        rows = rows[-keep:] if isinstance(rows, list) else []
    except Exception:
        rows = []
    (OUT / name).write_text(json.dumps(rows))

def publish(cfg: dict, signals: dict | None = None, note: str = "") -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    _copy("portfolio.json", "{}")
    (OUT / "state.json").write_text(json.dumps(state.load()))   # current ET day/week with counters already reset
    _copy_tail("journal.json", 1500)
    _copy("lessons.md", "")
    log = ROOT / "log.md"
    lines = log.read_text().splitlines()[-400:] if log.exists() else []
    (OUT / "log.md").write_text("\n".join(lines) + ("\n" if lines else ""))
    g = cfg.get("guardrails", {})
    meta = {
        "asOf": datetime.now(ET).isoformat(timespec="minutes"), "note": note,
        "broker": cfg["env"]["broker"], "watchlist": cfg["watchlist"], "weekly_budget": cfg["weekly_budget"],
        "run_every_minutes": cfg.get("run_every_minutes", 30), "sim": cfg.get("sim"),
        "guardrails": {k: v for k, v in g.items() if not str(k).startswith("_")},
        "followed_people": cfg.get("followed_people") or [], "followed_politicians": cfg.get("followed_politicians") or [],
        "holidays": sorted(HOLIDAYS), "early_close_1pm": sorted(EARLY_CLOSE_1PM),
    }
    ok, why = safety.paused()                     # the stop/start switch, so the site can say PAUSED
    meta["paused"], meta["pause_reason"] = (not ok), why
    prev_path = OUT / "signals.json"
    if signals is not None:
        meta.update(signals)
        meta["signalsAsOf"] = meta["asOf"]
    elif prev_path.exists():
        try:
            old = json.loads(prev_path.read_text())
            for k in ("congress_trades", "congress_pressure", "insider_trades", "insider_pressure", "headlines", "people_news", "allowed", "feed_status", "learning", "signalsAsOf"):
                if k in old: meta.setdefault(k, old[k])
        except Exception:
            pass
    prev_path.write_text(json.dumps(meta, indent=1, default=str))
