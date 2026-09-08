"""Safety checks that run before the agent is allowed to trade.

Every check returns (ok, message). run.py refuses to trade if any hard check fails, and logs why.
Nothing here can be overridden by the brain — these sit outside its reach, like the guardrails.
"""
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAUSE = ROOT / "PAUSE"

def paused() -> tuple[bool, str]:
    """Kill switch: create a file named PAUSE in the folder and the agent stops trading."""
    if PAUSE.exists():
        why = PAUSE.read_text().strip() or "no reason given"
        return False, f"PAUSED by the PAUSE file ({why}). Delete it to resume."
    return True, ""

def ledger_intact(broker) -> tuple[bool, str]:
    """cash + cost basis must equal money put in + realised P/L. If not, the ledger is corrupt."""
    p = getattr(broker, "p", None)
    if not p:
        return True, ""
    cost = sum(v["qty"] * v["avg_cost"] for v in p["positions"].values())
    left, right = p["cash"] + cost, p["deposited"] + p["realized_pnl"]
    if abs(left - right) > 0.05:
        return False, (f"LEDGER MISMATCH: cash {p['cash']:.2f} + cost {cost:.2f} = {left:.2f}, "
                       f"but deposited {p['deposited']:.2f} + realised {p['realized_pnl']:.2f} = {right:.2f}. "
                       f"Refusing to trade. Inspect portfolio.json.")
    for sym, v in p["positions"].items():
        if v["qty"] <= 0 or v["avg_cost"] <= 0:
            return False, f"LEDGER MISMATCH: {sym} has qty={v['qty']} avg_cost={v['avg_cost']}. Refusing to trade."
    return True, ""

def drawdown_ok(broker, limit_pct: float) -> tuple[bool, str]:
    """Circuit breaker: stop buying if the portfolio is down more than limit_pct against money put in."""
    if not hasattr(broker, "summary") or not limit_pct:
        return True, ""
    s = broker.summary()
    dep = s.get("deposited") or 0
    if dep <= 0:
        return True, ""
    dd = (s["equity"] / dep - 1) * 100
    if dd < -abs(limit_pct):
        return False, (f"CIRCUIT BREAKER: equity ${s['equity']:.2f} is {dd:.1f}% below the ${dep:.2f} put in "
                       f"(limit {limit_pct}%). No new buys. Review, then raise max_drawdown_pct or create/delete PAUSE.")
    return True, ""

def sane_prices(px: dict, max_daily_move_pct: float) -> tuple[dict, list[str]]:
    """Drop any quote that is missing, non-positive, or moved absurdly in a day (bad tick / bad split)."""
    good, dropped = {}, []
    for t, q in px.items():
        p = q.get("price")
        if p is None or p <= 0:
            dropped.append(f"{t}: no/zero price"); continue
        move = q.get("change_1d_pct")
        if max_daily_move_pct and move is not None and abs(move) > abs(max_daily_move_pct):
            dropped.append(f"{t}: {move:+.1f}% in a day looks like a bad tick"); continue
        good[t] = q
    return good, dropped

def preflight(broker, g: dict) -> tuple[bool, list[str]]:
    """All hard checks. Returns (may_trade, messages)."""
    msgs, ok = [], True
    for check, args in ((paused, ()), (ledger_intact, (broker,)), (drawdown_ok, (broker, g.get("max_drawdown_pct", 0)))):
        passed, m = check(*args)
        if not passed:
            ok = False
            msgs.append(m)
    return ok, msgs
