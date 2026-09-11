"""Entry point. Designed to run repeatedly through the trading day (about every 30 minutes
while the US market is open - see .github/workflows/agent.yml or autopilot-mac.command).
Each run is one "check".

    python -m agent.run            # one check: gather signals, ask the brain, maybe buy/sell, log
    python -m agent.run --report   # print portfolio + budget + track record, decide nothing
    python -m agent.run --force    # skip the weekend / market-open checks (testing; sim still fills at last price)

Brokers (BROKER in .env): sim (default, pretend money, real prices), alpaca (paper or live), ibkr.
"""
import json
import sys
import time as clock
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from . import config, prices, politicians, insiders, news, state, brain, learn, publish as pub, safety, backtest, reflect, triggers, instruments, traders, wallets, replay, autopilot
from .redact import redact
from .broker_sim import is_trading_day, close_time, last_trading_day_of_week

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "log.md"
ET = ZoneInfo("America/New_York")
MARKET_OPEN = time(9, 30)
# Every label the code itself emits must be here, or _clean_signals silently rewrites it to
# "unspecified" and the learning loop can never attribute a result to the feature that caused it.
SIGNALS = {"congress", "insider", "followed_person", "news", "momentum", "track_record", "etf_default",
           "risk_management", "dip_entry", "time_stop", "intraday_limit", "standing_order",
           "auto_bracket", "patience"}

def log(line: str) -> None:
    print(line)
    with open(LOG, "a") as f:
        f.write(line + "\n")

def _parse_hm(s: str, default: time) -> time:
    try:
        h, m = str(s).split(":"); return time(int(h), int(m))
    except Exception:
        return default

