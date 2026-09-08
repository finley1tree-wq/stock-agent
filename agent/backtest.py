"""Backtester: replay real historical prices against the agent's own guardrails.

It does NOT replay Claude's decisions (that would cost a fortune and prove little). It tests the
SIGNAL RULES the brain is allowed to act on — momentum, contrarian, ETF-default, sector, equal weight
— under the real weekly budget and caps, and measures them against buy-and-hold SPY.

The point is to give the agent a prior: which signal families and which sectors have actually paid
off over the last N years, so its first weeks aren't a blank slate. The results are written to
backtest.json (fed to the brain as `backtest_priors`) and backtest.md (for you).

    python -m agent.backtest              # 2-year and 5-year windows
    python -m agent.backtest --years 1,3,10
"""
import json, sys
from datetime import date
from pathlib import Path
import yfinance as yf
from . import config
from .prices import yahoo_symbol

ROOT = Path(__file__).resolve().parent.parent
OUT_JSON = ROOT / "backtest.json"
OUT_MD = ROOT / "backtest.md"
BENCH = "SPY"

# ---------- data ----------
def history(tickers: list[str], years: int) -> dict:
    """{our_ticker: {date_iso: close}} of daily closes, split/dividend adjusted."""
    ymap = {yahoo_symbol(t): t for t in tickers}
    data = yf.download(sorted(ymap), period=f"{years}y", interval="1d",
                       progress=False, auto_adjust=True, group_by="ticker", threads=True)
    out = {}
    cols = data.columns
    for y, t in ymap.items():
        try:
            if getattr(cols, "nlevels", 1) > 1:
                s = data[y]["Close"] if y in cols.get_level_values(0) else data["Close"][y]
            else:
                s = data["Close"]
            s = s.dropna()
            if len(s) > 30:
                out[t] = {d.date().isoformat(): float(v) for d, v in s.items()}
        except Exception:
            continue
    return out

def trading_days(hist: dict) -> list[str]:
    days = set()
    for series in hist.values():
        days |= set(series)
    return sorted(days)

def week_of(d: str) -> str:
    y, w, _ = date.fromisoformat(d).isocalendar()
    return f"{y}-W{w:02d}"

def pct_change(series: dict, day: str, lookback: int, days: list[str]) -> float | None:
    """Percent change over `lookback` trading days ending at `day`."""
    i = days.index(day)
    if i < lookback:
        return None
    then, now = days[i - lookback], day
    a, b = series.get(then), series.get(now)
    return None if not a or not b else (b / a - 1) * 100

# ---------- strategies ----------
def pick(strategy: str, day: str, hist: dict, days: list[str], sectors: dict, etfs: set) -> list[str]:
    """Which tickers this strategy buys on `day`. At most 4, matching the live guardrail."""
    avail = [t for t in hist if day in hist[t]]
    if not avail:
        return []
    if strategy == "spy_only":
        return [BENCH] if BENCH in avail else []
    if strategy == "etf_default":
        return [t for t in avail if t in etfs][:4]
    if strategy == "equal_weight":
        return avail[:4]
    if strategy in ("momentum_1m", "contrarian_1m", "momentum_1w"):
        look = 5 if strategy == "momentum_1w" else 21
        scored = [(t, pct_change(hist[t], day, look, days)) for t in avail]
        scored = [(t, m) for t, m in scored if m is not None]
        if not scored:
            return []
        scored.sort(key=lambda x: x[1], reverse=(strategy != "contrarian_1m"))
        return [t for t, _ in scored[:4]]
    if strategy == "sector_rotate":
        best, best_m = None, None
        for sec, ts in sectors.items():
            ms = [pct_change(hist[t], day, 21, days) for t in ts if t in avail]
            ms = [m for m in ms if m is not None]
            if ms and (best_m is None or sum(ms) / len(ms) > best_m):
                best, best_m = sec, sum(ms) / len(ms)
        return [t for t in (sectors.get(best) or []) if t in avail][:4]
    return []

