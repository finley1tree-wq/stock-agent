"""Pick trades WITHOUT the model, from the signals the agent already has.

The model is the best decision-maker here and nothing in this file replaces its judgement: it
cannot read a headline, weigh a filing against a chart, or notice that a story has changed. What
it can do is keep the machine running when the API is unavailable - out of credits, rate limited,
or down - instead of the agent sitting flat and learning nothing.

That matters more than it sounds. Every closed trade is a graded trade, and the counterfactual
loop only learns from days it actually traded. An agent that sits out a week because a billing
page is at zero has lost that week of evidence permanently.

The rules are deliberately the ones with measured support behind them, and nothing else:

  MOMENTUM     one-month momentum must be positive. It is the signal family the 5-year replay
               ranked highest, and while it is not distinguishable from luck at a 1-day horizon,
               nothing else measured better - so it is the honest default rather than a claim.
  THE DIP      entries are taken low in the day's range. Measured over 36,382 stock-days: buying
               high in the range is worth about -5 to -8bp, and day one of this account averaged
               the 76th percentile with six of seven closing red.
  DISCLOSURE   a name with congressional or insider BUYING behind it is preferred, and the filing
               is quoted as the evidence, exactly as the model is required to do.
  NO ETFs      the replay measured broad-index defaults at -0.11% (5d) and -0.55% (21d).

It never invents a reason. Every order it returns carries a concrete number or a named filer, so
a trade it opened is graded and attributed the same way a model trade is - which means the
learning loop keeps working while the credits are out.
"""
from __future__ import annotations

ETFS = {"SPY", "DIA", "GLD", "VNQ", "NLR", "QQQ", "IWM", "XLF", "XLE", "ARKK"}

def _f(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d

def plan(ctx: dict, g: dict) -> dict:
    """Return the same shape brain.decide() returns, built from ctx alone."""
    px = ctx.get("prices") or {}
    allowed = [t for t in (ctx.get("allowed_tickers") or []) if t not in ETFS]
    held = set(ctx.get("current_positions") or {})
    cooling = set(ctx.get("cooling_off_minutes_left") or {})
    want = int(ctx.get("min_positions") or 0)
    have = len(held)
    room = _f(ctx.get("remaining_budget_usd"))
    min_order = _f(g.get("min_order_usd"), 100)

    if ctx.get("no_new_entries_this_check") or room < min_order or have >= want:
        return _empty("autopilot: nothing to add (at the position target, out of room, or inside "
                      "the last max_hold_minutes of the session)")

    cpress = ctx.get("congress_net_buy_pressure") or {}
    ipress = ctx.get("insider_net_buy_pressure") or {}
    who = ctx.get("who_disclosed_it") or {}

    ranked = []
    for t in allowed:
        if t in held or t in cooling:
            continue
        q = px.get(t) or {}
        price, m1m, rng = q.get("price"), q.get("change_1m_pct"), q.get("pct_of_day_range")
        if not price or m1m is None or _f(m1m) <= 0:
            continue                                  # the measured signal, or nothing
        if rng is None or _f(rng) > _f(g.get("max_entry_range_pct"), 85):
            continue                                  # no range yet, or already high in the day
        cp, ip = _f(cpress.get(t)), _f(ipress.get(t))
        # rank: disclosure first (it is the only thing here anyone actually filed), then the dip,
        # then momentum as the tiebreak
        score = (2.0 if cp > 0 else 0) + (1.5 if ip > 0 else 0) + (100 - _f(rng)) / 100 + _f(m1m) / 50
        bits = [f"+{_f(m1m):.1f}% over the month", f"{_f(rng):.0f}% of today's range"]
        if cp > 0:
            names = [w for w in (who.get(t) or [])][:2]
            bits.insert(0, f"congress buying{' (' + ', '.join(map(str, names)) + ')' if names else ''}")
        if ip > 0:
            bits.insert(0, "insider buying (Form 4)")
        ranked.append((score, t, "; ".join(bits)))

    if not ranked:
        return _empty("autopilot: no name passed the screen (needs positive one-month momentum, "
                      "room below the day's high, and it must not be an index fund)")

    ranked.sort(reverse=True)
    take = ranked[:max(0, want - have)]
    # size to fill the gap with what is actually there, inside the owner's band
    each = min(3000.0, max(min_order, room / max(len(take), 1)))
    orders = [{"ticker": t, "usd": round(each, 2), "signals": _signals(why),
               "evidence": why, "why": "autopilot: best available on the measured screen"}
              for _, t, why in take]
    return {
        "deploy_now_usd": round(each * len(orders), 2), "orders": orders, "sells": [], "triggers": [],
        "next_check_minutes": int(g.get("min_decision_minutes", 6) or 6),
        "reasoning": (f"AUTOPILOT (no model call - the API is unavailable). Held {have} of {want} "
                      f"target names with ${room:,.0f} idle, so opened {len(orders)}: "
                      + ", ".join(o["ticker"] for o in orders)
                      + ". Screen: positive one-month momentum, low in the day's range, disclosure "
                        "preferred, no index funds. This is a rule, not judgement - it cannot read "
                        "the news, and it keeps the loop gathering graded trades until the model returns."),
        "lesson": "",
    }

def _signals(why: str) -> list[str]:
    s = ["momentum", "autopilot"]
    if "congress" in why:
        s.append("congress")
    if "insider" in why:
        s.append("insider")
    return s

def _empty(reason: str) -> dict:
    return {"deploy_now_usd": 0.0, "orders": [], "sells": [], "triggers": [],
            "next_check_minutes": None, "reasoning": reason, "lesson": ""}
