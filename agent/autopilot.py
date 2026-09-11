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
  DISCLOSURE   a name with congressional or insider BUYING behind it is preferred, scored by HOW
               MANY distinct people filed and HOW RECENTLY, and the filing is quoted as the
               evidence exactly as the model is required to do. Three members buying the same name
               is three independent decisions; one member is one. That is a sample-size argument,
               not a skill claim.
  SIZE         a disclosed dollar band is used where the filing gives one - a $250k-$500k purchase
               is a larger commitment than a $1k-$15k one.
  ROLE         an officer's Form 4 purchase (CEO, CFO, president, director) outranks a 10%-holder's;
               the first is the literature's informative case, the second is often a fund rebalancing.
  NO ETFs      the replay measured broad-index defaults at -0.11% (5d) and -0.55% (21d).

WHAT IT DELIBERATELY DOES NOT DO: rank by WHICH member filed. The leaderboard in traders.py scores
every member's disclosed buys against SPY from the disclosure date, and it fails its own
significance test - the best member sits at t = 2.18 against a 2.5 bar, no member survives
Benjamini-Hochberg, and the out-of-sample rank correlation is -0.002. traders.weights() therefore
returns {} and nobody is weighted. Ranking names by "whose portfolio is worth copying" would be
ranking by noise, and it is the exact mistake this file is written to avoid. Count of filers and
recency are real information; identity of filer, on this evidence, is not.

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
    ctrades = ctx.get("congress_recent_trades") or []
    itrades = ctx.get("insider_recent_trades") or []
    today = str(ctx.get("datetime_et") or "")[:10]

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
        cbuys = [r for r in ctrades if r.get("ticker") == t and r.get("type") == "buy"]
        ibuys = [r for r in itrades if r.get("ticker") == t and r.get("type") == "buy"]
        # HOW MANY people filed, not merely whether anyone did. Three members buying the same name
        # is three independent decisions; the old binary test scored that the same as one.
        filers = len({r.get("who") for r in cbuys if r.get("who")})
        # An officer buying their own company is the informative case in the literature; a
        # 10%-holder is often a fund rebalancing, so it is worth a fraction, not the same.
        officers = len({r.get("who") for r in ibuys if r.get("who") and _is_officer(r.get("role"))})
        others = len({r.get("who") for r in ibuys if r.get("who")}) - officers
        insiders_n = officers + others
        fresh = _recency_boost(cbuys + ibuys, today)
        officer = officers > 0
        band = max([_amount_band(r.get("amount")) for r in cbuys] or [0])
        # When the raw filings are not in context but net pressure is, use the pressure itself as
        # the count - it IS the number of net buyers. Without this a name with disclosed buying
        # scored zero for it, which is worse than the binary test this replaced.
        crowd = min(filers, 4) if filers else min(max(cp, 0.0), 4.0)

        score = (crowd * 1.2                              # distinct congressional filers, capped
                 + min(officers, 3) * 1.2                 # officers buying their own company
                 + min(others, 3) * 0.4                   # 10%-holders and funds, worth less
                 + (0 if ibuys or not ip > 0 else min(ip, 3) * 0.4)   # insider pressure fallback
                 + band                                   # disclosed dollar band, 0-1
                 + fresh                                  # 0-1, decays over the lookback
                 + (100 - _f(rng)) / 100                  # the dip, measured
                 + _f(m1m) / 50)                          # momentum as the tiebreak
        bits = [f"+{_f(m1m):.1f}% over the month", f"{_f(rng):.0f}% of today's range"]
        if filers:
            names = _names(who.get(t), cbuys)
            amt = next((r.get("amount") for r in cbuys if r.get("amount")), "")
            bits.insert(0, f"{filers} member{'s' if filers > 1 else ''} of congress bought"
                           + (f" ({names})" if names else "")
                           + (f", {amt}" if amt else ""))
        elif cp > 0:
            # No raw filings in context, only net pressure - still name whoever is known, because
            # "Rep. X filed a purchase" is evidence and "congress pressure 2" is barely any.
            names = _names(who.get(t), [])
            bits.insert(0, f"congress net buying ({int(cp)} net buyer{'s' if cp != 1 else ''})"
                           + (f": {names}" if names else ""))
        if insiders_n:
            role = next((r.get("role") for r in ibuys if _is_officer(r.get("role"))), None)
            bits.insert(0, f"{insiders_n} insider{'s' if insiders_n > 1 else ''} bought (Form 4"
                           + (f", incl. {role}" if role else "") + ")")
        elif ip > 0:
            bits.insert(0, "insider net buying (Form 4)")
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

OFFICER = ("ceo", "chief exec", "cfo", "chief financial", "president", "director", "officer", "chairman")

def _is_officer(role) -> bool:
    r = str(role or "").lower()
    return any(k in r for k in OFFICER) and "10 percent" not in r

def _amount_band(amount) -> float:
    """A disclosed range like '$250,001 - $500,000' -> 0..1. Bigger commitment, bigger number."""
    digits = "".join(c for c in str(amount or "") if c.isdigit() or c == " ").split()
    if not digits:
        return 0.0
    try:
        low = float(digits[0])
    except ValueError:
        return 0.0
    for edge, v in ((1_000_000, 1.0), (250_000, 0.8), (50_000, 0.6), (15_000, 0.4), (1_000, 0.2)):
        if low >= edge:
            return v
    return 0.1

def _recency_boost(rows: list[dict], today: str) -> float:
    """1.0 for a filing that landed today, decaying to 0 across a month. A 40-day-old disclosure
    is public knowledge; a fresh one is the only part anybody could still act on."""
    from datetime import date
    if not rows or not today:
        return 0.0
    try:
        t0 = date.fromisoformat(today)
    except ValueError:
        return 0.0
    best = 0.0
    for r in rows:
        d = r.get("disclosure_date") or r.get("filing_date") or r.get("transaction_date")
        try:
            age = (t0 - date.fromisoformat(str(d)[:10])).days
        except (TypeError, ValueError):
            continue
        best = max(best, max(0.0, 1.0 - age / 30.0))
    return best

def _names(entries, rows) -> str:
    """Readable filer names. who_disclosed_it holds dicts, and they were being dumped raw into the
    evidence string - an order's evidence read "congress buying ({'who': 'Gilbert Ray Cisneros'...".
    """
    out = []
    for e in (entries or []):
        n = e.get("who") if isinstance(e, dict) else e
        if n and n not in out:
            out.append(str(n))
    for r in rows:
        n = r.get("who")
        if n and n not in out:
            out.append(str(n))
    return ", ".join(out[:2])

def _signals(why: str) -> list[str]:
    s = ["momentum", "autopilot"]
    if "congress" in why or "member" in why:
        s.append("congress")
    if "insider" in why or "Form 4" in why:
        s.append("insider")
    return s

def _empty(reason: str) -> dict:
    return {"deploy_now_usd": 0.0, "orders": [], "sells": [], "triggers": [],
            "next_check_minutes": None, "reasoning": reason, "lesson": ""}
