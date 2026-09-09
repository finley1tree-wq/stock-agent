"""Learn from years of history in a minute, instead of a day at a time.

The counterfactual loop grades one real trading day per real trading day. After two days it has
one independent observation and says so — it calls its own numbers "anecdote". Waiting for that
to become evidence takes months, and no amount of extra trading speeds it up: everything bought
on the same morning rises and falls with the same market, so a hundred trades in one day is
still roughly ONE independent observation. Independent DAYS are the currency, and you cannot
buy more of them by trading harder.

You can, however, replay the past. This runs the agent's own signal rules over years of real
prices, grades every decision the same way the live loop does, and reports each signal's edge
with the statistics needed to tell it apart from luck:

    edge      = the signal's average forward return MINUS the universe average that same day
                (so a rising market cannot make every signal look clever)
    t-stat    = edge / standard error across independent days
    verdict   = whether that survives testing several signals at once

Two honest limits. It grades the RULES, not the model's judgement — the brain reads news and
filings that this cannot replay. And a rule tuned on the same history it is tested on will
flatter itself, which is why nothing here is tuned: the signals are the ones already in the
code, measured as they stand.

    python -m agent.replay --years 3
"""
import json
import sys
from datetime import date
from pathlib import Path

from . import config
from .backtest import history, trading_days, pct_change

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "replay.json"
HORIZONS = {"1d": 1, "5d": 5, "21d": 21}
# Testing several signals at once means the best of them looks good by chance; this is the bar a
# single t-stat has to clear before it counts as anything at all.
T_BAR = 2.5

def _fwd(series: dict, days: list[str], i: int, h: int) -> float | None:
    if i + h >= len(days):
        return None
    a, b = series.get(days[i]), series.get(days[i + h])
    return None if not a or not b else (b / a - 1) * 100

def signals_for(day: str, hist: dict, days: list[str], i: int, sectors: dict, etfs: set) -> dict:
    """Which tickers each signal family would have picked that morning. Rules as they exist."""
    universe = [t for t in hist if hist[t].get(day)]
    if len(universe) < 3:
        return {}
    def mom(t, look):
        return pct_change(hist[t], day, look, days)
    out = {}
    m1w = {t: mom(t, 5) for t in universe}
    m1w = {t: v for t, v in m1w.items() if v is not None}
    if m1w:
        ranked = sorted(m1w, key=lambda t: -m1w[t])
        out["momentum_1w"] = ranked[:3]
        out["contrarian_1w"] = ranked[-3:]
    m1m = {t: mom(t, 21) for t in universe}
    m1m = {t: v for t, v in m1m.items() if v is not None}
    if m1m:
        out["momentum_1m"] = sorted(m1m, key=lambda t: -m1m[t])[:3]
    picks = [t for t in universe if t in etfs]
    if picks:
        out["etf_default"] = picks[:3]
    return out

def run(years: int = 3, cfg: dict | None = None) -> dict:
    cfg = cfg or config.load_config()
    watch = sorted({t for v in cfg["watchlist"].values() for t in v})
    sectors = {t: s for s, ts in cfg["watchlist"].items() for t in ts}
    etfs = {"SPY", "DIA", "GLD", "VNQ", "NLR"}
    hist = history(watch, years)
    days = trading_days(hist)
    if len(days) < 60:
        return {"error": "not enough history"}

    # per signal, per horizon: a list of (edge vs the universe that day) - one entry per DAY
    acc: dict = {s: {h: [] for h in HORIZONS} for h in [0] for s in
                 ("momentum_1w", "contrarian_1w", "momentum_1m", "etf_default")}
    universe_ret: dict = {h: [] for h in HORIZONS}
    graded_days = 0

    for i, day in enumerate(days):
        picks = signals_for(day, hist, days, i, sectors, etfs)
        if not picks:
            continue
        counted = False
        for hname, h in HORIZONS.items():
            allret = [_fwd(hist[t], days, i, h) for t in hist if hist[t].get(day)]
            allret = [r for r in allret if r is not None]
            if len(allret) < 3:
                continue
            uni = sum(allret) / len(allret)
            universe_ret[hname].append(uni)
            for sname, tickers in picks.items():
                rs = [_fwd(hist[t], days, i, h) for t in tickers]
                rs = [r for r in rs if r is not None]
                if rs:
                    acc[sname][hname].append(sum(rs) / len(rs) - uni)   # EXCESS over that day
                    counted = True
        if counted:
            graded_days += 1

    def stats(xs: list[float]) -> dict:
        n = len(xs)
        if n < 2:
            return {"days": n}
        mean = sum(xs) / n
        var = sum((x - mean) ** 2 for x in xs) / (n - 1)
        se = (var / n) ** 0.5
        t = mean / se if se else 0.0
        return {"days": n, "edge_pct": round(mean, 4), "t_stat": round(t, 2),
                "beat_rate": round(sum(1 for x in xs if x > 0) / n, 3),
                "verdict": "real" if abs(t) >= T_BAR else "indistinguishable from luck"}

    out = {
        "built": date.today().isoformat(), "years": years,
        "trading_days_replayed": len(days), "days_graded": graded_days,
        "measures": "each signal's average forward return MINUS the whole universe's that same day",
        "t_bar": T_BAR,
        "signals": {s: {h: stats(v) for h, v in hs.items()} for s, hs in acc.items()},
        "universe_drift_pct": {h: round(sum(v) / len(v), 4) if v else None for h, v in universe_ret.items()},
        "caveat": ("Grades the mechanical signal rules, not the model's judgement, and cannot replay "
                   "the news and filings the brain reads. A signal marked 'indistinguishable from luck' "
                   "has no measured edge here - that is information, not a failure."),
    }
    OUT.write_text(json.dumps(out, indent=1))
    return out

def load() -> dict:
    try:
        return json.loads(OUT.read_text())
    except Exception:
        return {}

def evidence(horizon: str = "5d") -> dict:
    """Compact, brain-facing: which signals have a measured edge and which do not."""
    r = load()
    if not r.get("signals"):
        return {}
    rows = {s: h.get(horizon, {}) for s, h in r["signals"].items()}
    return {
        "horizon": horizon, "independent_days": r.get("days_graded"),
        "years_replayed": r.get("years"),
        "signals": {s: {k: v for k, v in d.items() if k in ("edge_pct", "t_stat", "days", "verdict")}
                    for s, d in rows.items() if d.get("days")},
        "how_to_read": ("edge_pct is this signal's average return MINUS the universe's on the same day, so "
                        "market drift is already removed. A |t_stat| under " + str(r.get("t_bar", T_BAR)) +
                        " means the edge is not distinguishable from luck and should not be traded on."),
    }

if __name__ == "__main__":
    yrs = int(sys.argv[sys.argv.index("--years") + 1]) if "--years" in sys.argv else 3
    r = run(yrs)
    if r.get("error"):
        raise SystemExit(r["error"])
    print(f"replayed {r['trading_days_replayed']} trading days over {r['years']}y "
          f"({r['days_graded']} graded)\n")
    print(f"  {'signal':16} {'horizon':8} {'days':>6} {'edge':>9} {'t':>7}   verdict")
    for s, hs in r["signals"].items():
        for h, d in hs.items():
            if d.get("days", 0) > 2:
                print(f"  {s:16} {h:8} {d['days']:6} {d['edge_pct']:+8.3f}% {d['t_stat']:+7.2f}   {d['verdict']}")
