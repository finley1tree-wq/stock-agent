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
MIN_DAYS_FOR_GUIDANCE = 10   # below this, a lesson is a hypothesis and not a rule

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

def score(prices: dict, held: set | None = None) -> dict:
    """Fill in 1w/1m returns where enough time has passed, then aggregate.

    A buy that has already been SOLD is frozen at what it actually returned. Marking every past
    buy to today's price forever is a different and much worse question - it grades a position
    the agent no longer owns, so a trade closed at -1% keeps getting worse as the stock falls and
    the model is told it is down 2.49% per trade when the realised figure is a fraction of that.
    """
    rows = _load()
    today = date.today()
    still = set(held) if held is not None else None
    for r in _buys(rows):
        if r.get("ret_final") is not None:
            r["ret_now"] = r["ret_final"]; continue          # closed: the answer cannot change
        px = prices.get(r["symbol"], {}).get("price")
        if not px or not r.get("entry_price"):
            continue
        age = (today - date.fromisoformat(str(r["date"])[:10])).days
        ret = round((px / r["entry_price"] - 1) * 100, 2)
        if age >= 7 and r.get("ret_1w") is None: r["ret_1w"] = ret
        if age >= 30 and r.get("ret_1m") is None: r["ret_1m"] = ret
        r["ret_now"] = ret
        if still is not None and r["symbol"] not in still:
            r["ret_final"] = ret                              # position is gone: freeze it here
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

def past_lessons(n: int = 12, evidence_days: int = 0) -> dict:
    """Recent lessons, WITH how much evidence stands behind them.

    Handing the model a bare list of its own conclusions is how it talked itself out of trading:
    nine lessons written on a single red day all said "hold cash", and it then cited "the last 8
    lessons" as proof. A lesson written after two graded days is a hypothesis. Below
    MIN_DAYS_FOR_GUIDANCE the list is trimmed and explicitly labelled as such, so it informs
    judgement instead of replacing it.
    """
    lines = []
    if LESSONS.exists():
        lines = [l[2:].strip() for l in LESSONS.read_text().splitlines() if l.startswith("- ")]
    thin = int(evidence_days or 0) < MIN_DAYS_FOR_GUIDANCE
    keep = 3 if thin else n
    return {
        "lessons": lines[-keep:],
        "graded_days_behind_them": int(evidence_days or 0),
        "status": ("UNPROVEN - written from too little history to be a rule. Treat these as things to "
                   "watch for, never as a reason to sit out. Repeating a conclusion does not make it "
                   "evidence." if thin else "backed by enough graded days to carry weight"),
    }

def _similar(a: str, b: str) -> float:
    """Cheap word-overlap similarity, enough to catch a lesson being written nine times."""
    wa = {w for w in a.lower().split() if len(w) > 3}
    wb = {w for w in b.lower().split() if len(w) > 3}
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)

def add_lesson(text: str, track: dict, evidence_days: int = 0, min_days: int = 1) -> None:
    """Write a lesson only when there is something to have learned from.

    On day one nine confident, causal-sounding lessons were written before a single decision had
    been graded - the agent was reading its own guesses back as knowledge on the next run. A lesson
    now needs graded evidence behind it, must not repeat one already on file, and carries the
    number of graded days so its weight is visible to whoever reads it next.
    """
    text = (text or "").strip()
    if not text:
        return
    if int(evidence_days or 0) < int(min_days):
        return
    prior = []
    if LESSONS.exists():
        prior = [l.split(": ", 1)[-1].strip() for l in LESSONS.read_text().splitlines() if l.startswith("- ")]
    # Tightened from 0.6: nine lessons on one day all said "hold cash on a red day" in slightly
    # different words, cleared the old bar, and the model then cited "the last 8 lessons" as its
    # reason never to trade. A conclusion repeated in fresh wording is still the same conclusion.
    if any(_similar(text, old) > 0.42 for old in prior[-40:]):
        return
    header = "" if LESSONS.exists() else "# Lessons the agent has drawn from its own results\n\n"
    with open(LESSONS, "a") as f:
        f.write(f"{header}- {date.today()} ({evidence_days}d graded, avg so far {track.get('avg_ret_pct_all')}%): {text}\n")
