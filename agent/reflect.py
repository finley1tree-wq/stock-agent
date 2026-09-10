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

def last_dropped(n: int = 1) -> list[str]:
    """What the guardrails threw away at the last n checks, and why.

    The brain never saw this: an order silently shrunk or dropped looked, from its side, like a
    decision that simply had no effect. Handing the reasons back is how it stops repeating them.
    """
    rows = _load()[-n:]
    return [d for r in rows for d in (r.get("dropped") or [])]

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

HORIZONS = {"1d": 1, "5d": 5, "21d": 21}      # a decision is graded once at each of these ages

def _fwd(then: float, now: float | None) -> float | None:
    return None if not then or not now else (now / then - 1) * 100

def _avg(xs): return round(sum(xs) / len(xs), 2) if xs else None

def _grade_row(r: dict, px_now: dict) -> dict | None:
    """Score one past decision against prices as they stand right now. Called once per horizon."""
    uni = r.get("universe") or {}
    bought = {b["t"] for b in r.get("bought", [])}
    held = {t for t, u in uni.items() if u.get("h")}
    fwd = {t: _fwd(u["p"], (px_now.get(t) or {}).get("price")) for t, u in uni.items()}
    fwd = {t: v for t, v in fwd.items() if v is not None}
    if not fwd:
        return None
    chosen = [v for t, v in fwd.items() if t in bought]
    skipped_t = [t for t in fwd if t not in bought and t not in held]
    skipped = [fwd[t] for t in skipped_t]
    c_avg, s_avg = _avg(chosen), _avg(skipped)
    g = {"n_bought": len(bought), "n_skipped": len(skipped_t), "chosen_avg": c_avg, "skipped_avg": s_avg,
         "universe_fully_bought": not skipped_t,
         "frac_universe_bought": round(len(bought) / len(fwd), 3) if fwd else 0.0}
    # Buying the entire universe used to make a check unscoreable, which is a free way to dodge
    # being graded. It now scores as zero regret and is counted, so the escape hatch is closed.
    g["regret"] = None if c_avg is None else (0.0 if not skipped_t else round(s_avg - c_avg, 2))
    by_sig = {}
    for b in r.get("bought", []):
        v = fwd.get(b["t"])
        if v is not None:
            for sig in b.get("sig", []):
                by_sig.setdefault(sig, []).append(v)
    g["by_signal"] = {k: [len(v), _avg(v)] for k, v in by_sig.items()}
    if skipped_t:
        # Keep the top few winners and worst few losers it passed on, not just the single extreme:
        # with one per check the same ticker fills the whole list and the next-best miss is invisible.
        ranked = sorted(skipped_t, key=lambda t: fwd[t])
        g["misses"] = [{"ticker": t, "fwd_pct": round(fwd[t], 2), "sector": uni[t].get("s", "off-watchlist"),
                        "m1m_then": uni[t].get("m1m"), "congress": uni[t].get("c", 0),
                        "insider": uni[t].get("i", 0)}
                       for t in reversed(ranked[-3:]) if fwd[t] > 0]
        g["avoided"] = [{"ticker": t, "fwd_pct": round(fwd[t], 2)} for t in ranked[:2] if fwd[t] < 0]
    return g

def grade_due(px_now: dict) -> list[dict]:
    """Fill in any grade that has come of age, exactly once, and never revisit it.

    Grading every past decision against today's price is the mistake this replaces: it mixes a
    one-day-old decision with a one-month-old one, and every number moves together whenever the
    market moves, so hundreds of rows carry the information of roughly a single observation.
    """
    rows = _load()
    today = date.today()
    changed = False
    for r in rows:
        if not r.get("universe"):
            continue
        try:
            age = (today - date.fromisoformat(r["date"])).days
        except Exception:
            continue
        g = r.setdefault("grades", {})
        for name, h in HORIZONS.items():
            if name in g or age < h:
                continue
            snap = _grade_row(r, px_now)
            if snap:
                snap["graded_on"] = today.isoformat()
                g[name] = snap
                changed = True
    if changed:
        _save(rows)
    return rows

