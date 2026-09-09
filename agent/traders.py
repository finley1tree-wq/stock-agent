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

# The leaderboard failed its own significance test, so nothing is weighted until it passes.
#
# Tested against a luck null on the live board (25 members, 1,114 scored buys, per-trade excess
# sd 10.24pp): the expected BEST-of-25 average excess return if every member had exactly zero
# skill is +5.77% — higher than the observed top of +4.76% (p = 0.71). No member survives
# Benjamini-Hochberg (min q = 0.73). The cross-sectional variance of the scores is LOWER than
# sampling noise alone predicts, implying negative between-member skill variance. An
# out-of-sample rank test, 2025 scores against 2026 outcomes, gives Spearman rho = -0.002.
#
# So the old 0.5x-2.0x multipliers were computed from noise and used to size real positions.
# With the budget at $1,000 and 100% allowed in one name, that was the most dangerous line in
# the signal stack. The published record agrees: Eggers & Hainmueller (Journal of Politics 75(2),
# 2013) find the famous Ziobrowski 12%/yr Senate result is the largest of eight estimates and
# significant in at most three of eight specifications.
MIN_SCORED = 30                    # measured: ~105 independent trades to see a +2%/trade edge
MIN_T_STAT = 2.5                   # and the multiple-comparisons bar is higher still

def weights(board: dict, min_scored: int = MIN_SCORED, per_trade_sd: float = 10.24) -> dict:
    """{member: multiplier}. Returns {} — no tilt at all — unless a record beats luck.

    A multiplier is only issued when a member clears BOTH a real sample size and a t-statistic
    that would survive testing 25 people at once. On today's data nobody clears it, which is the
    correct answer, not a bug.
    """
    out = {}
    for r in (board or {}).get("leaders", []):
        n = int(r.get("disclosed_buys_scored") or 0)
        if n < min_scored:
            continue
        se = per_trade_sd / (n ** 0.5)
        t = (r.get("avg_excess_pct") or 0) / se if se else 0
        if t >= MIN_T_STAT:
            out[r["who"]] = 1.5
        elif t <= -MIN_T_STAT:
            out[r["who"]] = 0.5
    return out

def significance(board: dict, per_trade_sd: float = 10.24) -> dict:
    """What the board is worth as evidence, so the number is never read as a finding."""
    ls = (board or {}).get("leaders") or []
    if not ls:
        return {"verdict": "no leaderboard yet"}
    best = max(ls, key=lambda r: r["avg_excess_pct"])
    n = int(best.get("disclosed_buys_scored") or 1)
    t = best["avg_excess_pct"] / (per_trade_sd / (n ** 0.5))
    tilted = len(weights(board))
    return {
        "members": len(ls), "best": best["who"], "best_avg_excess_pct": best["avg_excess_pct"],
        "best_t_stat": round(t, 2), "members_weighted": tilted,
        "verdict": ("no member is distinguishable from luck; every multiplier is 1.0x"
                    if tilted == 0 else f"{tilted} member(s) clear the bar"),
        "how_to_read": ("Ranking 25 people and taking the top one produces a good-looking number "
                        "by construction. A score only counts here if it beats what the best of "
                        "25 coin-flippers would show, which needs roughly 30+ independent trades."),
    }