def checks_left_today(now: datetime, every_min: int) -> int:
    """Checks remaining before today's real close (13:00 ET on early-close days)."""
    c = close_time(now.date())
    close = now.replace(hour=c.hour, minute=c.minute, second=0, microsecond=0)
    mins = (close - now).total_seconds() / 60
    return max(0, int(mins // max(1, every_min)))

def is_cleanup_check(now: datetime, g: dict, every_min: int) -> bool:
    """The forced deploy-everything check: last trading day of the week (Friday, or Thursday before a holiday
    Friday), at/after the configured time or the last slot before the real close, whichever comes first."""
    # A weekly "deploy every remaining dollar in the last hour" rule cannot coexist with a
    # 30-minute hold: it would dump the whole account at 15:00 and carry the late tranche over
    # the weekend. Under an intraday clock there is no such thing as idle weekly money.
    if int(g.get("max_hold_minutes", 0) or 0) > 0:
        return False
    today = now.date()
    if not last_trading_day_of_week(today):
        return False
    close_dt = datetime.combine(today, close_time(today), ET)
    configured = datetime.combine(today, _parse_hm(g.get("friday_cleanup_after_et", "15:30"), time(15, 30)), ET)
    after = min(configured, close_dt - timedelta(minutes=2 * every_min))   # at least the last two open slots
    return now >= after or checks_left_today(now, every_min) <= 1

def past_entry_cutoff(now: datetime, g: dict) -> bool:
    """No NEW position inside the last max_hold_minutes of the session.

    A position bought at 15:40 cannot be closed by the 30-minute clock: once the market is shut
    nothing runs, so it is carried overnight - or over a weekend - on a rule that promised half
    an hour. Two extra minutes cover tick latency."""
    mins = int(g.get("max_hold_minutes", 0) or 0)
    if mins <= 0 or not is_trading_day(now.date()):
        return False
    close_dt = datetime.combine(now.date(), close_time(now.date()), ET)
    return now >= close_dt - timedelta(minutes=mins + 2)

def at_session_end(now: datetime, minutes_before: int = 3) -> bool:
    """Inside the final minutes before the close: flatten whatever is still open."""
    if not is_trading_day(now.date()):
        return False
    close_dt = datetime.combine(now.date(), close_time(now.date()), ET)
    return close_dt - timedelta(minutes=minutes_before) <= now < close_dt

def market_open_fallback(now: datetime) -> bool:
    """Used only when the broker can't tell us."""
    return is_trading_day(now.date()) and MARKET_OPEN <= now.time() < close_time(now.date())

def make_broker(cfg: dict):
    env = cfg["env"]
    if env["broker"] == "ibkr":
        from .broker_ibkr import IBKRBroker
        return IBKRBroker(env)
    if env["broker"] == "alpaca":
        from .broker import Broker
        return Broker(env)
    from .broker_sim import SimBroker
    b = SimBroker(env, cfg.get("sim"))
    b.spread_pct = float(cfg.get("guardrails", {}).get("spread_cost_pct", 0) or 0)
    return b

def _clean_signals(o: dict) -> list[str]:
    raw = o.get("signals") or []
    if not isinstance(raw, list):
        raw = [raw]
    return [s for s in raw if isinstance(s, str) and s in SIGNALS] or ["unspecified"]

def _full_deployment(today, g: dict) -> dict:
    """Finley's phase two: from a set date, every dollar works and it concentrates.

    Phase one is not timidity - it is the evidence-gathering week. Phase two is his explicit
    instruction to stop spreading thin, and it arrives on a date rather than on a feeling so it
    cannot quietly never happen.
    """
    from datetime import date as _d
    start = str(g.get("full_deployment_from") or "")
    try:
        on = _d.fromisoformat(start) <= today
    except Exception:
        return {"active": False}
    return {"active": on, "starts": start, "max_names": int(g.get("full_deployment_max_names", 3) or 3),
            "instruction": ("Deploy every available dollar, concentrated in at most max_names positions of "
                            "highest conviction. Quality over quantity: a large position in one idea you can "
                            "defend beats the same money spread across five you cannot. Every position still "
                            "carries its ATR-sized stop, so concentration widens the outcome, it does not "
                            "remove the floor.") if on else
                           f"Not yet - phase one until {start}. Deploy what the evidence justifies and let the loop learn."}

def apply_guardrails(plan: dict, allowed: set[str], remaining_week: float, st: dict, g: dict, cleanup: bool,
                     px: dict | None = None, chase_check: bool = True,
                     sector_of: dict | None = None) -> tuple[list[dict], list[str], list[dict]]:
    """Buys. Returns (orders_to_fill_now, dropped_reasons, orders_to_leave_as_limits).
    Caps enforced inside one check as well as across the day/week: per-ticker/week (running), per-day (running),
    per-day order count, min order, evidence required, no same-day rebuy, no negative or duplicate tickers."""
    budget_week = g["_weekly_budget"]
    dropped: list[str] = []
    deferred: list[dict] = []
    # The day cap is NET of sells on purpose. Counting gross money put to work would mean that after
    # one full deploy-and-sell cycle nothing could be bought for the rest of the day - which under a
    # 30-minute clock is a lockout by lunchtime, the opposite of what the owner asked for. Gross
    # figures exist (deployed_today) for the dashboard and the brain, never for the cap.
    day_cap = max(0.0, budget_week * g["max_daily_deploy_pct"] / 100 - st.get("spent_today", 0.0))
    cap_now = remaining_week if cleanup else min(remaining_week, day_cap)
    # deploy_now_usd is a ceiling. When the plan omits it (a standing-order fill, a plan that only
    # sized its orders) the sum of the orders is the fallback - it is never a floor, so an explicit
    # smaller number still binds.
    asked = sum(max(0.0, float(o.get("usd", 0) or 0)) for o in (plan.get("orders") or []) if isinstance(o, dict))
    deploy = min(max(0.0, float(plan.get("deploy_now_usd", plan.get("deploy_today_usd", 0)) or 0)) or asked, cap_now)
    if cleanup:
        deploy = remaining_week
    orders_left = int(g.get("max_orders_per_day", 8)) - int(st.get("orders_today", 0))
    if orders_left <= 0 and not cleanup:
        return [], ["max_orders_per_day reached"], []
    merged: dict[str, dict] = {}
    for o in plan.get("orders", []) or []:
        if not isinstance(o, dict):
            continue
        t = str(o.get("ticker", "")).upper()
        if t not in allowed:
            dropped.append(f"{t}: not in allowed list"); continue
        cooldown = int(g.get("rebuy_cooldown_minutes", 0) or 0)
        if cooldown:
            # With a 30-minute clock, banning a name for the whole day after one round trip
            # exhausts the candidate list before lunch. A cooldown keeps wash-trading off the
            # table without permanently retiring the name.
            last = (st.get("sold_ts") or {}).get(t)
            if last and (datetime.now(ET).timestamp() - float(last)) / 60 < cooldown:
                dropped.append(f"{t}: sold {((datetime.now(ET).timestamp()-float(last))/60):.0f} min ago, cooling off"); continue
        elif t in st.get("sold_today", []):
            dropped.append(f"{t}: sold today, no same-day rebuy"); continue
        if not str(o.get("evidence", "")).strip():
            dropped.append(f"{t}: no evidence given"); continue
        usd = max(0.0, float(o.get("usd", 0) or 0))          # never negative
        if t in merged:                                       # repeated ticker -> one order
            merged[t]["usd"] += usd; continue
        merged[t] = {**o, "ticker": t, "usd": usd}
    orders = [o for o in merged.values() if o["usd"] > 0]
    total = sum(o["usd"] for o in orders) or 1.0
    if not cleanup:
        deploy = min(deploy, total)      # dropped orders release their dollars, they do not donate them
    per_cap = budget_week * g["max_per_ticker_pct"] / 100
    by_ticker = dict(st.get("by_ticker", {}))
    # Sector concentration: five names in one bucket is one position wearing five hats. CCJ and
    # NLR were two thirds of a book and the same uranium bet.
    sector_of = sector_of or {}
    sector_cap = budget_week * float(g.get("max_per_sector_pct", 100) or 100) / 100
    by_sector: dict[str, float] = {}
    for tk, amt in by_ticker.items():
        sec = sector_of.get(tk)
        if sec:
            by_sector[sec] = by_sector.get(sec, 0.0) + float(amt)
    left = deploy
    out = []
    # Four buys per check could never build a five-name book from flat. The cap now follows the
    # target position count, so reaching min_positions is arithmetically possible in one decision.
    per_check = max(int(g.get("min_positions", 4) or 4) + 2, 4)
    for o in orders[:max(orders_left, 1) if cleanup else min(per_check, orders_left)]:
        room = per_cap - by_ticker.get(o["ticker"], 0.0)
        sec = sector_of.get(o["ticker"])
        if sec:
            room = min(room, sector_cap - by_sector.get(sec, 0.0))
        usd = min(deploy * o["usd"] / total, room, left)
        if usd < g["min_order_usd"]:
            why = f"sector {sec} at its {g.get('max_per_sector_pct')}% cap" if (sec and sector_cap - by_sector.get(sec, 0.0) < g["min_order_usd"]) else "below min order after caps"
            dropped.append(f"{o['ticker']}: {why} (${usd:.2f})"); continue
        usd = round(usd, 2)
        row = {"ticker": o["ticker"], "usd": usd, "why": str(o.get("why", "")), "signals": _clean_signals(o), "evidence": str(o.get("evidence", ""))[:200]}
        # Buying at market in the top of the day's range is paying for a move that already
        # happened. On day one the average entry sat at the 76th percentile of the range and six
        # of seven closed red. Rather than refuse the idea, take it at a price worth having: the
        # order becomes a resting limit lower down, and fills only if the market comes back.
        q = (px or {}).get(o["ticker"]) or {}
        pos = q.get("pct_of_day_range")
        cap = float(g.get("max_entry_range_pct", 100) or 100)
        if chase_check and pos is not None and pos > cap and not cleanup:
            lo, hi = q.get("day_low"), q.get("day_high")
            at = float(g.get("chase_limit_at_pct", 40) or 40)
            level = lo + (hi - lo) * at / 100 if (lo and hi and hi > lo) else None
            if level and level > 0:
                deferred.append({**row, "limit_price": round(level, 4), "was_at_pct": pos})
                dropped.append(f"{o['ticker']}: {pos:.0f}% up today's range — resting a limit at ${level:.2f} instead of chasing")
                continue
        # Budget is consumed only by an order that actually fills now. A deferred limit was
        # charging the day's allowance for money it never spent.
        by_ticker[o["ticker"]] = by_ticker.get(o["ticker"], 0.0) + usd
        if sec:
            by_sector[sec] = by_sector.get(sec, 0.0) + usd
        left -= usd
        out.append(row)
    return out, dropped, deferred

def apply_sell_guardrails(plan: dict, positions: dict, st: dict, g: dict, hold_exempt: set | None = None) -> tuple[list[dict], list[str]]:
    """Sells. Must hold it, must be old enough, must have evidence, daily count cap, one sell per ticker per check."""
    dropped: list[str] = []
    if g.get("only_buy", False):
        return [], (["selling disabled (only_buy)"] if plan.get("sells") else [])
    left = int(g.get("max_sells_per_day", 3)) - int(st.get("sells_today", 0))
    out, seen, counted = [], set(), 0
    for s in plan.get("sells", []) or []:
        if not isinstance(s, dict):
            continue
        t = str(s.get("ticker", "")).upper()
        pos = positions.get(t)
        if not pos:
            dropped.append(f"sell {t}: not held"); continue
        if t in seen:
            dropped.append(f"sell {t}: duplicate in plan"); continue
        since_buy = pos.get("days_since_buy", pos.get("days_held", 999))
        # a stop-loss or trailing stop is protection, not churn, so the hold clock does not gag it
        if since_buy < int(g.get("min_hold_days", 0)) and t not in (hold_exempt or set()):
            dropped.append(f"sell {t}: last bought {since_buy}d ago < min_hold_days"); continue
        if not str(s.get("evidence", "")).strip():
            dropped.append(f"sell {t}: no evidence given"); continue
        pct = max(0.0, min(100.0, float(s.get("pct_of_position", 0) or 0)))
        if pct <= 0:
            continue
        # A time stop or stop-loss is protection, not churn (same reasoning as min_hold_days
        # above): counting it against the daily cap could leave a 30-minute position open overnight.
        if t not in (hold_exempt or set()):
            if counted >= max(left, 0):
                dropped.append(f"sell {t}: max_sells_per_day reached"); continue
            counted += 1
        seen.add(t)
        out.append({"ticker": t, "pct": pct, "qty": pos["qty"] * pct / 100, "why": str(s.get("why", "")), "signals": _clean_signals(s), "evidence": str(s.get("evidence", ""))[:200]})
    return out, dropped

def gather_signals(cfg: dict, env: dict, g: dict, held: list[str]) -> dict:
    """Congress + insider feeds, allowed universe, headlines. Shared by a check and by --publish."""
    watch = config.all_watchlist_tickers(cfg)
    followed_people = cfg.get("followed_people") or []
    feed_status = {}
    ctrades = politicians.recent_trades(env, g["politician_lookback_days"])
    feed_status["congress"] = "ok" if ctrades else "unavailable (all sources failed or no recent rows)"
    feed_status["congress_source"] = politicians.last_source or ""
    feed_status["congress_notes"] = "; ".join(politicians.last_errors)[:300]
    # Rank the disclosers by what their past filings were actually worth against the index, and let
    # that tilt the pressure. Following all of Congress equally is following the average, and the
    # average includes everyone who is bad at this.
    board = traders.refresh(politicians.recent_trades(env, 3650) if ctrades else [])
    cpressure = politicians.buy_pressure(ctrades, cfg.get("followed_politicians") or [], traders.weights(board))
    itrades = insiders.recent_trades(env, g.get("insider_lookback_days", 30))
    feed_status["insiders"] = "ok" if itrades else ("no key" if not env.get("fmp_key") else "unavailable")
    ipressure = insiders.buy_pressure(itrades, followed_people)
    allowed = set(watch)
    if g["allow_politician_tickers"]:
        allowed |= {t for t, sc in list(cpressure.items())[:15] if sc > 0}
    if g.get("allow_insider_tickers", True):
        allowed |= {t for t, sc in list(ipressure.items())[:15] if sc > 0}
    # A ticker off the feeds is not necessarily the company's ordinary shares. GOOGN is Alphabet
    # preferred depositary stock, not Alphabet. Make anything off-watchlist prove what it is.
    # Traders followed on-chain, from wallets.txt. Empty until addresses are added.
    try:
        wmoves, wstatus = wallets.check_due()
    except Exception as e:
        wmoves, wstatus = [], {"error": str(e)[:80]}
    allowed, rejected = instruments.filter_allowed(allowed, watch)
    feed_status["excluded_instruments"] = rejected[:12]
    return {"watch": watch, "followed_people": followed_people, "ctrades": ctrades, "cpressure": cpressure,
            "itrades": itrades, "ipressure": ipressure, "allowed": allowed, "feed_status": feed_status,
            "instrument_notes": rejected, "board": board,
            "wallet_moves": wmoves, "wallet_status": wstatus}

def site_signals(sig: dict, headlines: dict, people: dict, learning: dict | None = None) -> dict:
    return {"allowed": sorted(sig["allowed"]), "feed_status": sig["feed_status"], "learning": learning or {},
            "disclosure_leaderboard": (sig.get("board") or {}).get("leaders", [])[:12],
            "disclosure_leaderboard_meta": {k: (sig.get("board") or {}).get(k) for k in ("built", "horizon_days", "buys_scored", "measured_from", "benchmark", "caveat")},
            "disclosure_significance": traders.significance(sig.get("board") or {}),
            "wallet_moves": wallets.summary(sig.get("wallet_moves") or [], 12),
            "wallet_status": sig.get("wallet_status") or {},
            "congress_trades": sig["ctrades"][:60], "congress_pressure": dict(list(sig["cpressure"].items())[:20]),
            "insider_trades": sig["itrades"][:60], "insider_pressure": dict(list(sig["ipressure"].items())[:20]),
            "headlines": headlines, "people_news": people}

def publish_only() -> None:
    """Refresh site/data without asking the brain (used by --publish and to seed the dashboard)."""
    cfg = config.load_config(); env, g = cfg["env"], cfg["guardrails"]
    broker = make_broker(cfg)
    held = broker.held_tickers() if hasattr(broker, "held_tickers") else []
    sig = gather_signals(cfg, env, g, held)
    headlines = news.ticker_headlines(sorted(sig["allowed"] | set(held)), per=int(g.get("news_headlines_per_ticker", 3)))
    people = news.people_news(sig["followed_people"], per=4)
    if getattr(broker, "name", "") == "sim":
        px = prices.snapshot(sorted(set(held)))
        if hasattr(broker, "set_prices"): broker.set_prices(px)
        broker.write_report()
    pub.publish(cfg, site_signals(sig, headlines, people), note="published without a decision",
                working_orders=triggers.summary(prices.snapshot(sorted(sig["allowed"]))))
    print("site/data refreshed")


def _at_price(broker, sym: str, price: float, fn):
    """Fill this one order at the standing order's own price, not the price at check time."""
    px_map = getattr(broker, "prices", None)
    if not isinstance(px_map, dict):
        return fn()                                    # a real broker prices its own fills
    saved = px_map.get(sym)
    saved_spread = getattr(broker, "spread_pct", 0.0)
    px_map[sym] = float(price)
    broker.spread_pct = 0.0                            # it gets the level it asked for; stops already
    try:                                               # carry their own slippage in the fill price
        return fn()
    finally:
        broker.spread_pct = saved_spread
        if saved is None:
            px_map.pop(sym, None)
        else:
            px_map[sym] = saved

def _bracket_cfg(g: dict) -> dict:
    """The auto_bracket block WITH the budget folded in.

    Order sizes are a fraction of the weekly budget now, and the bracket only ever received its
    own sub-dict - so without this the scale-in size silently computes to zero and the averaging-in
    orders quietly stop existing. Caught by the basket test, which is exactly what it is for.
    """
    return {**(g.get("auto_bracket") or {}), "_weekly_budget": float(g.get("_weekly_budget", 0) or 0),
            "_max_hold_minutes": float(g.get("max_hold_minutes", 0) or 0)}

def time_stops(now, broker, positions, st, g, log_fn):
    """Close anything that has sat still too long.

    A stop caps what a bad idea costs and a target banks a good one, but neither says anything
    about an idea that simply goes nowhere. Capital parked in a name that is not working is
    capital not working, so a position older than max_hold_days is closed unless it is genuinely
    ahead. This is the rule that stops the book silently becoming a buy-and-hold portfolio.
    """
    days = int(g.get("max_hold_days", 0) or 0)
    mins = int(g.get("max_hold_minutes", 0) or 0)
    if (not days and not mins) or not hasattr(broker, "sell_qty"):
        return [], 0
    keep = float(g.get("time_stop_min_gain_pct", 0) or 0)
    stale = []
    for t, pos in (positions or {}).items():
        pl = float(pos.get("unrealized_plpc") or 0)
        held_m = pos.get("minutes_held")
        # An intraday clock, when one is set, overrides the daily one: this is the rule that makes
        # the agent take the trade it has rather than wait for one it might get. It fires whether
        # the position is up or down - the point is the time, not the outcome.
        if mins and held_m is not None and held_m >= mins:
            stale.append({"ticker": t, "pct_of_position": 100,
                          "why": f"held {held_m} min, the {mins}-minute limit: out regardless",
                          "evidence": f"bought {held_m} min ago, {pl:+.2f}% unrealised",
                          "signals": ["time_stop", "intraday_limit"]})
            continue
        if not days or int(pos.get("days_held", 0)) < days:
            continue
        if pl >= keep:
            log_fn(f"  (holding {t}: {pos['days_held']}d old but {pl:+.2f}%, letting it run)")
            continue
        stale.append({"ticker": t, "pct_of_position": 100, "why": f"held {pos['days_held']}d and only {pl:+.2f}%: the idea has not worked",
                      "evidence": f"opened {pos.get('days_held')}d ago, {pl:+.2f}% unrealised", "signals": ["time_stop", "risk_management"]})
    if not stale:
        return [], 0
    return _forced_sells(now, broker, positions, st, g, log_fn, stale, "time_stop", "time stop")

def _forced_sells(now, broker, positions, st, g, log_fn, stale: list[dict], trigger: str, label: str):
    """Execute protective sells: exempt from the hold clock and from the daily sell cap."""
    sells, dropped = apply_sell_guardrails({"sells": stale}, positions, st, g, hold_exempt={s["ticker"] for s in stale})
    for d in dropped:
        log_fn(f"  (dropped {d})")
    out, did = [], 0
    for sl in sells:
        rec = broker.sell_qty(sl["ticker"], sl["qty"])
        if str(rec.get("status", "")).startswith("rejected"):
            log_fn(f"- SELL {sl['ticker']} [{rec['status']}]"); continue
        full = {**rec, "date": str(now.date()), "time_et": now.strftime("%H:%M"), "ts": int(now.timestamp()),
                "why": sl["why"], "signals": sl["signals"], "evidence": sl["evidence"], "trigger": trigger}
        state.record_sell(st, sl["ticker"], full, float(rec.get("proceeds", 0) or 0)); state.save(st)
        learn.record_sell(full, signals=sorted(set(sl["signals"]) | set(learn.entry_signals(sl["ticker"]))), evidence=sl["evidence"], hour_et=now.hour)
        triggers.cancel_position_orders(sl["ticker"], now, f"{label} closed the position")
        out.append(sl); did += 1
        log_fn(f"- SELL 100% {sl['ticker']} [{label}] -> ${rec.get('proceeds', 0):.2f} ({rec.get('realized_pct', 0):+.2f}%) — {sl['why']}")
    return out, did

def session_end_flatten(now, broker, positions, st, g, log_fn):
    """Nothing is carried past the bell under an intraday clock. Runs in the last minutes."""
    if int(g.get("max_hold_minutes", 0) or 0) <= 0 or not positions or not hasattr(broker, "sell_qty"):
        return [], 0
    stale = [{"ticker": t, "pct_of_position": 100,
              "why": "session ending: a 30-minute rule cannot carry a position overnight",
              "evidence": f"{pos.get('minutes_held')} min held, {float(pos.get('unrealized_plpc') or 0):+.2f}% unrealised, market closes in minutes",
              "signals": ["time_stop", "session_close"]} for t, pos in positions.items()]
    return _forced_sells(now, broker, positions, st, g, log_fn, stale, "session_close", "session close")

def fill_standing_orders(now, today, broker, positions, px, st, g, allowed, remaining, sector_of, cpressure, log_fn,
                         no_new_entries: bool = False):
    """Fire any standing order whose level the market reached since the last check.

    Runs BEFORE the brain, so the brain sees the resulting portfolio. Every fill still goes through
    the ordinary guardrails and the ordinary ledger; the only difference is the fill price and the
    fact that the decision was made at an earlier check.
    """
    live = [o for o in triggers.all_orders() if o.get("status") == "working"]
    if not live:
        return [], [], 0
    # Replay from the start of the bar that was still forming at the previous pass, not from the
    # previous pass itself. With a 60-second cadence and 5-minute bars, a since_ts equal to the last
    # check meant every completed bar was only ever seen while forming - its true low could land
    # after the pass and never be replayed. Consecutive windows now overlap by exactly one bar.
    since = int(st.get("last_bar_ts") or st.get("last_check_ts", 0) or 0)
    bars = prices.intraday(sorted({o["ticker"] for o in live}), since_ts=since)
    fires, notes = triggers.evaluate(now, px, bars, set(positions), float(g.get("trigger_slippage_pct", 0.05)))
    for n in notes:
        log_fn(f"  ({n})")
    if not fires:
        return [], [], 0
    filled_buys, filled_sells, did = [], [], 0

    sell_fires = [f for f in fires if f["kind"] in triggers.SELL_KINDS]
    if sell_fires and hasattr(broker, "sell_qty"):
        fmap = {}
        for f in sell_fires:
            if f["ticker"] in fmap:
                triggers.close(f["id"], now, "cancelled", "another standing order on the same ticker filled first")
                log_fn(f"  (trigger {f['ticker']} {f['kind']} superseded at this check)")
                continue
            fmap[f["ticker"]] = f
        plan = {"sells": [{"ticker": t, "pct_of_position": f["pct_of_position"], "why": f["why"],
                           "evidence": f["evidence"], "signals": (f.get("signals") or []) + ["standing_order"]}
                          for t, f in fmap.items()]}
        exempt = {t for t, f in fmap.items() if f["kind"] in ("stop_loss", "trailing_stop")}
        sells, sdropped = apply_sell_guardrails(plan, positions, st, g, hold_exempt=exempt)
        for d in sdropped:
            log_fn(f"  (dropped {d})")
        for sl in sells:
            f = fmap[sl["ticker"]]
            rec = _at_price(broker, sl["ticker"], f["fill_price"], lambda: broker.sell_qty(sl["ticker"], sl["qty"]))
            if str(rec.get("status", "")).startswith("rejected"):
                log_fn(f"- SELL {sl['pct']:.0f}% {sl['ticker']} [{rec['status']}]"); continue
            full = {**rec, "date": str(today), "time_et": now.strftime("%H:%M"), "ts": int(f.get("fired_ts") or now.timestamp()),
                    "why": sl["why"], "signals": sl["signals"], "evidence": sl["evidence"], "trigger": f["kind"]}
            state.record_sell(st, sl["ticker"], full, float(rec.get("proceeds", 0) or 0)); state.save(st)
            learn.record_sell(full, signals=sorted(set(sl["signals"]) | set(learn.entry_signals(sl["ticker"]))), evidence=sl["evidence"], hour_et=now.hour)
            triggers.close(f["id"], now, "filled")
            if sl["ticker"] not in broker.positions():
                n = triggers.cancel_position_orders(sl["ticker"], now, "position closed")
                if n:
                    log_fn(f"  (cancelled {n} standing order(s) on {sl['ticker']}: position closed)")
            filled_sells.append(sl); did += 1
            extra = f" -> ${rec.get('proceeds', 0):.2f} ({rec.get('realized_pct', 0):+.2f}%)" if "proceeds" in rec else ""
            log_fn(f"- SELL {sl['pct']:.0f}% {sl['ticker']} [{f['kind']} @ ${f['fill_price']:.2f}]{extra} — {sl['why']}")

    buy_fires = [f for f in fires if f["kind"] in triggers.BUY_KINDS]
    if buy_fires and no_new_entries:
        for f in buy_fires:
            triggers.close(f["id"], now, "cancelled", "inside the last max_hold_minutes of the session")
            log_fn(f"  (cancelled standing buy {f['ticker']}: inside the last max_hold_minutes of the session)")
        buy_fires = []
    if buy_fires:
        fmap = {}
        for f in buy_fires:
            if f["ticker"] in fmap:
                triggers.close(f["id"], now, "cancelled", "another standing order on the same ticker filled first")
                continue
            fmap[f["ticker"]] = f
        # A standing order can sit for days. Whatever made the ticker acceptable when the order
        # was placed has to still be true now, or the screen is only a formality: it would let an
        # order placed before a token was rejected fill anyway.
        unvetted = {t for t in fmap if t not in allowed}
        if unvetted:
            verdicts = instruments.check(unvetted)
            for t in sorted(unvetted):
                v = verdicts.get(t) or {}
                if not v.get("ok"):
                    if v.get("transient"):
                        # A screen that could not be RUN is not a screen that FAILED. Leave the
                        # order working and try again next pass instead of destroying a $1,000
                        # entry because a data feed hiccuped.
                        log_fn(f"  (holding standing buy {t}: {v.get('why')} — will retry next check)")
                        fmap.pop(t, None); continue
                    triggers.close(fmap[t]["id"], now, "cancelled", "failed the screen at fill time")
                    log_fn(f"  (cancelled standing buy {t}: {v.get('why', 'failed the screen at fill time')})")
                    fmap.pop(t, None)
        if not fmap:
            return filled_buys, filled_sells, did
        usd_total = sum(f["usd"] for f in fmap.values())
        plan = {"deploy_now_usd": usd_total,
                "orders": [{"ticker": t, "usd": f["usd"], "why": f["why"], "evidence": f["evidence"],
                            "signals": (f.get("signals") or []) + ["standing_order"]} for t, f in fmap.items()]}
        orders, dropped, _ = apply_guardrails(plan, allowed | set(fmap), remaining, st, g, False, chase_check=False, sector_of=sector_of)
        for d in dropped:
            log_fn(f"  (dropped {d})")
        for o in orders:
            f = fmap[o["ticker"]]
            o["usd"] = min(o["usd"], float(f["usd"]))       # never more than the order rested for
            rec = _at_price(broker, o["ticker"], f["fill_price"], lambda: broker.buy_notional(o["ticker"], o["usd"]))
            if str(rec.get("status", "")).startswith("rejected"):
                log_fn(f"- BUY ${o['usd']:.2f} {o['ticker']} [{rec['status']}]"); continue
            full = {**rec, "date": str(today), "time_et": now.strftime("%H:%M"), "ts": int(f.get("fired_ts") or now.timestamp()),
                    "why": o["why"], "signals": o["signals"], "evidence": o["evidence"], "trigger": f["kind"]}
            state.record_order(st, o["ticker"], float(rec.get("notional", o["usd"])), full); state.save(st)
            learn.record(full, f["fill_price"], sector_of.get(o["ticker"], "off-watchlist"),
                         cpressure.get(o["ticker"], 0) > 0, px.get(o["ticker"], {}).get("change_1m_pct"),
                         signals=o["signals"], evidence=o["evidence"], hour_et=now.hour)
            triggers.close(f["id"], now, "filled")
            filled_buys.append({**o, "usd": float(rec.get("notional", o["usd"]))}); did += 1
            log_fn(f"- BUY ${float(rec.get('notional', o['usd'])):.2f} {o['ticker']} [{f['kind']} @ ${f['fill_price']:.2f}] — {o['why']}")
    return filled_buys, filled_sells, did


PUBLISH_EVERY_S = 900          # refresh the site at least this often even when nothing happens
BAR_S = 300                    # prices.intraday's bar length; the replay watermark lands on bar starts

def tick(force: bool = False, loops: int = 1, interval: int = 60) -> None:
    """Watch the market between decisions.

    GitHub's cron floor is five minutes, but an exit should not wait even that long, so one job
    does several passes spaced `interval` seconds apart and then exits before the next one starts.
    Only one of these ever runs at a time (the workflow shares the agent's concurrency group), so
    there is never a second writer touching the ledger.
    """
    for i in range(max(1, loops)):
        if i:
            clock.sleep(max(5, interval))
        try:
            _tick_once(force)
        except Exception as e:
            log(f"tick error: {redact(e)}")

def _tick_once(force: bool = False) -> None:
    """One pass: quotes, fire anything that reached its level, publish if it matters."""
    cfg = config.load_config()
    env, g = cfg["env"], cfg["guardrails"]
    g["_weekly_budget"] = float(cfg["weekly_budget"])
    # The smallest sensible order scales with the account, so it never drifts out of step again.
    pct = float(g.get("min_order_pct_of_budget", 0) or 0)
    if pct > 0:
        g["min_order_usd"] = max(float(g.get("min_order_usd", 0) or 0), round(g["_weekly_budget"] * pct / 100, 2))
    broker = make_broker(cfg)
    now = datetime.now(ET)
    today = now.date()
    if not force:
        if not is_trading_day(today):
            return
        is_open = broker.market_open() if (getattr(broker, "client", None) or getattr(broker, "name", "") == "sim") else market_open_fallback(now)
        if not is_open:
            return
    live = [o for o in triggers.all_orders() if o.get("status") == "working"]
    held = broker.held_tickers() if hasattr(broker, "held_tickers") else []
    st = state.load()
    if not live and not held:
        # Nothing to fire and nothing to protect - but a flat book is not a reason to let the site
        # go stale and start warning the owner that the agent is down. Refresh on the ordinary
        # freshness timer and stop there.
        if (int(now.timestamp()) - int(st.get("last_publish_ts", 0) or 0)) > PUBLISH_EVERY_S:
            st["last_publish_ts"] = int(now.timestamp())
            st["last_check_ts"] = int(now.timestamp())
            state.save(st)
            pub.publish(cfg, None, "tick: flat, nothing working", working_orders=[])
        return
    px = prices.snapshot(sorted({o["ticker"] for o in live} | set(held)))
    px, _ = safety.sane_prices(px, g.get("max_daily_move_pct", 0))
    if hasattr(broker, "set_prices"): broker.set_prices(px)
    may_trade, problems = safety.preflight(broker, g)
    if not may_trade:
        for m in problems: log(f"  ! {m}")
        pub.publish(cfg, None, "safety hold", working_orders=triggers.summary(px, now)); return
    remaining = round(g["_weekly_budget"] - st["spent"], 2)
    if getattr(broker, "name", "") == "sim":
        remaining = round(min(remaining, broker.cash()), 2)
    sector_of = {t: s for s, ts in cfg["watchlist"].items() for t in ts}
    # The watchlist is the vetted set. Passing an empty set here re-screened every hand-picked name
    # at fill time, cached a transient lookup failure forever, and cancelled the order on it.
    cutoff = past_entry_cutoff(now, g)
    if cutoff:
        n = triggers.cancel_all_buys(now, "inside the last max_hold_minutes of the session")
        if n:
            log(f"  (cancelled {n} resting buy order(s): inside the last max_hold_minutes of the session)")
    bought, sold, did = fill_standing_orders(now, today, broker, broker.positions(), px, st, g,
                                             set(sector_of), remaining, sector_of, {}, log, no_new_entries=cutoff)
    # The clock has to be enforced on EVERY pass, not only when the brain is asked. Checked only
    # on decisions, a "30-minute" hold actually ran 30-64 minutes depending on when the next
    # decision happened to land.
    stale_sells, stale_n = time_stops(now, broker, broker.positions(), st, g, log)
    if stale_n:
        sold += stale_sells; did += stale_n
    # Nothing is carried past the bell: whatever is still open in the final minutes is closed.
    if at_session_end(now):
        flat_sells, flat_n = session_end_flatten(now, broker, broker.positions(), st, g, log)
        if flat_n:
            sold += flat_sells; did += flat_n

    # Every pass, not only after a buy: this is what makes the ratchet a ratchet. The stop climbs
    # behind a winning price minute by minute, so a trade that peaks and turns is sold near its
    # high instead of riding the clock down.
    if broker.positions():
        auto, _ = triggers.rebalance_brackets(now, broker.positions(), px, _bracket_cfg(g))
        if auto:
            triggers.place(auto, now, set(broker.positions()), set(broker.positions()), px)
    st["last_check_ts"] = int(now.timestamp())
    st["last_bar_ts"] = (int(now.timestamp()) // BAR_S) * BAR_S     # start of the bar still forming
    state.save(st)
    if did:
        log(f"## {today} {now.strftime('%H:%M')} ET — tick — {len(sold)} sell(s), {len(bought)} buy(s) from standing orders")
        if hasattr(broker, "write_report"): broker.write_report()
    # Every publish is a commit and every commit is a site deploy, so only publish when there is
    # something new to see: a fill, a change in the working book, or a periodic freshness refresh.
    book = triggers.summary(px, now)
    # Publish when the BOOK changes, not when a ratcheting stop creeps a cent. Orders appearing or
    # disappearing is news; a level drifting 0.1% is not, and at one publish per Vercel deploy a
    # per-tick re-pin would exhaust the daily quota by lunchtime. Anything smaller is still
    # committed and reaches the site on the 15-minute freshness publish.
    now_px = {o["id"]: float(o.get("price") or 0) for o in book}
    prev_px = st.get("book_px") or {}
    moved = set(now_px) != set(prev_px) or any(
        abs(v - float(prev_px.get(k) or 0)) > max(0.01, v * 0.003) for k, v in now_px.items())
    stale = (int(now.timestamp()) - int(st.get("last_publish_ts", 0) or 0)) > PUBLISH_EVERY_S
    if did or moved or stale:
        st["book_px"] = now_px
        st["last_publish_ts"] = int(now.timestamp())
        state.save(st)
        pub.publish(cfg, None, f"tick: {did} standing order(s) filled" if did else "tick: watching",
                    working_orders=book)

def main(report_only: bool = False, force: bool = False) -> None:
    cfg = config.load_config()
    env, g = cfg["env"], cfg["guardrails"]
    g["_weekly_budget"] = float(cfg["weekly_budget"])
    # The smallest sensible order scales with the account, so it never drifts out of step again.
    pct = float(g.get("min_order_pct_of_budget", 0) or 0)
    if pct > 0:
        g["min_order_usd"] = max(float(g.get("min_order_usd", 0) or 0), round(g["_weekly_budget"] * pct / 100, 2))
    every_min = int(cfg.get("run_every_minutes", 30))
    broker = make_broker(cfg)
    is_sim = getattr(broker, "name", "") == "sim"
    st = state.load()
    now = datetime.now(ET)
    today = now.date()
    if is_sim:
        mode = "SIM (pretend money)"
    else:
        mode = "DRY RUN" if env["dry_run"] else ("PAPER" if (env["alpaca_paper"] if env["broker"] == "alpaca" else env["ibkr_paper"]) else "LIVE")

    held = broker.held_tickers() if hasattr(broker, "held_tickers") else []
    if report_only:
        px = prices.snapshot(sorted(set(learn.journal_tickers()) | set(held)))
        if hasattr(broker, "set_prices"): broker.set_prices(px)
        positions = broker.positions()
        log(f"\n## {today} {now.strftime('%H:%M')} ET — REPORT — {mode} via {env['broker']}")
        if is_sim:
            broker.write_report(); log(f"portfolio: {broker.summary()}")
        log(f"positions: {positions}\ncash: {broker.cash()}\ntrack record: {learn.score(px, set(broker.positions())) if px else 'no trades yet'}")
        return

    remaining = round(g["_weekly_budget"] - st["spent"], 2)
    if is_sim:
        remaining = round(min(remaining, broker.cash()), 2)
    log(f"\n## {today} {now.strftime('%H:%M')} ET ({today.strftime('%A')}) — week {st['week']} — budget left ${remaining:.2f} (today ${st.get('deployed_today', 0.0):.2f} put to work, {st['orders_today']} buys, {st['sells_today']} sells) — {mode} via {env['broker']}")

    if not force:
        if not is_trading_day(today):
            log("Market closed today (weekend or holiday). Nothing to do."); pub.publish(cfg, None, "market closed"); return
        is_open = broker.market_open() if (getattr(broker, "client", None) or is_sim) else market_open_fallback(now)
        if not is_open:
            log("Market closed right now. Nothing to do."); pub.publish(cfg, None, "market closed"); return
    may_trade, problems = safety.preflight(broker, g)
    if not may_trade:
        for m in problems: log(f"  ! {m}")
        log("Safety check failed. No decision made."); pub.publish(cfg, None, "safety hold"); return
    if not env["anthropic_key"]:
        log("Waiting for ANTHROPIC_API_KEY in .env — double-click setup.command and paste it. No decision made."); return

    # --- signals: decide the allowed universe FIRST, then price everything in it ---
    sig = gather_signals(cfg, env, g, held)
    for n in (sig.get("instrument_notes") or [])[:6]:
        log(f"  ({n})")
    watch, followed_people, allowed = sig["watch"], sig["followed_people"], set(sig["allowed"])
    ctrades, cpressure, itrades, ipressure = sig["ctrades"], sig["cpressure"], sig["itrades"], sig["ipressure"]
    px = prices.snapshot(sorted(allowed | set(learn.journal_tickers()) | set(held)))
    px, bad_ticks = safety.sane_prices(px, g.get("max_daily_move_pct", 0))
    for b in bad_ticks: log(f"  (bad quote {b})")
    unpriced = sorted(t for t in allowed if t not in px)
    if unpriced:
        log(f"  (no price for {', '.join(unpriced[:10])}{'…' if len(unpriced) > 10 else ''} — excluded this check)")
        allowed -= set(unpriced)
    if hasattr(broker, "set_prices"): broker.set_prices(px)
    positions = broker.positions()
    sector_of = {t: s for s, ts in cfg["watchlist"].items() for t in ts}

    # --- standing orders fill FIRST, at their own price, wherever in the last half hour the market
    #     reached them. The brain then decides against the resulting portfolio. ---
    cutoff = past_entry_cutoff(now, g)
    if cutoff:
        n = triggers.cancel_all_buys(now, "inside the last max_hold_minutes of the session")
        if n:
            log(f"  (cancelled {n} resting buy order(s): inside the last max_hold_minutes of the session)")
    tbuys, tsells, tdid = fill_standing_orders(now, today, broker, positions, px, st, g,
                                               allowed, remaining, sector_of, cpressure, log, no_new_entries=cutoff)
    stale_sells, stale_n = time_stops(now, broker, broker.positions(), st, g, log)
    tsells += stale_sells; tdid += stale_n
    if tdid:
        positions = broker.positions()
        remaining = round(g["_weekly_budget"] - st["spent"], 2)
        if is_sim:
            remaining = round(min(remaining, broker.cash()), 2)
    # Entry screening does not expire, so a name bought before a rule existed can sit in the book
    # forever. Re-check what is held and put it in front of the brain rather than quietly holding.
    flagged = {}
    off_watch = {t for t in positions if t not in set(watch)}
    if off_watch:
        for t, v in instruments.check(off_watch).items():
            if not v.get("ok"):
                flagged[t] = v.get("why", "no longer passes the screen")
                log(f"  (holding {t} would not be bought today: {v.get('why')})")
    track = learn.score(px, set(broker.positions()))
    headlines = news.ticker_headlines(sorted(allowed | set(held)), per=int(g.get("news_headlines_per_ticker", 3)))
    people = news.people_news(followed_people, per=4)

    cf = reflect.report(px)                       # graded once here, then reused after the decision
    checks_left = checks_left_today(now, every_min)
    cleanup = is_cleanup_check(now, g, every_min)
    nothing_to_buy = remaining < g["min_order_usd"] or cutoff
    if cutoff:
        log("  (inside the last max_hold_minutes of the session: no new entries at this check)")
    ctx = {
        "datetime_et": now.strftime("%Y-%m-%d %H:%M"), "weekday": today.strftime("%A"),
        "market_close_et": close_time(today).strftime("%H:%M"), "last_trading_day_of_week": last_trading_day_of_week(today),
        "friday_cleanup": cleanup and not nothing_to_buy, "checks_left_today": checks_left, "run_every_minutes": every_min,
        "full_deployment": _full_deployment(today, g),
        "positions_held": len(positions), "min_positions": int(g.get("min_positions", 0) or 0),
        "below_target_position_count": len(positions) < int(g.get("min_positions", 0) or 0),
        # How much of the account is doing nothing. Reported because "I hold min_positions names"
        # was being treated as a finished job while two thirds of the money sat in cash.
        "cash_idle_pct": round(100 * remaining / g["_weekly_budget"], 1) if g.get("_weekly_budget") else None,
        "invested_usd": round(sum(float(v.get("qty", 0)) * float(v.get("avg_cost", 0)) for v in (positions or {}).values()), 2),
        "portfolio": broker.summary() if is_sim else {"cash": broker.cash()},
        "current_positions": positions,
        "holdings_that_would_not_be_bought_today": flagged,
        "weekly_budget_usd": g["_weekly_budget"], "remaining_budget_usd": remaining,
        "spent_today_usd": st.get("deployed_today", 0.0), "orders_today": st["orders_today"], "sells_today": st["sells_today"],
        "bought_this_week": st.get("deployed_by_ticker") or st["by_ticker"], "sold_today": st["sold_today"],
        "cooling_off_minutes_left": {t: int(round(int(g.get("rebuy_cooldown_minutes", 0) or 0) - (now.timestamp() - float(ts or 0)) / 60))
                                     for t, ts in (st.get("sold_ts") or {}).items()
                                     if int(g.get("rebuy_cooldown_minutes", 0) or 0) and (now.timestamp() - float(ts or 0)) / 60 < int(g.get("rebuy_cooldown_minutes", 0) or 0)},
        "no_new_entries_this_check": cutoff,
        "guardrails": {k: v for k, v in g.items() if not k.startswith("_")},
        "sell_rules": {"allowed": not g.get("only_buy", False), "min_hold_days": g.get("min_hold_days", 0), "max_sells_per_day": g.get("max_sells_per_day", 3)},
        "allowed_tickers": sorted(allowed), "watchlist": cfg["watchlist"], "prices": px,
        "headlines_by_ticker": headlines, "followed_people": followed_people, "followed_people_news": people,
        "congress_recent_trades": ctrades[:40], "congress_net_buy_pressure": dict(list(cpressure.items())[:15]),
        "insider_recent_trades": itrades[:40], "insider_net_buy_pressure": dict(list(ipressure.items())[:15]),
        "who_disclosed_it": {t: politicians.who_bought(ctrades, t) for t in list(cpressure)[:8]},
        "disclosure_leaderboard": (sig.get("board") or {}).get("leaders", [])[:8],
        "disclosure_leaderboard_caveat": (sig.get("board") or {}).get("caveat", ""),
        "followed_people_insider_filings": insiders.by_followed(itrades, followed_people)[:20],
        "track_record": track, "past_lessons": learn.past_lessons(evidence_days=cf.get("independent_days_graded") or 0),
        "backtest_priors": backtest.priors(),
        "signal_evidence_5d": replay.evidence("5d"),
        "signal_evidence_21d": replay.evidence("21d"),
        "counterfactual_learning": cf,
        "working_orders": triggers.summary(px, now),
        "orders_dropped_at_last_check": reflect.last_dropped(),
        "standing_order_kinds": sorted(triggers.KINDS),
        "past_lessons_with_outcome": {"rows": reflect.recent_lessons_with_outcome(px),
                                      "status": learn.past_lessons(evidence_days=cf.get("independent_days_graded") or 0)["status"]},
    }
    # The model is the decision-maker. When it cannot be reached - out of credits, rate limited,
    # or down - the agent used to stop trading entirely and sit flat, which costs a day of graded
    # trades permanently: the counterfactual loop only learns from days it actually traded. The
    # rule-based fallback is strictly worse at picking (it cannot read a headline) but it keeps the
    # machine running on the signals that were already measured.
    autopiloted = False
    try:
        plan = brain.decide(env, ctx)
    except Exception as e:
        msg = redact(e)
        if not bool(g.get("autopilot_when_model_unavailable", True)):
            log(f"brain error: {msg} — no decision at this check.")
            pub.publish(cfg, site_signals(sig, headlines, people, reflect.report(px)), "brain error",
                        working_orders=triggers.summary(px, now)); return
        log(f"brain unavailable: {msg}")
        log("  -> falling back to autopilot: rules only, no model call")
        plan = autopilot.plan(ctx, g)
        autopiloted = True
    log(f"{'autopilot' if autopiloted else 'brain'}: {plan.get('reasoning', '')}")
    if not autopiloted:      # a rule has no lesson to teach; only the model writes one
        learn.add_lesson(plan.get("lesson", ""), track, evidence_days=cf.get("independent_days_graded") or 0)
    if plan.get("lesson"): log(f"lesson: {plan['lesson']}")
    did = tdid

    # --- sells first (frees cash); state saved after every fill so counters never lag the ledger ---
    sells, sdropped = apply_sell_guardrails(plan, positions, st, g) if hasattr(broker, "sell_qty") else ([], ["broker has no sell support"] if plan.get("sells") else [])
    for d in sdropped: log(f"  (dropped {d})")
    filled_sells, filled_buys = [], []
    for s in sells:
        rec = broker.sell_qty(s["ticker"], s["qty"])
        if str(rec.get("status", "")).startswith("rejected"):
            log(f"- SELL {s['pct']:.0f}% {s['ticker']} [{rec['status']}]"); continue
        full = {**rec, "date": str(today), "time_et": now.strftime("%H:%M"), "ts": int(now.timestamp()), "why": s["why"], "signals": s["signals"], "evidence": s["evidence"]}
        state.record_sell(st, s["ticker"], full, float(rec.get("proceeds", 0) or 0)); state.save(st)
        learn.record_sell(full, signals=sorted(set(s["signals"]) | set(learn.entry_signals(s["ticker"]))), evidence=s["evidence"], hour_et=now.hour)
        if s["ticker"] not in broker.positions():
            # Standing-order sells already did this; a sell the brain decided on did not, so the
            # position's averaging-in order stayed live and could re-open what was just closed.
            n = triggers.cancel_position_orders(s["ticker"], now, "position closed")
            if n:
                log(f"  (cancelled {n} order(s) on {s['ticker']}: position closed)")
        filled_sells.append(s)
        extra = f" → ${rec.get('proceeds', 0):.2f} ({rec.get('realized_pct', 0):+.2f}%)" if "proceeds" in rec else ""
        log(f"- SELL {s['pct']:.0f}% {s['ticker']} [{rec['status']}]{extra} {s['signals']} — {s['why']} | evidence: {s['evidence']}")
        did += 1
    if is_sim and sells:
        remaining = round(min(g["_weekly_budget"] - st["spent"], broker.cash()), 2)

    # --- buys ---
    orders, dropped, deferred = ([], [], []) if nothing_to_buy else apply_guardrails(plan, allowed, remaining, st, g, cleanup, px, sector_of=sector_of)
    for d in dropped: log(f"  (dropped {d})")
    for o in orders:
        rec = broker.buy_notional(o["ticker"], o["usd"])
        if str(rec.get("status", "")).startswith("rejected"):
            log(f"- BUY ${o['usd']:.2f} {o['ticker']} [{rec['status']}]"); continue
        full = {**rec, "date": str(today), "time_et": now.strftime("%H:%M"), "ts": int(now.timestamp()), "why": o["why"], "signals": o["signals"], "evidence": o["evidence"]}
        state.record_order(st, o["ticker"], float(rec.get("notional", o["usd"])), full); state.save(st)
        learn.record(full, px.get(o["ticker"], {}).get("price"), sector_of.get(o["ticker"], "off-watchlist"),
                     cpressure.get(o["ticker"], 0) > 0, px.get(o["ticker"], {}).get("change_1m_pct"),
                     signals=o["signals"], evidence=o["evidence"], hour_et=now.hour)
        filled_buys.append({**o, "usd": float(rec.get("notional", o["usd"]))})
        log(f"- BUY ${float(rec.get('notional', o['usd'])):.2f} {o['ticker']} [{rec['status']}] {o['signals']} — {o['why']} | evidence: {o['evidence']}")
        did += 1

    # anything that was too high in the range to buy at market rests as a limit lower down
    want = list(plan.get("triggers") or [])
    if int(g.get("max_hold_minutes", 0) or 0) > 0:
        # Under an intraday clock a buy order never outlives the session, whether the model left
        # good_until blank (which defaulted to a 5-day life spanning the weekend) or set a later date.
        for t in want:
            if str(t.get("kind", "")).lower() in triggers.BUY_KINDS:
                t["good_until"] = min(str(t.get("good_until") or "9999-12-31")[:10], now.date().isoformat())
        if cutoff:
            want = [t for t in want if str(t.get("kind", "")).lower() not in triggers.BUY_KINDS]
    for d in deferred:
        want.append({"ticker": d["ticker"], "kind": "buy_limit", "price": d["limit_price"], "usd": d["usd"],
                     # Alive through this session, gone tomorrow. Left blank it defaulted to a
                     # multi-day life and filled sessions later on a stale idea: measured
                     # -0.150%/signal against -0.024% for same-session.
                     "pct_of_position": 0, "trail_pct": 0, "good_until": now.date().isoformat(),
                     "signals": (d.get("signals") or []) + ["patience"],
                     "evidence": d.get("evidence") or f"was {d['was_at_pct']:.0f}% up the day's range",
                     "why": f"wanted it, but not at the high — resting at ${d['limit_price']:.2f}. {d.get('why','')}"[:240]})
    placed, trejected = triggers.place(want, now, set(broker.positions()), allowed, px)
    auto, stale = triggers.rebalance_brackets(now, broker.positions(), px, _bracket_cfg(g))
    # Rest dip orders on names it does NOT hold, so a dip can be an entry and not just an average-down.
    _cool = int(g.get("rebuy_cooldown_minutes", 0) or 0)
    _cooling = {t for t, ts in (st.get("sold_ts") or {}).items()
                if _cool and (now.timestamp() - float(ts or 0)) / 60 < _cool}
    auto += [] if cutoff else triggers.dip_hunt(now, set(broker.positions()), allowed, px,
                              {**(g.get("dip_hunt") or {}),
                               "_max_hold_minutes": float(g.get("max_hold_minutes", 0) or 0),
                               "_min_order_usd": float(g.get("min_order_usd", 0) or 0),
                               "_budget_full": float(g["_weekly_budget"]),
                               "_cash_cap": remaining,
                               "_skip": sorted(_cooling)},    # no live order to re-enter a name it may not re-enter
                              float(g["_weekly_budget"]))
    if stale:
        log(f"  (re-pinned {stale} order(s) to the new average cost)")
    if auto:
        a_placed, a_rej = triggers.place(auto, now, set(broker.positions()), allowed | set(broker.positions()), px)
        placed += a_placed
        trejected += a_rej
    for d in trejected:
        log(f"  (dropped {d})")
    for t in placed:
        detail = f"trail {t['trail_pct']}%" if t["kind"] == "trailing_stop" else f"${t['price']:.2f}"
        size = f"${t['usd']:.2f}" if t["kind"] in triggers.BUY_KINDS else f"{t['pct_of_position']:.0f}%"
        log(f"~ WORKING {t['kind']} {size} {t['ticker']} @ {detail} until {t['good_until']} — {t['why']}")
    st["last_check_ts"] = int(now.timestamp())
    st["last_bar_ts"] = (int(now.timestamp()) // BAR_S) * BAR_S
    st["last_decision_ts"] = int(now.timestamp())
    # The brain already says how soon it wants to be asked again; that request was being thrown
    # away and every decision waited a flat 30 minutes, so a new idea could sit unbought for half
    # an hour while the market moved. It is honoured now, inside a floor and a ceiling.
    st["next_check_minutes"] = plan.get("next_check_minutes")
    state.save(st)
    filled_buys = tbuys + filled_buys
    filled_sells = tsells + filled_sells
    reflect.record(now, px, allowed, filled_buys, filled_sells, dropped + sdropped, plan,
                   cpressure, ipressure, headlines, sector_of, set(positions), remaining)
    if is_sim:
        broker.write_report()
        s = broker.summary()
        log(f"portfolio: equity ${s['equity']:.2f} ({s['total_return_pct']:+.2f}% on ${s['deposited']:.2f} in) · cash ${s['cash']:.2f} · realised {s['realized_pnl']:+.2f}")
    book = triggers.summary(px, now)
    if did == 0:
        log(f"Decision: nothing at this check.{f' {len(book)} standing order(s) working.' if book else ''}")
    else:
        log(f"Done: {len(filled_sells)} sell(s), {len(filled_buys)} buy(s)"
            f"{f' (incl. {tdid} from standing orders)' if tdid else ''}; "
            f"{len(book)} order(s) working; budget left ${g['_weekly_budget'] - st['spent']:.2f} this week")
    pub.publish(cfg, site_signals(sig, headlines, people, reflect.report(px)), plan.get("reasoning", "")[:300],
                working_orders=book, next_check_minutes=plan.get("next_check_minutes"),
                reasoning=plan.get("reasoning", "")[:300])

if __name__ == "__main__":
    if "--if-due" in sys.argv:
        # Run a full decision only if one is overdue. This lets the tick workflow do both jobs in
        # one job, which is what finally removed the concurrency-lane fight: a queued tick kept
        # cancelling a pending decision, because a lane holds only one waiting run.
        mins = int(sys.argv[sys.argv.index("--if-due") + 1])
        _now = datetime.now(ET)
        _cfg = config.load_config()
        _g = _cfg["guardrails"]
        _floor = int(_g.get("min_decision_minutes", 6) or 6)
        _ceil = int(_g.get("max_decision_minutes", 30) or 30)
        if not market_open_fallback(_now) and "--force" not in sys.argv:
            # Overnight, a decision would only log "market closed" and publish - and every publish
            # is a site deploy. That was ~77 wasted deploys a day against a 100/day limit.
            print("market closed; no decision, nothing published"); sys.exit(0)
        if _now.time() < time(9, 32) and "--force" not in sys.argv:
            # In the first minute the daily quote can still be yesterday's row; two minutes costs nothing.
            print("first minute of the session; waiting for a real quote"); sys.exit(0)
        _st = state.load()
        _want = _st.get("next_check_minutes")
        _due = max(_floor, min(_ceil, int(_want))) if _want else mins
        _age = (_now.timestamp() - float(_st.get("last_decision_ts", 0) or 0)) / 60
        if _age < _due:
            print(f"decision was {_age:.0f} min ago; not due yet (the brain asked for {_due})")
        else:
            print(f"decision due: last one {_age:.0f} min ago (wanted every {_due})")
            main(force="--force" in sys.argv)
    elif "--tick" in sys.argv:
        def _arg(name, default):
            return int(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default
        tick(force="--force" in sys.argv, loops=_arg("--loop", 1), interval=_arg("--interval", 60))
    elif "--publish" in sys.argv:
        publish_only()
    else:
        main(report_only="--report" in sys.argv, force="--force" in sys.argv)
