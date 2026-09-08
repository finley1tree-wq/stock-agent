"""Counterfactual learning: what it did, what it passed over, and what that cost.

learn.py scores the trades it MADE. This scores the decisions it made — including the decision to do
nothing — by remembering the whole candidate universe at that moment with each ticker's price and
signal state. Later, when prices have moved, every past decision can be re-graded:

    chosen   = the tickers it bought at that check
    skipped  = every other ticker it could have bought and didn't (already-held names are neither)
    regret   = avg forward return of skipped  minus  avg forward return of chosen

Positive regret means it is leaving money on the table. Negative regret means its picking is adding
value over picking at random from the same universe. It also surfaces the single biggest miss and the
biggest disaster avoided, so the brain sees concrete "this could have gone right / this went right
because I passed" examples instead of only its own fills.

Written to decisions.json (capped, compact). report() is handed to the brain every check.
"""
import json
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILE = ROOT / "decisions.json"
MAX_DECISIONS = 420          # ~30 trading days at 14 checks/day (file is committed every check; keep it small)
MIN_AGE_DAYS = 1             # don't grade a decision until the next session

def _load() -> list[dict]:
    if not FILE.exists():
        return []
    try:
        return json.loads(FILE.read_text())
    except Exception:
        return []

def _save(rows: list[dict]) -> None:
    FILE.write_text(json.dumps(rows[-MAX_DECISIONS:], separators=(",", ":"), default=str))

def record(now: datetime, px: dict, allowed: set, bought: list, sold: list, dropped: list,
           plan: dict, cpressure: dict, ipressure: dict, headlines: dict, sector_of: dict,
           held: set, budget_left: float, blocked: bool = False) -> None:
    """One row per check, traded or not. Universe is stored compactly so it can be re-graded later."""
    universe = {}
    for t in sorted(allowed):
        q = px.get(t) or {}
        if q.get("price") is None:
            continue
        # Sparse on purpose: zero / default fields are omitted and read back with .get() defaults.
        u = {"p": round(float(q["price"]), 4)}
        if q.get("change_1m_pct") is not None: u["m1m"] = round(float(q["change_1m_pct"]), 1)
        if round(cpressure.get(t, 0) or 0, 1): u["c"] = round(cpressure.get(t, 0), 1)   # congress net buying
        if round(ipressure.get(t, 0) or 0, 1): u["i"] = round(ipressure.get(t, 0), 1)   # insider net buying
        if headlines.get(t): u["n"] = len(headlines[t])                                  # headline count
        if t in sector_of: u["s"] = sector_of[t]                                         # absent = off-watchlist
        if t in held: u["h"] = 1                                                         # already held
        universe[t] = u
    rows = _load()
    rows.append({
        "ts": now.strftime("%Y-%m-%dT%H:%M"), "date": now.date().isoformat(), "hour": now.hour,
        "blocked": bool(blocked),
        "budget_left": round(budget_left, 2),
        "deploy_usd": round(float(plan.get("deploy_now_usd", 0) or 0), 2),
        "bought": [{"t": o["ticker"], "usd": o["usd"], "sig": o["signals"]} for o in bought],
        "sold": [{"t": s["ticker"], "pct": s["pct"], "sig": s["signals"]} for s in sold],
        "dropped": dropped[:8],
        "reasoning": (plan.get("reasoning") or "")[:400],
        "lesson": (plan.get("lesson") or "")[:300],
        "universe": universe,
    })
    _save(rows)

def _fwd(then: float, now: float | None) -> float | None:
    return None if not then or not now else (now / then - 1) * 100

def _avg(xs): return round(sum(xs) / len(xs), 2) if xs else None

