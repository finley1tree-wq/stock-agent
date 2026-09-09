"""Which disclosed portfolios are actually worth following.

This is the honest version of "copy the good traders". Congress members must disclose their
trades under the STOCK Act, so anyone can read what they bought — most people simply never do.
That is a real edge, and it is entirely public.

But "Congress beats the market" is a claim, not a fact, and following all of them is following
noise. So this ranks each member by what their disclosures were actually worth, and two details
decide whether that ranking means anything:

**Measure from the DISCLOSURE date, never the transaction date.** A member may file up to 45 days
after trading. You could not have acted on the trade date, so scoring from it invents an edge
nobody could have captured. Only rows whose filing date is known are scored at all.

**Measure EXCESS return over the index.** In a rising market every buyer looks like a genius.
What matters is whether the name beat SPY over the same window, so the whole leaderboard is
computed as return minus SPY's return across the identical dates.

The result is a small table: who, how many disclosed buys, how often they beat the index, by how
much. It is cached in traders.json and refreshed daily.
"""
import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from .prices import yahoo_symbol

ROOT = Path(__file__).resolve().parent.parent
FILE = ROOT / "traders.json"
BENCHMARK = "SPY"
MAX_TICKERS = 500                 # keeps one daily rebuild to a couple of batched downloads

def _closes(tickers: list[str], start: str, end: str) -> dict:
    """{ticker: {date: close}} daily, batched."""
    import yfinance as yf
    out = {}
    ymap = {yahoo_symbol(t): t for t in tickers}
    ysyms = sorted(ymap)
    for i in range(0, len(ysyms), 120):
        chunk = ysyms[i:i + 120]
        try:
            d = yf.download(chunk, start=start, end=end, interval="1d", progress=False,
                            auto_adjust=True, group_by="ticker", threads=True)
        except Exception:
            continue
        if d is None or len(d) == 0:
            continue
        for y in chunk:
            try:
                cols = d.columns
                if getattr(cols, "nlevels", 1) > 1:
                    f = d[y]["Close"] if y in cols.get_level_values(0) else d["Close"][y]
                else:
                    f = d["Close"]
                ser = f.dropna()
                if len(ser):
                    out[ymap[y]] = {idx.date().isoformat(): float(v) for idx, v in ser.items()}
            except Exception:
                continue
    return out

def _fwd(series: dict, start: str, horizon_days: int) -> float | None:
    """Return from the first trading day on/after `start` to the first on/after start+horizon."""
    if not series:
        return None
    days = sorted(series)
    def at(d: str):
        for x in days:
            if x >= d:
                return x
        return None
    a = at(start)
    if not a:
        return None
    b = at((date.fromisoformat(a) + timedelta(days=horizon_days)).isoformat())
    if not b or b == a:
        return None
    p0, p1 = series[a], series[b]
    return None if not p0 else (p1 / p0 - 1) * 100

def build(trades: list[dict], horizon_days: int = 30, lookback_days: int = 540,
          min_trades: int = 4) -> dict:
    """Score every member's disclosed BUYS against the index. Returns the leaderboard."""
    today = date.today()
    floor = (today - timedelta(days=lookback_days)).isoformat()
    ceiling = (today - timedelta(days=horizon_days + 3)).isoformat()   # needs room to have played out
    rows = [r for r in trades
            if r.get("who") and r.get("disclosure_date")
            and r["type"] == "buy" and floor <= r["disclosure_date"] <= ceiling]
    if not rows:
        return {"built": today.isoformat(), "note": "no disclosed buys old enough to score", "leaders": []}
    counts = defaultdict(int)
    for r in rows:
        counts[r["ticker"]] += 1
    keep = {t for t, _ in sorted(counts.items(), key=lambda kv: -kv[1])[:MAX_TICKERS]}
    rows = [r for r in rows if r["ticker"] in keep]
    px = _closes(sorted(keep | {BENCHMARK}), floor, today.isoformat())
    bench = px.get(BENCHMARK) or {}

    per = defaultdict(list)
    for r in rows:
        ser = px.get(r["ticker"])
        if not ser:
            continue
        got = _fwd(ser, r["disclosure_date"], horizon_days)
        mkt = _fwd(bench, r["disclosure_date"], horizon_days)
        if got is None or mkt is None:
            continue
        per[r["who"]].append({"t": r["ticker"], "d": r["disclosure_date"], "excess": got - mkt})

    leaders = []
    for who, hits in per.items():
        if len(hits) < min_trades:
            continue
        ex = [h["excess"] for h in hits]
        avg = sum(ex) / len(ex)
        best = max(hits, key=lambda h: h["excess"])
        leaders.append({
            "who": who, "disclosed_buys_scored": len(hits),
            "avg_excess_pct": round(avg, 2),
            "beat_index_rate": round(sum(1 for x in ex if x > 0) / len(ex), 2),
            "best": {"ticker": best["t"], "excess_pct": round(best["excess"], 1), "disclosed": best["d"]},
        })
    leaders.sort(key=lambda r: -r["avg_excess_pct"])
    return {
        "built": today.isoformat(), "horizon_days": horizon_days, "lookback_days": lookback_days,
        "measured_from": "disclosure date, not transaction date",
        "benchmark": BENCHMARK, "members_scored": len(leaders), "buys_scored": sum(len(v) for v in per.values()),
        "leaders": leaders,
        "caveat": ("Excess return over SPY across the same dates, scored only from the day the filing became "
                   "public. A small number of trades is not evidence of skill; treat anyone with fewer than "
                   "about 20 scored buys as unproven."),
    }

def load() -> dict:
    try:
        return json.loads(FILE.read_text())
    except Exception:
        return {}

def refresh(trades: list[dict], max_age_hours: int = 20, **kw) -> dict:
    """Rebuild at most once a day; the download is the expensive part."""
    cur = load()
    if cur.get("built"):
        try:
            age = (datetime.now() - datetime.fromisoformat(cur["built"])).total_seconds() / 3600
            if age < max_age_hours and cur.get("leaders") is not None:
                return cur
        except Exception:
            pass
    fresh = build(trades, **kw)
    try:
        FILE.write_text(json.dumps(fresh, indent=1))
    except Exception:
        pass
    return fresh

def weights(board: dict, min_scored: int = 8) -> dict:
    """{member: multiplier} for buy pressure. Proven names count more, poor ones count against.

    Deliberately gentle: 2x at best, 0.5x at worst. A leaderboard built on a year of filings is a
    weak prior, and betting the book on it would be exactly the overfitting the learning loop is
    supposed to catch.
    """
    out = {}
    for r in (board or {}).get("leaders", []):
        if r["disclosed_buys_scored"] < min_scored:
            continue
        a = r["avg_excess_pct"]
        out[r["who"]] = 2.0 if a >= 5 else 1.5 if a >= 2 else 0.5 if a <= -2 else 1.0
    return out
