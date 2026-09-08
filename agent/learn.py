"""Learning loop.

Every executed buy is written to journal.json with the signals that drove it (sector, signal
sources such as congress / insider / news / momentum, whether Congress was buying, momentum at
entry, hour of day, the evidence the brain cited). Every sell is written too, with the realised
result. On later runs we score each buy at 1 week and 1 month, roll the results up by sector, by
signal source and by hour, rank the signal sources by realised return, summarise the sells, and
hand all of that plus the brain's own past lessons back to it. The agent can't change its
guardrails, but it does get smarter about which of its ideas - and which sources - have actually
been working, and in what order.
"""
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JOURNAL = ROOT / "journal.json"
LESSONS = ROOT / "lessons.md"

def _load() -> list[dict]:
    return json.loads(JOURNAL.read_text()) if JOURNAL.exists() else []

def _save(rows: list[dict]) -> None:
    JOURNAL.write_text(json.dumps(rows, indent=2, default=str))

def _buys(rows): return [r for r in rows if r.get("side", "buy") != "sell"]
def _sells(rows): return [r for r in rows if r.get("side") == "sell"]

def record(order: dict, entry_price: float | None, sector: str, congress_buying: bool, momentum_1m: float | None,
           signals: list[str] | None = None, evidence: str = "", hour_et: int | None = None) -> None:
    rows = _load()
    rows.append({**order, "side": "buy", "entry_price": entry_price, "sector": sector,
                 "congress_buying": congress_buying, "momentum_1m_at_entry": momentum_1m,
                 "signals": sorted(set(signals or [])), "evidence": evidence, "hour_et": hour_et,
                 "ret_1w": None, "ret_1m": None})
    _save(rows)

def record_sell(rec: dict, signals: list[str] | None = None, evidence: str = "", hour_et: int | None = None) -> None:
    rows = _load()
    rows.append({**rec, "side": "sell", "signals": sorted(set(signals or [])), "evidence": evidence, "hour_et": hour_et})
    _save(rows)

def journal_tickers() -> list[str]:
    return sorted({r["symbol"] for r in _buys(_load())})

def _agg(scored: list[dict], key: str, val: str = "ret_now", multi: bool = False) -> dict:
    buckets: dict[str, list[float]] = {}
    for r in scored:
        vals = r.get(key) if multi else [r.get(key)]
        for v in (vals or []):
            buckets.setdefault(str(v), []).append(r[val])
    return {k: {"n": len(v), "avg_ret_pct": round(sum(v) / len(v), 2), "hit_rate": round(sum(x > 0 for x in v) / len(v), 2)}
            for k, v in buckets.items()}

def score(prices: dict) -> dict:
    """Fill in 1w/1m returns where enough time has passed, then aggregate."""
    rows = _load()
    today = date.today()
    for r in _buys(rows):
        px = prices.get(r["symbol"], {}).get("price")
        if not px or not r.get("entry_price"):
            continue
        age = (today - date.fromisoformat(str(r["date"])[:10])).days
        ret = round((px / r["entry_price"] - 1) * 100, 2)
        if age >= 7 and r.get("ret_1w") is None: r["ret_1w"] = ret
        if age >= 30 and r.get("ret_1m") is None: r["ret_1m"] = ret
        r["ret_now"] = ret
    _save(rows)

    scored = [r for r in _buys(rows) if r.get("ret_now") is not None]
    sells = [r for r in _sells(rows) if r.get("realized_pct") is not None]
    by_signal = _agg(scored, "signals", multi=True)
    ranking = sorted(by_signal.items(), key=lambda kv: (-kv[1]["avg_ret_pct"], -kv[1]["n"]))
    rec = {
        "buys_total": len(_buys(rows)), "buys_scored": len(scored),
        "avg_ret_pct_all": round(sum(r["ret_now"] for r in scored) / len(scored), 2) if scored else None,
        "by_sector": _agg(scored, "sector"),
        "by_congress_buying": _agg(scored, "congress_buying"),
        "by_signal": by_signal,
        "signal_ranking_best_to_worst": [k for k, _ in ranking],
        "by_hour_et": _agg(scored, "hour_et"),
        "best": sorted(scored, key=lambda r: -r["ret_now"])[:3], "worst": sorted(scored, key=lambda r: r["ret_now"])[:3],
        "sells": {"n": len(sells),
                  "realized_pnl_usd": round(sum(r.get("realized_pnl", 0) for r in sells), 2),
                  "avg_realized_pct": round(sum(r["realized_pct"] for r in sells) / len(sells), 2) if sells else None,
                  "hit_rate": round(sum(r["realized_pct"] > 0 for r in sells) / len(sells), 2) if sells else None,
                  "by_signal": _agg(sells, "signals", val="realized_pct", multi=True),
                  "last": [{"symbol": r["symbol"], "date": r.get("date"), "realized_pct": r["realized_pct"], "why": r.get("why", "")} for r in sells[-5:]]},
    }
    for k in ("best", "worst"):
        rec[k] = [{"symbol": r["symbol"], "date": r["date"], "ret_now": r["ret_now"], "signals": r.get("signals", []),
                   "evidence": r.get("evidence", ""), "why": r.get("why", "")} for r in rec[k]]
    return rec

def past_lessons(n: int = 12) -> list[str]:
    if not LESSONS.exists():
        return []
    return [l.strip("- \n") for l in LESSONS.read_text().splitlines() if l.startswith("- ")][-n:]

def add_lesson(text: str, track: dict) -> None:
    text = (text or "").strip()
    if not text:
        return
    header = "" if LESSONS.exists() else "# Lessons the agent has drawn from its own results\n\n"
    with open(LESSONS, "a") as f:
        f.write(f"{header}- {date.today()} (avg so far {track.get('avg_ret_pct_all')}%): {text}\n")