def score(px_now: dict, max_rows: int = 400, horizon: str = "1d") -> dict:
    """Aggregate the fixed-horizon grades. Only decisions old enough to have an answer count."""
    rows = grade_due(px_now)[-max_rows:]
    graded = [(r, r["grades"][horizon]) for r in rows if (r.get("grades") or {}).get(horizon)]
    with_buys = [(r, g) for r, g in graded if g.get("regret") is not None]
    regrets = [g["regret"] for _, g in with_buys]
    c_avgs = [g["chosen_avg"] for _, g in with_buys if g["chosen_avg"] is not None]
    s_avgs = [g["skipped_avg"] for _, g in with_buys if g["skipped_avg"] is not None]
    idle_uni = [g["skipped_avg"] for r, g in graded
                if g.get("regret") is None and not r.get("blocked") and g.get("skipped_avg") is not None]
    by_signal: dict[str, list] = {}
    for _, g in with_buys:
        for k, (n, avg) in (g.get("by_signal") or {}).items():
            if avg is not None:
                cur = by_signal.setdefault(k, [0, 0.0])
                cur[0] += n; cur[1] += avg * n
    best_miss, best_save, by_sector = {}, {}, {}
    for r, g in graded:
        for m in (g.get("misses") or []):
            if m["ticker"] not in best_miss or m["fwd_pct"] > best_miss[m["ticker"]]["fwd_pct"]:
                best_miss[m["ticker"]] = m
            by_sector.setdefault(m.get("sector", "off-watchlist"), set()).add((m["ticker"], r.get("date")))
        for a in (g.get("avoided") or []):
            if a["ticker"] not in best_save or a["fwd_pct"] < best_save[a["ticker"]]["fwd_pct"]:
                best_save[a["ticker"]] = a
    # idleness counts only checks the agent could have acted on; a guardrail hold is not a choice
    idle = [r for r in rows if not r.get("bought") and not r.get("sold") and not r.get("blocked")]
    blocked = [r for r in rows if r.get("blocked")]
    dates = {r["date"] for r, _ in graded}
    return {
        "horizon": horizon,
        "decisions_recorded": len(_load()), "decisions_graded": len(graded),
        "decisions_with_buys_graded": len(with_buys),
        "independent_days_graded": len(dates),
        "avg_regret_pct": _avg(regrets),
        "chosen_avg_pct": _avg(c_avgs), "skipped_avg_pct": _avg(s_avgs),
        "idle_universe_avg_pct": _avg(idle_uni),
        "picking_beats_random": None if not regrets else bool(_avg(regrets) < 0),
        "avg_fraction_of_universe_bought": _avg([g["frac_universe_bought"] for _, g in graded]),
        "checks_that_bought_everything": sum(1 for _, g in graded if g.get("universe_fully_bought")),
        "by_signal_chosen": {k: {"n": n, "avg_pct": round(tot / n, 2)} for k, (n, tot) in sorted(by_signal.items()) if n},
        "biggest_misses": sorted(best_miss.values(), key=lambda m: -m["fwd_pct"])[:5],
        "biggest_avoided": sorted(best_save.values(), key=lambda m: m["fwd_pct"])[:3],
        "sectors_most_often_missed": {k: {"n": len(v)} for k, v in
                                      sorted(by_sector.items(), key=lambda kv: -len(kv[1]))[:5]},
        "idle_checks": len(idle), "blocked_checks": len(blocked),
        "idle_share": round(len(idle) / max(1, len(rows) - len(blocked)), 2) if rows else None,
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
    # An edge measured on a handful of days is indistinguishable from luck. Say so, in the report,
    # so the number is never read as a finding before it is one.
    days = s.get("independent_days_graded") or 0
    s["evidence_strength"] = ("none" if days == 0 else "anecdote" if days < 10
                              else "weak" if days < 30 else "suggestive" if days < 60 else "usable")
    s["how_many_days_before_this_means_anything"] = 30
    if days < 30:
        s["warning"] = (f"only {days} independent day(s) graded: treat every number here as a story, not a finding. "
                        "Do not change strategy on it.")
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