# ---------- simulation ----------
def simulate(strategy: str, hist: dict, days: list[str], cfg: dict, sectors: dict, etfs: set) -> dict:
    g = cfg["guardrails"]
    budget = float(cfg["weekly_budget"])
    per_cap = budget * g["max_per_ticker_pct"] / 100
    min_order = g["min_order_usd"]
    cash, deposited, positions, fills = 0.0, 0.0, {}, []
    equity_curve, seen_week = [], None
    for day in days:
        if week_of(day) != seen_week:            # first trading day of a new week: deposit + deploy
            seen_week = week_of(day)
            cash += budget
            deposited += budget
            picks = pick(strategy, day, hist, days, sectors, etfs)
            if picks:
                each = min(budget / len(picks), per_cap)
                for t in picks:
                    price = hist[t].get(day)
                    if not price or each < min_order or each > cash:
                        continue
                    qty = each / price
                    pos = positions.setdefault(t, {"qty": 0.0, "cost": 0.0})
                    pos["qty"] += qty
                    pos["cost"] += each
                    cash -= each
                    fills.append({"date": day, "ticker": t, "usd": round(each, 2), "price": round(price, 4)})
        mv = sum(p["qty"] * hist[t].get(day, hist[t][max(d for d in hist[t] if d <= day)] if any(d <= day for d in hist[t]) else 0) for t, p in positions.items())
        equity_curve.append((day, round(cash + mv, 2)))
    final = equity_curve[-1][1] if equity_curve else 0.0
    peak, max_dd = 0.0, 0.0
    for _, v in equity_curve:
        peak = max(peak, v)
        if peak > 0:
            max_dd = max(max_dd, (peak - v) / peak * 100)
    return {
        "strategy": strategy, "final_equity": round(final, 2), "deposited": round(deposited, 2),
        "total_return_pct": round((final / deposited - 1) * 100, 2) if deposited else None,
        "profit": round(final - deposited, 2), "max_drawdown_pct": round(max_dd, 2),
        "weeks": len({week_of(d) for d, _ in equity_curve}), "fills": len(fills),
        "positions": {t: round(p["qty"], 4) for t, p in sorted(positions.items())},
        "curve": [equity_curve[i] for i in range(0, len(equity_curve), max(1, len(equity_curve) // 60))],
    }

def forward_returns(hist: dict, days: list[str]) -> dict:
    """Does momentum actually predict? Average forward 1w/1m return after high vs low 1m momentum."""
    buckets = {"high_momentum": {"1w": [], "1m": []}, "low_momentum": {"1w": [], "1m": []}}
    step = 5
    for i in range(21, len(days) - 21, step):
        day = days[i]
        scored = [(t, pct_change(hist[t], day, 21, days)) for t in hist if day in hist[t]]
        scored = [(t, m) for t, m in scored if m is not None]
        if len(scored) < 4:
            continue
        scored.sort(key=lambda x: x[1], reverse=True)
        for label, group in (("high_momentum", scored[:3]), ("low_momentum", scored[-3:])):
            for t, _ in group:
                for horizon, ahead in (("1w", 5), ("1m", 21)):
                    fut = days[i + ahead]
                    a, b = hist[t].get(day), hist[t].get(fut)
                    if a and b:
                        buckets[label][horizon].append((b / a - 1) * 100)
    out = {}
    for label, hz in buckets.items():
        out[label] = {h: {"n": len(v), "avg_pct": round(sum(v) / len(v), 2), "hit_rate": round(sum(x > 0 for x in v) / len(v), 2)} if v else None for h, v in hz.items()}
    return out

def sector_performance(hist: dict, days: list[str], sectors: dict) -> dict:
    out = {}
    for sec, ts in sectors.items():
        rets = []
        for t in ts:
            s = hist.get(t)
            if s and len(s) > 30:
                ds = sorted(s)
                rets.append((s[ds[-1]] / s[ds[0]] - 1) * 100)
        if rets:
            out[sec] = {"n": len(rets), "avg_total_return_pct": round(sum(rets) / len(rets), 2)}
    return dict(sorted(out.items(), key=lambda kv: -kv[1]["avg_total_return_pct"]))

STRATEGIES = ["spy_only", "equal_weight", "etf_default", "momentum_1m", "momentum_1w", "contrarian_1m", "sector_rotate"]

def one_window(years: int, cfg: dict, sectors: dict, etfs: set, tickers: list[str]) -> dict:
    print(f"downloading {years}y of daily history for {len(tickers)} tickers…")
    hist = history(tickers, years)
    if BENCH not in hist:
        raise SystemExit("benchmark SPY unavailable — aborting")
    days = trading_days(hist)
    print(f"  {len(hist)} tickers, {len(days)} trading days ({days[0]} → {days[-1]})")
    results = [simulate(st, hist, days, cfg, sectors, etfs) for st in STRATEGIES]
    results.sort(key=lambda r: -(r["total_return_pct"] or -999))
    bench = next(r for r in results if r["strategy"] == "spy_only")
    for r in results:
        r["vs_spy_pct"] = round((r["total_return_pct"] or 0) - (bench["total_return_pct"] or 0), 2)
    return {
        "years": years, "period": {"from": days[0], "to": days[-1], "trading_days": len(days)},
        "ranking": [{k: r[k] for k in ("strategy", "total_return_pct", "vs_spy_pct", "profit", "max_drawdown_pct", "fills")} for r in results],
        "momentum_predictive_power": forward_returns(hist, days),
        "sector_performance": sector_performance(hist, days, sectors),
        "missing": sorted(set(tickers) - set(hist)),
    }

def run(windows: list[int] | None = None) -> dict:
    windows = windows or [2, 5]
    cfg = config.load_config()
    sectors = cfg["watchlist"]
    tickers = sorted({t for ts in sectors.values() for t in ts} | {BENCH})
    etfs = {"SPY", "DIA", "GLD", "VNQ", "NLR"}
    wins = [one_window(y, cfg, sectors, etfs, tickers) for y in windows]

    # stability: does the winner survive across windows?
    tops = [w["ranking"][0]["strategy"] for w in wins]
    orders = [[r["strategy"] for r in w["ranking"]] for w in wins]
    stable = len(set(tops)) == 1
    caveats = [
        "SELECTION BIAS: the watchlist was chosen in 2026 already knowing which themes had run "
        "(nuclear, defense, gold). Every strategy beats SPY here largely because of the ticker list, "
        "not the rule. Treat 'vs SPY' as meaningless.",
        "NO SELLING and no transaction costs are modelled; the live agent may sell.",
        "Claude's judgement is NOT replayed — only the mechanical signal rules are.",
    ]
    if not stable:
        pairs = ", ".join(f"{w['years']}y->{t}" for w, t in zip(wins, tops))
        caveats.insert(0, "UNSTABLE: the best strategy differs by window (" + pairs + "). "
                          "Do not treat the ranking as a rule; it is noise-dominated.")
    else:
        caveats.insert(0, f"The same strategy ({tops[0]}) ranked first in every window tested — weak evidence, not proof.")

    out = {
        "generated": date.today().isoformat(), "windows": windows,
        "weekly_budget": cfg["weekly_budget"], "guardrails_applied": True,
        "stable_ranking": stable, "top_by_window": dict(zip([w["years"] for w in wins], tops)),
        "rank_orders": {w["years"]: o for w, o in zip(wins, orders)},
        "by_window": {w["years"]: w for w in wins},
        "caveats": caveats,
    }
    OUT_JSON.write_text(json.dumps(out, indent=1))
    write_md(out)
    return out

def write_md(o: dict) -> None:
    L = [f"# Backtest — generated {o['generated']}", "",
         f"${o['weekly_budget']:.0f} deployed every week under the live guardrails "
         f"(max 40% per ticker, min $5, at most 4 buys per deploy). Buy-and-hold, no selling. "
         f"This tests the **signal rules**, not Claude's judgement.", "",
         "## Read this first", ""]
    for c in o["caveats"]:
        L.append(f"- {c}")
    for years, w in o["by_window"].items():
        L += ["", f"## {years}-year window — {w['period']['from']} → {w['period']['to']}", "",
              "| Strategy | Return | vs SPY | Profit | Max drawdown | Buys |", "|---|---:|---:|---:|---:|---:|"]
        for r in w["ranking"]:
            L.append(f"| {r['strategy']} | {r['total_return_pct']:+.2f}% | {r['vs_spy_pct']:+.2f}% | ${r['profit']:+,.2f} | {r['max_drawdown_pct']:.1f}% | {r['fills']} |")
        m = w["momentum_predictive_power"]
        L += ["", "**Does momentum predict?**", "", "| Bucket | Next 1 week | Next 1 month |", "|---|---:|---:|"]
        for label in ("high_momentum", "low_momentum"):
            wk, mo = m[label]["1w"], m[label]["1m"]
            L.append(f"| {label.replace('_', ' ')} | {wk['avg_pct']:+.2f}% (hit {wk['hit_rate']:.0%}, n={wk['n']}) | {mo['avg_pct']:+.2f}% (hit {mo['hit_rate']:.0%}, n={mo['n']}) |")
        L += ["", "**Sectors over this window**", "", "| Sector | Avg total return |", "|---|---:|"]
        for sec, v in w["sector_performance"].items():
            L.append(f"| {sec.replace('_', ' ')} | {v['avg_total_return_pct']:+.2f}% |")
        if w["missing"]:
            L += ["", f"No price history for: {', '.join(w['missing'])}"]
    L += ["", "Past performance says nothing about the future. This is a prior, not a promise.", ""]
    OUT_MD.write_text("\n".join(L))

def priors() -> dict:
    """Compact summary handed to the brain each check (empty if never run)."""
    if not OUT_JSON.exists():
        return {}
    try:
        o = json.loads(OUT_JSON.read_text())
    except Exception:
        return {}
    windows = {}
    for years, w in o.get("by_window", {}).items():
        windows[f"{years}y"] = {
            "period": w["period"],
            "strategy_ranking": [(r["strategy"], r["total_return_pct"]) for r in w["ranking"]],
            "momentum_predictive_power": w["momentum_predictive_power"],
            "sector_performance": w["sector_performance"],
        }
    return {"generated": o.get("generated"), "stable_ranking": o.get("stable_ranking"),
            "top_by_window": o.get("top_by_window"), "windows": windows, "caveats": o.get("caveats", [])}

if __name__ == "__main__":
    wins = [2, 5]
    if "--years" in sys.argv:
        wins = [int(x) for x in sys.argv[sys.argv.index("--years") + 1].split(",")]
    r = run(wins)
    print()
    for years, w in r["by_window"].items():
        print(f"  --- {years}y ---")
        for x in w["ranking"]:
            print(f"    {x['strategy']:<16} {x['total_return_pct']:+8.2f}%  dd {x['max_drawdown_pct']:5.1f}%")
    print()
    for c in r["caveats"]:
        print("  ! " + c)
    print(f"\nwrote {OUT_JSON.name} and {OUT_MD.name}")
