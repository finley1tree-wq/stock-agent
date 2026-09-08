"""Entry point. Designed to run repeatedly through the trading day (about every 30 minutes
while the US market is open - see .github/workflows/agent.yml or autopilot-mac.command).
Each run is one "check".

    python -m agent.run            # one check: gather signals, ask the brain, maybe buy/sell, log
    python -m agent.run --report   # print portfolio + budget + track record, decide nothing
    python -m agent.run --force    # skip the weekend / market-open checks (testing; sim still fills at last price)

Brokers (BROKER in .env): sim (default, pretend money, real prices), alpaca (paper or live), ibkr.
"""
import sys
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from . import config, prices, politicians, insiders, news, state, brain, learn, publish as pub, safety, backtest, reflect, triggers, instruments
from .redact import redact
from .broker_sim import is_trading_day, close_time, last_trading_day_of_week

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "log.md"
ET = ZoneInfo("America/New_York")
MARKET_OPEN = time(9, 30)
SIGNALS = {"congress", "insider", "followed_person", "news", "momentum", "track_record", "etf_default", "risk_management"}

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
    today = now.date()
    if not last_trading_day_of_week(today):
        return False
    close_dt = datetime.combine(today, close_time(today), ET)
    configured = datetime.combine(today, _parse_hm(g.get("friday_cleanup_after_et", "15:30"), time(15, 30)), ET)
    after = min(configured, close_dt - timedelta(minutes=2 * every_min))   # at least the last two open slots
    return now >= after or checks_left_today(now, every_min) <= 1

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

def apply_guardrails(plan: dict, allowed: set[str], remaining_week: float, st: dict, g: dict, cleanup: bool) -> tuple[list[dict], list[str]]:
    """Buys. Returns (orders, dropped_reasons).
    Caps enforced inside one check as well as across the day/week: per-ticker/week (running), per-day (running),
    per-day order count, min order, evidence required, no same-day rebuy, no negative or duplicate tickers."""
    budget_week = g["_weekly_budget"]
    dropped: list[str] = []
    day_cap = max(0.0, budget_week * g["max_daily_deploy_pct"] / 100 - st.get("spent_today", 0.0))
    cap_now = remaining_week if cleanup else min(remaining_week, day_cap)
    deploy = min(max(0.0, float(plan.get("deploy_now_usd", plan.get("deploy_today_usd", 0)) or 0)), cap_now)
    if cleanup:
        deploy = remaining_week
    orders_left = int(g.get("max_orders_per_day", 8)) - int(st.get("orders_today", 0))
    if orders_left <= 0 and not cleanup:
        return [], ["max_orders_per_day reached"]
    merged: dict[str, dict] = {}
    for o in plan.get("orders", []) or []:
        if not isinstance(o, dict):
            continue
        t = str(o.get("ticker", "")).upper()
        if t not in allowed:
            dropped.append(f"{t}: not in allowed list"); continue
        if t in st.get("sold_today", []):
            dropped.append(f"{t}: sold today, no same-day rebuy"); continue
        if not str(o.get("evidence", "")).strip():
            dropped.append(f"{t}: no evidence given"); continue
        usd = max(0.0, float(o.get("usd", 0) or 0))          # never negative
        if t in merged:                                       # repeated ticker -> one order
            merged[t]["usd"] += usd; continue
        merged[t] = {**o, "ticker": t, "usd": usd}
    orders = [o for o in merged.values() if o["usd"] > 0]
    total = sum(o["usd"] for o in orders) or 1.0
    per_cap = budget_week * g["max_per_ticker_pct"] / 100
    by_ticker = dict(st.get("by_ticker", {}))
    left = deploy
    out = []
    for o in orders[:max(orders_left, 1) if cleanup else min(4, orders_left)]:
        room = per_cap - by_ticker.get(o["ticker"], 0.0)
        usd = min(deploy * o["usd"] / total, room, left)
        if usd < g["min_order_usd"]:
            dropped.append(f"{o['ticker']}: below min order after caps (${usd:.2f})"); continue
        usd = round(usd, 2)
        by_ticker[o["ticker"]] = by_ticker.get(o["ticker"], 0.0) + usd
        left -= usd
        out.append({"ticker": o["ticker"], "usd": usd, "why": str(o.get("why", "")), "signals": _clean_signals(o), "evidence": str(o.get("evidence", ""))[:200]})
    return out, dropped

