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

def _agg(scored: list[dict], key: str, val: str = "ret_now", multi: bool = False, weight: str | None = None) -> dict:
    """Bucket average of `val` by `key`. With `weight` set (e.g. "proceeds") the average is
    dollar-weighted: one $500 trade counts ten times a $50 one. Unweighted, a single AMD lot sold
    in four $3 halves outvoted every real trade and ranked 'risk_management' the best signal."""
    buckets: dict[str, list[tuple[float, float]]] = {}
    for r in scored:
        vals = r.get(key) if multi else [r.get(key)]
        w = float(r.get(weight) or 0) if weight else 1.0
        if weight and w <= 0:
            w = float(r.get("qty") or 0) or 1.0
        for v in (vals or []):
            buckets.setdefault(str(v), []).append((float(r[val]), w))
    out = {}
    for k, pairs in buckets.items():
        tw = sum(w for _, w in pairs) or 1.0
        out[k] = {"n": len(pairs),
                  "avg_ret_pct": round(sum(x * w for x, w in pairs) / tw, 2),
                  "hit_rate": round(sum(w for x, w in pairs if x > 0) / tw, 2)}
        if weight:
            out[k]["usd"] = round(tw, 2)
    return out

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
    sells_all = _sells(rows)
    for r in _buys(rows):
        closed = still is not None and r["symbol"] not in still
        if closed:
            # Self-healing: derive the frozen value from the SELL rows every time, never from a
            # one-off repair. A mark-to-today freeze (or a tick/replay race) cannot resurrect the
            # inflated number, because the sells are the source of truth and they do not move.
            real = _realised_for(r, sells_all)
            if real is not None:
                r["ret_final"] = real; r["ret_now"] = real; r["ret_src"] = "realised"; continue
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
        if closed:
            r["ret_final"] = ret; r["ret_src"] = "mark"        # gone but no sell row found: last resort
    # how long each closed trade was actually held, so the loop can answer "does the clock pay?"
    for sr in sells_all:
        if sr.get("hold_minutes") is None:
            b = _entry_for(sr, rows)
            if b and b.get("ts") and sr.get("ts"):
                sr["hold_minutes"] = int(max(0, (int(sr["ts"]) - int(b["ts"])) // 60))
    _save(rows)

    scored = [r for r in _buys(rows) if r.get("ret_now") is not None]
    open_rows = [r for r in scored if still is None or r["symbol"] in still]
    sells = [r for r in sells_all if r.get("realized_pct") is not None]
    for sr in sells:
        # Old sells were recorded with no signals (or "unspecified") before closing sells inherited
        # the entry's tags. Attribute them at read time, the same way new sells are, so the ranking
        # is not dominated by a bucket that means "nobody wrote it down".
        sig = [x for x in (sr.get("signals") or []) if x and x != "unspecified"]
        if not sig:
            b = _entry_for(sr, rows)
            if b and b.get("signals"):
                sr["signals"] = sorted(set(b["signals"]) | ({"time_stop"} if sr.get("trigger") == "time_stop" else set()))
    # The ranking the brain reads is built from REALISED sells. Building it from the buy-side mark
    # graded positions the agent no longer owned and told it it was down 2.5% a trade when the
    # booked figure was a fraction of that - and flipped the sign on AMD.
    by_signal = _agg(sells, "signals", val="realized_pct", multi=True, weight="proceeds") if sells else _agg(scored, "signals", multi=True)
    ranking = sorted(by_signal.items(), key=lambda kv: (-kv[1]["avg_ret_pct"], -kv[1]["n"]))
    closed_buys = [r for r in scored if r.get("ret_src") == "realised" or (still is not None and r["symbol"] not in still)]
    cost_closed = sum(float(r.get("notional") or r.get("usd") or 0) for r in closed_buys)
    pnl = sum(float(r.get("realized_pnl", 0) or 0) for r in sells)
    for sr in sells:
        hm = sr.get("hold_minutes")
        sr["hold_bucket"] = ("<=30m" if hm <= 30 else "<=60m" if hm <= 60 else "<=1d" if hm <= 390 else ">1d") if hm is not None else "unknown"
    rec = {
        "buys_total": len(_buys(rows)), "buys_scored": len(scored),
        "avg_ret_pct_all": round(sum(r["ret_now"] for r in scored) / len(scored), 2) if scored else None,
        "realized_per_dollar_pct": round(100 * pnl / cost_closed, 2) if cost_closed > 0 else None,
        "how_to_read": ("realized_per_dollar_pct is what closed trades actually booked per dollar put in. "
                        "avg_ret_pct_all mixes that with open positions marked to market; prefer the first. "
                        "Sell-side buckets (by_signal, by_hour_et, by_hold_bucket) are dollar-weighted: usd is the "
                        "money behind each bucket, and a bucket under a few hundred dollars is noise."),
        "by_sector": _agg(scored, "sector"),
        "by_congress_buying": _agg(scored, "congress_buying"),
        "by_signal": by_signal,
        "signal_ranking_best_to_worst": [k for k, _ in ranking],
        "by_hour_et": _agg(sells, "hour_et", val="realized_pct", weight="proceeds") if sells else _agg(scored, "hour_et"),
        "by_hold_bucket": _agg(sells, "hold_bucket", val="realized_pct", weight="proceeds") if sells else {},
        "unrealised_open": [{"symbol": r["symbol"], "ret_now": r["ret_now"]} for r in open_rows],
        "best": sorted(sells, key=lambda r: -r["realized_pct"])[:3] if sells else sorted(scored, key=lambda r: -r["ret_now"])[:3],
        "worst": sorted(sells, key=lambda r: r["realized_pct"])[:3] if sells else sorted(scored, key=lambda r: r["ret_now"])[:3],
        "sells": {"n": len(sells),
                  "realized_pnl_usd": round(sum(r.get("realized_pnl", 0) for r in sells), 2),
                  "avg_realized_pct": round(sum(r["realized_pct"] for r in sells) / len(sells), 2) if sells else None,
                  "hit_rate": round(sum(r["realized_pct"] > 0 for r in sells) / len(sells), 2) if sells else None,
                  "by_signal": _agg(sells, "signals", val="realized_pct", multi=True, weight="proceeds"),
                  "last": [{"symbol": r["symbol"], "date": r.get("date"), "realized_pct": r["realized_pct"], "why": r.get("why", "")} for r in sells[-5:]]},
    }
    for k in ("best", "worst"):
        rec[k] = [{"symbol": r["symbol"], "date": r.get("date"), "ret_pct": r.get("realized_pct", r.get("ret_now")),
                   "hold_minutes": r.get("hold_minutes"), "signals": r.get("signals", []),
                   "evidence": r.get("evidence", ""), "why": r.get("why", "")} for r in rec[k]]
    return rec

def _realised_for(buy: dict, sells: list[dict]) -> float | None:
    """What this buy actually returned, from the sell rows that closed it: proceeds-weighted realised %."""
    bts = int(buy.get("ts") or 0)
    bdate = str(buy.get("date", ""))[:10]
    mine = [s for s in sells if s.get("symbol") == buy.get("symbol") and s.get("realized_pct") is not None
            and ((int(s.get("ts") or 0) >= bts) if bts and s.get("ts") else str(s.get("date", ""))[:10] >= bdate)]
    if not mine:
        return None
    w = [float(s.get("proceeds") or s.get("qty") or 1) for s in mine]
    return round(sum(float(s["realized_pct"]) * x for s, x in zip(mine, w)) / (sum(w) or 1), 2)

def _entry_for(sell: dict, rows: list[dict]) -> dict | None:
    """The most recent buy of the same symbol at or before this sell."""
    sts = int(sell.get("ts") or 0)
    cands = [r for r in _buys(rows) if r.get("symbol") == sell.get("symbol") and int(r.get("ts") or 0) <= (sts or 2**62)]
    return max(cands, key=lambda r: int(r.get("ts") or 0)) if cands else None

def entry_signals(symbol: str) -> list[str]:
    """Signals behind the most recent buy of this name, so a closing sell can inherit them."""
    rows = _load()
    cands = [r for r in _buys(rows) if r.get("symbol") == symbol]
    if not cands:
        return []
    b = max(cands, key=lambda r: int(r.get("ts") or 0))
    return [x for x in (b.get("signals") or []) if isinstance(x, str)]

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
        f.write(f"{header}- {date.today()} ({evidence_days}d graded, realised {track.get('realized_per_dollar_pct')}% per dollar): {text}\n")