def score(px_now: dict, max_rows: int = 400) -> dict:
    """Re-grade every decision old enough to have an answer, using today's prices.

    Per decision:  chosen  = tickers bought at that check
                   skipped = tickers it could have bought and didn't (already-held names are neither:
                             holding through a move is not "passing" on it)
                   regret  = avg(skipped) - avg(chosen)          [only defined when it bought something]
    The headline averages are taken over the SAME decisions as regret, so chosen_avg - skipped_avg == -regret.
    Idle checks are graded separately: idle_universe_avg_pct is what the list did while it sat out.
    """
    rows = _load()[-max_rows:]
    today = date.today()
    graded, regrets, c_avgs, s_avgs, chosen_all, skipped_all, idle_all = [], [], [], [], [], [], []
    by_signal_chosen: dict[str, list[float]] = {}
    by_sector_skipped: dict[str, dict[str, float]] = {}      # sector -> {ticker@date: fwd}
    best_miss: dict[str, dict] = {}                          # ticker -> its single best miss
    best_save: dict[str, dict] = {}                          # ticker -> its single worst avoided

    for r in rows:
        age = (today - date.fromisoformat(r["date"])).days
        if age < MIN_AGE_DAYS or not r.get("universe"):
            continue
        uni = r["universe"]
        bought = {b["t"] for b in r.get("bought", [])}
        held = {t for t, u in uni.items() if u.get("h")}
        fwd = {t: _fwd(u["p"], (px_now.get(t) or {}).get("price")) for t, u in uni.items()}
        fwd = {t: v for t, v in fwd.items() if v is not None}
        if not fwd:
            continue
        chosen = [v for t, v in fwd.items() if t in bought]
        skipped_t = [t for t in fwd if t not in bought and t not in held]
        skipped = [fwd[t] for t in skipped_t]
        if not skipped_t:
            continue
        c_avg, s_avg = _avg(chosen), _avg(skipped)
        graded.append({"ts": r["ts"], "age_days": age, "n_bought": len(bought),
                       "chosen_avg": c_avg, "skipped_avg": s_avg,
                       "regret": None if c_avg is None else round(s_avg - c_avg, 2)})
        if c_avg is not None:
            regrets.append(s_avg - c_avg); c_avgs.append(c_avg); s_avgs.append(s_avg)
            chosen_all += chosen; skipped_all += skipped
            for b in r.get("bought", []):
                v = fwd.get(b["t"])
                if v is not None:
                    for sig in b.get("sig", []):
                        by_signal_chosen.setdefault(sig, []).append(v)
        elif not r.get("blocked"):
            idle_all += skipped
        ranked = sorted(skipped_t, key=lambda t: fwd[t])
        for t in [t for t in ranked[-3:] if fwd[t] > 0]:            # top-3 skipped winners per check
            sec = uni[t].get("s", "off-watchlist")
            m = {"ts": r["ts"], "ticker": t, "fwd_pct": round(fwd[t], 2), "sector": sec,
                 "m1m_then": uni[t].get("m1m"), "congress": uni[t].get("c", 0), "insider": uni[t].get("i", 0)}
            if t not in best_miss or m["fwd_pct"] > best_miss[t]["fwd_pct"]:
                best_miss[t] = m                                       # one row per ticker: its best check
            by_sector_skipped.setdefault(sec, {})[f"{t}@{r['date']}"] = fwd[t]   # distinct ticker-days
        for t in [t for t in ranked[:2] if fwd[t] < 0]:              # bottom-2 skipped losers per check
            sv = {"ts": r["ts"], "ticker": t, "fwd_pct": round(fwd[t], 2)}
            if t not in best_save or sv["fwd_pct"] < best_save[t]["fwd_pct"]:
                best_save[t] = sv

    misses = sorted(best_miss.values(), key=lambda m: -m["fwd_pct"])
    saves = sorted(best_save.values(), key=lambda s: s["fwd_pct"])
    idle = [r for r in rows if not r.get("bought") and not r.get("sold") and not r.get("blocked")]
    return {
        "decisions_recorded": len(_load()), "decisions_graded": len(graded),
        "decisions_with_buys_graded": len(regrets),
        "avg_regret_pct": _avg(regrets),
        "chosen_avg_pct": _avg(c_avgs), "skipped_avg_pct": _avg(s_avgs),
        "idle_universe_avg_pct": _avg(idle_all),
        "picking_beats_random": None if not regrets else bool(_avg(regrets) < 0),
        "chosen_hit_rate": round(sum(x > 0 for x in chosen_all) / len(chosen_all), 2) if chosen_all else None,
        "skipped_hit_rate": round(sum(x > 0 for x in skipped_all) / len(skipped_all), 2) if skipped_all else None,
        "by_signal_chosen": {k: {"n": len(v), "avg_pct": _avg(v)} for k, v in sorted(by_signal_chosen.items())},
        "biggest_misses": misses[:5],
        "biggest_avoided": saves[:3],
        "sectors_most_often_missed": {k: {"n": len(v), "avg_pct": _avg(list(v.values()))} for k, v in
                                      sorted(by_sector_skipped.items(), key=lambda kv: (-len(kv[1]), -max(kv[1].values())))[:5]},
        "idle_checks": len(idle), "idle_share": round(len(idle) / len(rows), 2) if rows else None,
    }

def report(px_now: dict) -> dict:
    """Compact, brain-facing. Empty until there is at least one gradable decision."""
    s = score(px_now)
    if not s["decisions_graded"]:
        return {"decisions_recorded": s["decisions_recorded"], "note": "not enough history to grade yet"}
    s["how_to_read"] = ("regret = how much better the tickers you SKIPPED did than the ones you BOUGHT, "
                        "averaged over graded decisions where you bought something. Positive means your picking "
                        "cost you; negative means it added value over buying at random from the same list. "
                        "Names you already held count as neither. idle_universe_avg_pct = what the list did "
                        "while you sat out (positive = sitting out had a cost). biggest_misses = what you passed "
                        "over and its signal state then; biggest_avoided = what passing saved you.")
    if s["avg_regret_pct"] is None:
        s["note"] = "no graded check contains a buy yet, so regret is undefined; idle_universe_avg_pct is the only grade so far"
    return s

def recent_lessons_with_outcome(px_now: dict, n: int = 8) -> list[dict]:
    """The last few lessons, each paired with how that check actually turned out."""
    rows = [r for r in _load() if r.get("lesson")]
    today = date.today()
    out = []
    for r in rows[-n:]:
        age = (today - date.fromisoformat(r["date"])).days
        fwd = {t: _fwd(u["p"], (px_now.get(t) or {}).get("price")) for t, u in (r.get("universe") or {}).items()}
        fwd = {t: v for t, v in fwd.items() if v is not None}
        bought = {b["t"] for b in r.get("bought", [])}
        chosen = [v for t, v in fwd.items() if t in bought]
        out.append({"ts": r["ts"], "age_days": age, "lesson": r["lesson"],
                    "that_check_avg_pct": _avg(chosen), "n_bought": len(bought)})
    return out