def apply_sell_guardrails(plan: dict, positions: dict, st: dict, g: dict, hold_exempt: set | None = None) -> tuple[list[dict], list[str]]:
    """Sells. Must hold it, must be old enough, must have evidence, daily count cap, one sell per ticker per check."""
    dropped: list[str] = []
    if g.get("only_buy", False):
        return [], (["selling disabled (only_buy)"] if plan.get("sells") else [])
    left = int(g.get("max_sells_per_day", 3)) - int(st.get("sells_today", 0))
    out, seen = [], set()
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
        if len(out) >= max(left, 0):
            dropped.append(f"sell {t}: max_sells_per_day reached"); continue
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
    cpressure = politicians.buy_pressure(ctrades, cfg.get("followed_politicians") or [])
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
    allowed, rejected = instruments.filter_allowed(allowed, watch)
    feed_status["excluded_instruments"] = rejected[:12]
    return {"watch": watch, "followed_people": followed_people, "ctrades": ctrades, "cpressure": cpressure,
            "itrades": itrades, "ipressure": ipressure, "allowed": allowed, "feed_status": feed_status,
            "instrument_notes": rejected}

def site_signals(sig: dict, headlines: dict, people: dict, learning: dict | None = None) -> dict:
    return {"allowed": sorted(sig["allowed"]), "feed_status": sig["feed_status"], "learning": learning or {},
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

def fill_standing_orders(now, today, broker, positions, px, st, g, allowed, remaining, sector_of, cpressure, log_fn):
    """Fire any standing order whose level the market reached since the last check.

    Runs BEFORE the brain, so the brain sees the resulting portfolio. Every fill still goes through
    the ordinary guardrails and the ordinary ledger; the only difference is the fill price and the
    fact that the decision was made at an earlier check.
    """
    live = [o for o in triggers.all_orders() if o.get("status") == "working"]
    if not live:
        return [], [], 0
    bars = prices.intraday(sorted({o["ticker"] for o in live}), since_ts=int(st.get("last_check_ts", 0) or 0))
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
            learn.record_sell(full, signals=sl["signals"], evidence=sl["evidence"], hour_et=now.hour)
            triggers.close(f["id"], now, "filled")
            if sl["ticker"] not in broker.positions():
                n = triggers.cancel_all_for(sl["ticker"], triggers.SELL_KINDS, now, "position closed")
                if n:
                    log_fn(f"  (cancelled {n} standing order(s) on {sl['ticker']}: position closed)")
            filled_sells.append(sl); did += 1
            extra = f" -> ${rec.get('proceeds', 0):.2f} ({rec.get('realized_pct', 0):+.2f}%)" if "proceeds" in rec else ""
            log_fn(f"- SELL {sl['pct']:.0f}% {sl['ticker']} [{f['kind']} @ ${f['fill_price']:.2f}]{extra} — {sl['why']}")

    buy_fires = [f for f in fires if f["kind"] in triggers.BUY_KINDS]
    if buy_fires:
        fmap = {}
        for f in buy_fires:
            if f["ticker"] in fmap:
                triggers.close(f["id"], now, "cancelled", "another standing order on the same ticker filled first")
                continue
            fmap[f["ticker"]] = f
        usd_total = sum(f["usd"] for f in fmap.values())
        plan = {"deploy_now_usd": usd_total,
                "orders": [{"ticker": t, "usd": f["usd"], "why": f["why"], "evidence": f["evidence"],
                            "signals": (f.get("signals") or []) + ["standing_order"]} for t, f in fmap.items()]}
        orders, dropped = apply_guardrails(plan, allowed | set(fmap), remaining, st, g, False)
        for d in dropped:
            log_fn(f"  (dropped {d})")
        for o in orders:
            f = fmap[o["ticker"]]
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


def main(report_only: bool = False, force: bool = False) -> None:
    cfg = config.load_config()
    env, g = cfg["env"], cfg["guardrails"]
    g["_weekly_budget"] = float(cfg["weekly_budget"])
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
        log(f"positions: {positions}\ncash: {broker.cash()}\ntrack record: {learn.score(px) if px else 'no trades yet'}")
        return

    remaining = round(g["_weekly_budget"] - st["spent"], 2)
    if is_sim:
        remaining = round(min(remaining, broker.cash()), 2)
    log(f"\n## {today} {now.strftime('%H:%M')} ET ({today.strftime('%A')}) — week {st['week']} — budget left ${remaining:.2f} (today ${st['spent_today']:.2f}, {st['orders_today']} buys, {st['sells_today']} sells) — {mode} via {env['broker']}")

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
    tbuys, tsells, tdid = fill_standing_orders(now, today, broker, positions, px, st, g,
                                               allowed, remaining, sector_of, cpressure, log)
    if tdid:
        positions = broker.positions()
        remaining = round(g["_weekly_budget"] - st["spent"], 2)
        if is_sim:
            remaining = round(min(remaining, broker.cash()), 2)
    track = learn.score(px)
    headlines = news.ticker_headlines(sorted(allowed | set(held)), per=int(g.get("news_headlines_per_ticker", 3)))
    people = news.people_news(followed_people, per=4)

    checks_left = checks_left_today(now, every_min)
    cleanup = is_cleanup_check(now, g, every_min)
    nothing_to_buy = remaining < g["min_order_usd"]
    ctx = {
        "datetime_et": now.strftime("%Y-%m-%d %H:%M"), "weekday": today.strftime("%A"),
        "market_close_et": close_time(today).strftime("%H:%M"), "last_trading_day_of_week": last_trading_day_of_week(today),
        "friday_cleanup": cleanup and not nothing_to_buy, "checks_left_today": checks_left, "run_every_minutes": every_min,
        "portfolio": broker.summary() if is_sim else {"cash": broker.cash()},
        "current_positions": positions,
        "weekly_budget_usd": g["_weekly_budget"], "remaining_budget_usd": remaining,
        "spent_today_usd": st["spent_today"], "orders_today": st["orders_today"], "sells_today": st["sells_today"],
        "bought_this_week": st["by_ticker"], "sold_today": st["sold_today"],
        "guardrails": {k: v for k, v in g.items() if not k.startswith("_")},
        "sell_rules": {"allowed": not g.get("only_buy", False), "min_hold_days": g.get("min_hold_days", 0), "max_sells_per_day": g.get("max_sells_per_day", 3)},
        "allowed_tickers": sorted(allowed), "watchlist": cfg["watchlist"], "prices": px,
        "headlines_by_ticker": headlines, "followed_people": followed_people, "followed_people_news": people,
        "congress_recent_trades": ctrades[:40], "congress_net_buy_pressure": dict(list(cpressure.items())[:15]),
        "insider_recent_trades": itrades[:40], "insider_net_buy_pressure": dict(list(ipressure.items())[:15]),
        "followed_people_insider_filings": insiders.by_followed(itrades, followed_people)[:20],
        "track_record": track, "past_lessons": learn.past_lessons(),
        "backtest_priors": backtest.priors(),
        "counterfactual_learning": reflect.report(px),
        "working_orders": triggers.summary(px, now),
        "standing_order_kinds": sorted(triggers.KINDS),
        "past_lessons_with_outcome": reflect.recent_lessons_with_outcome(px),
    }
    try:
        plan = brain.decide(env, ctx)
    except Exception as e:
        log(f"brain error: {redact(e)} — no decision at this check."); pub.publish(cfg, site_signals(sig, headlines, people, reflect.report(px)), "brain error"); return
    log(f"brain: {plan.get('reasoning', '')}")
    learn.add_lesson(plan.get("lesson", ""), track)
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
        learn.record_sell(full, signals=s["signals"], evidence=s["evidence"], hour_et=now.hour)
        filled_sells.append(s)
        extra = f" → ${rec.get('proceeds', 0):.2f} ({rec.get('realized_pct', 0):+.2f}%)" if "proceeds" in rec else ""
        log(f"- SELL {s['pct']:.0f}% {s['ticker']} [{rec['status']}]{extra} {s['signals']} — {s['why']} | evidence: {s['evidence']}")
        did += 1
    if is_sim and sells:
        remaining = round(min(g["_weekly_budget"] - st["spent"], broker.cash()), 2)

    # --- buys ---
    orders, dropped = ([], []) if nothing_to_buy else apply_guardrails(plan, allowed, remaining, st, g, cleanup)
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

    placed, trejected = triggers.place(plan.get("triggers"), now, set(broker.positions()), allowed, px)
    for d in trejected:
        log(f"  (dropped {d})")
    for t in placed:
        detail = f"trail {t['trail_pct']}%" if t["kind"] == "trailing_stop" else f"${t['price']:.2f}"
        size = f"${t['usd']:.2f}" if t["kind"] in triggers.BUY_KINDS else f"{t['pct_of_position']:.0f}%"
        log(f"~ WORKING {t['kind']} {size} {t['ticker']} @ {detail} until {t['good_until']} — {t['why']}")
    st["last_check_ts"] = int(now.timestamp())
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
                working_orders=book, next_check_minutes=plan.get("next_check_minutes"))

if __name__ == "__main__":
    if "--publish" in sys.argv:
        publish_only()
    else:
        main(report_only="--report" in sys.argv, force="--force" in sys.argv)
