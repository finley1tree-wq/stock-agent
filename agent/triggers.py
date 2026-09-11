"""Standing orders: decisions made in advance, executed when the price gets there.

The brain only thinks every so often, but the market moves continuously. Without this, every
buy and sell lands at whatever the price happened to be at the moment of a check — an arbitrary
clock tick, not a level anyone would choose. A standing order fixes the *price* in advance and
lets the market decide the *time*:

    buy_limit     buy if it falls to X          (accumulate on a dip)
    buy_stop      buy if it rises through X     (confirmation / breakout)
    take_profit   sell part of a position at X  (bank a gain)
    stop_loss     sell part of a position at X  (cap a loss)
    trailing_stop sell after it falls N% from its high since the order was placed

Between two checks the agent replays the intraday bars it missed, so an order whose level was
touched at 10:47 fills at 10:47 at its own price — not at the next check's price. Stop orders
take a small adverse slippage, because in real life a stop is a market order once it triggers.

triggers.json holds the working orders. Every fill still passes through the same guardrails and
the same ledger as a decision made live.
"""
import json
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
FILE = ROOT / "triggers.json"
ET = ZoneInfo("America/New_York")

def px_round(v: float) -> float:
    """Keep a price meaningful at any scale.

    Rounding to four decimals is fine for a $470 stock and fatal for a token at $0.00000304, which
    becomes exactly zero and takes every level computed from it to zero with it. Same rule as
    broker_sim._px: cents above a dollar, significant figures below it.
    """
    v = float(v)
    if v == 0:
        return 0.0
    return round(v, 4) if abs(v) >= 1 else float(f"{v:.8g}")

BUY_KINDS = {"buy_limit", "buy_stop"}
SELL_KINDS = {"take_profit", "stop_loss", "trailing_stop"}
KINDS = BUY_KINDS | SELL_KINDS
MAX_WORKING = 60                 # 5 positions x 2-3 brackets + 6 dip orders needs far more than 24;
                                 # at 24 the newest orders were silently dropped
DEFAULT_GOOD_FOR_DAYS = 5

def _load() -> dict:
    if not FILE.exists():
        return {"orders": []}
    try:
        d = json.loads(FILE.read_text())
        return d if isinstance(d, dict) and isinstance(d.get("orders"), list) else {"orders": []}
    except Exception:
        return {"orders": []}

def _save(d: dict) -> None:
    FILE.write_text(json.dumps(d, indent=1, default=str))

def working(now: datetime | None = None) -> list[dict]:
    """Live orders only: not filled, not cancelled, not expired."""
    today = (now or datetime.now(ET)).date()
    return [o for o in _load()["orders"]
            if o.get("status") == "working" and date.fromisoformat(o["good_until"]) >= today]

def all_orders() -> list[dict]:
    return _load()["orders"]

def _clean(o: dict, now: datetime, default_good_until: str, px: dict | None = None) -> dict | None:
    """Validate one brain-proposed order into a stored trigger, or None if unusable."""
    try:
        kind = str(o.get("kind", "")).strip().lower()
        ticker = str(o.get("ticker", "")).strip().upper()
        price = float(o.get("price", 0) or 0)
        if kind not in KINDS or not ticker:
            return None
        if kind == "trailing_stop":
            pct = float(o.get("trail_pct", 0) or 0)
            if not 0.5 <= pct <= 50:
                return None
            price = 0.0
        elif price <= 0:
            return None
        rec = {
            "id": uuid.uuid4().hex[:8], "ticker": ticker, "kind": kind, "price": px_round(price),
            "status": "working", "created": now.strftime("%Y-%m-%d %H:%M"), "created_ts": int(now.timestamp()),
            "why": str(o.get("why", ""))[:240], "evidence": str(o.get("evidence", ""))[:240],
            "signals": [str(s)[:24] for s in (o.get("signals") or [])][:6],
            "good_until": str(o.get("good_until") or default_good_until)[:10],
        }
        try:
            date.fromisoformat(rec["good_until"])
        except Exception:
            rec["good_until"] = default_good_until
        if kind in BUY_KINDS:
            usd = float(o.get("usd", 0) or 0)
            if usd <= 0:
                return None
            rec["usd"] = round(usd, 2)
        else:
            pct = float(o.get("pct_of_position", 0) or 0)
            if not 0 < pct <= 100:
                return None
            rec["pct_of_position"] = round(pct, 2)
            if kind == "trailing_stop":
                rec["trail_pct"] = round(float(o["trail_pct"]), 2)
                # the high since placement starts at the price right now, so the stop has a real
                # level from the first moment instead of showing zero until the next bar arrives
                last = float(((px or {}).get(ticker) or {}).get("price") or 0)
                rec["high_water"] = px_round(last)
                rec["price"] = px_round(last * (1 - rec["trail_pct"] / 100)) if last else 0.0
        return rec
    except Exception:
        return None

def place(plan_triggers: list, now: datetime, held: set, allowed: set, px: dict | None = None) -> tuple[list[dict], list[str]]:
    """Store the brain's new standing orders. Returns (placed, rejected_reasons)."""
    d = _load()
    live = {(o["ticker"], o["kind"],
             round(float(o.get("trail_pct", 0)), 2) if o["kind"] == "trailing_stop" else round(float(o.get("price", 0)), 2))
            for o in d["orders"] if o.get("status") == "working"}
    default_good_until = (now.date() + timedelta(days=DEFAULT_GOOD_FOR_DAYS)).isoformat()
    placed, rejected = [], []
    n_working = len([o for o in d["orders"] if o.get("status") == "working"])
    for raw in (plan_triggers or [])[:40]:      # was 12: brackets alone can exceed that with 5 names
        if not isinstance(raw, dict):
            continue
        rec = _clean(raw, now, default_good_until, px)
        if not rec:
            rejected.append(f"trigger {str(raw.get('ticker', '?'))[:8]}: malformed or out of range"); continue
        if not str(rec.get("evidence", "")).strip():
            rejected.append(f"trigger {rec['ticker']}: no evidence given"); continue
        if rec["kind"] in SELL_KINDS and rec["ticker"] not in held:
            rejected.append(f"trigger {rec['ticker']} {rec['kind']}: not held"); continue
        if rec["kind"] in BUY_KINDS and rec["ticker"] not in allowed:
            rejected.append(f"trigger {rec['ticker']} {rec['kind']}: not in the allowed universe"); continue
        key = (rec["ticker"], rec["kind"],
               round(rec["trail_pct"], 2) if rec["kind"] == "trailing_stop" else round(rec["price"], 2))
        if key in live:
            rejected.append(f"trigger {rec['ticker']} {rec['kind']}: duplicate of a working order"); continue
        if n_working >= MAX_WORKING:
            rejected.append(f"trigger {rec['ticker']}: working-order book is full ({MAX_WORKING})"); continue
        live.add(key); n_working += 1
        d["orders"].append(rec); placed.append(rec)
    d["orders"] = d["orders"][-400:]
    d["updated"] = now.strftime("%Y-%m-%d %H:%M")
    _save(d)
    return placed, rejected

def _crossed(o: dict, lo: float, hi: float) -> bool:
    p = o["price"]
    if o["kind"] in ("buy_limit", "stop_loss"):
        return lo <= p
    if o["kind"] in ("buy_stop", "take_profit"):
        return hi >= p
    return False

def evaluate(now: datetime, px: dict, bars: dict, held: set, slippage_pct: float = 0.05) -> tuple[list[dict], list[str]]:
    """Replay the bars since the last check and fire any order whose level was reached.

    bars: {ticker: [{"t": epoch_s, "h": high, "l": low, "c": close}, ...]} newest last. When a
    ticker has no bars, the current quote is used as a single bar. Returns (fires, notes) where a
    fire carries the price to fill at; the caller executes it through the broker.
    """
    d = _load()
    today = now.date()
    fires, notes = [], []
    for o in d["orders"]:
        if o.get("status") != "working":
            continue
        if date.fromisoformat(o["good_until"]) < today:
            o["status"] = "expired"; o["closed"] = now.strftime("%Y-%m-%d %H:%M")
            notes.append(f"trigger {o['ticker']} {o['kind']} @ {o['price']} expired"); continue
        if o["kind"] in SELL_KINDS and o["ticker"] not in held:
            o["status"] = "cancelled"; o["closed"] = now.strftime("%Y-%m-%d %H:%M")
            o["cancel_reason"] = "position no longer held"
            notes.append(f"trigger {o['ticker']} {o['kind']} cancelled (position gone)"); continue
        q = px.get(o["ticker"]) or {}
        last = q.get("price")
        seq = bars.get(o["ticker"]) or ([{"t": int(now.timestamp()), "h": last, "l": last, "c": last}] if last else [])
        seq = [b for b in seq if b.get("h") is not None and b.get("l") is not None
               and int(b.get("t", 0)) >= int(o.get("created_ts", 0))]
        if not seq:
            continue
        if o["kind"] == "trailing_stop":
            # Walk the bars in order. The stop can only ever be raised by highs already seen, so a
            # dip is never judged against a peak that had not happened yet.
            hw = float(o.get("high_water") or 0)
            trail = float(o["trail_pct"]) / 100
            hit = None
            for b in seq:
                hw = max(hw, float(b["h"]))
                stop = px_round(hw * (1 - trail))
                if float(b["l"]) <= stop:
                    hit = (b, stop); break
            o["high_water"] = px_round(hw)
            o["price"] = px_round(hw * (1 - trail))             # shown on the dashboard as the live stop
            if not hit:
                continue
            b, stop = hit
            o["price"] = stop
            fill = px_round(stop * (1 - slippage_pct / 100))
            fires.append({**o, "fill_price": fill, "fired_ts": int(b["t"]), "stop_at": stop})
        else:
            hit = next((b for b in seq if _crossed(o, float(b["l"]), float(b["h"]))), None)
            if not hit:
                continue
            fill = o["price"]
            if o["kind"] == "buy_stop":                        # a stop becomes a market order: pay up
                fill = px_round(fill * (1 + slippage_pct / 100))
            elif o["kind"] == "stop_loss":
                fill = px_round(fill * (1 - slippage_pct / 100))
            fires.append({**o, "fill_price": px_round(fill), "fired_ts": int(hit["t"])})
    _save(d)
    return fires, notes

def close(order_id: str, now: datetime, status: str, detail: str = "") -> None:
    d = _load()
    for o in d["orders"]:
        if o.get("id") == order_id and o.get("status") == "working":
            o["status"] = status
            o["closed"] = now.strftime("%Y-%m-%d %H:%M")
            if detail:
                o["cancel_reason"] = detail
    d["updated"] = now.strftime("%Y-%m-%d %H:%M")
    _save(d)

def cancel_all_buys(now: datetime, reason: str) -> int:
    """Retire every working buy order. Used inside the last max_hold_minutes of the session, when
    a fill could no longer be closed by the clock before the bell."""
    d = _load(); n = 0
    for o in d["orders"]:
        if o.get("status") == "working" and o["kind"] in BUY_KINDS:
            o["status"] = "cancelled"; o["closed"] = now.strftime("%Y-%m-%d %H:%M")
            o["cancel_reason"] = reason; n += 1
    if n:
        _save(d)
    return n

def cancel_position_orders(ticker: str, now: datetime, reason: str) -> int:
    """When a position closes, retire everything that was attached to it.

    Cancelling only the sell side is a trap: the averaging-in buy order would still be working, so
    a stop-out would immediately re-enter the same position slightly lower. That turns the stop
    into a pause. Any order the agent attached to this position goes with it; a buy the brain
    placed on its own judgement is left alone.
    """
    d = _load(); n = 0
    for o in d["orders"]:
        if o.get("status") != "working" or o["ticker"] != ticker:
            continue
        if o["kind"] in SELL_KINDS or {"auto_bracket", "dip_entry"} & set(o.get("signals") or []):
            o["status"] = "cancelled"; o["closed"] = now.strftime("%Y-%m-%d %H:%M")
            o["cancel_reason"] = reason; n += 1
    if n:
        _save(d)
    return n

def cancel_all_for(ticker: str, kinds: set, now: datetime, reason: str) -> int:
    d = _load(); n = 0
    for o in d["orders"]:
        if o.get("status") == "working" and o["ticker"] == ticker and o["kind"] in kinds:
            o["status"] = "cancelled"; o["closed"] = now.strftime("%Y-%m-%d %H:%M"); o["cancel_reason"] = reason; n += 1
    if n:
        _save(d)
    return n

def tp_size_pct(cfg: dict) -> float:
    """How much of the position exits on the limit target.

    A partial exit is a multi-day idea: sell a third, let the rest run. With max_hold_minutes set
    there is nothing to run into - time_stops closes the remainder at market inside the same half
    hour (paying spread_cost_pct), or the break-even stop takes it at trigger_slippage_pct. Either
    way a free limit fill is converted into a paid one. Measured on 112,063 real 30-minute windows:
    -0.0478%/trade at 33% vs -0.0449% at 100%, differing only on the windows that reach the target.
    Off the clock the 20-day evidence in config.yaml still holds, so the configured size stands.
    """
    size = float(cfg.get("take_profit_size_pct", 50) or 50)
    return 100.0 if float(cfg.get("_max_hold_minutes", 0) or 0) > 0 else size

def auto_bracket(now: datetime, positions: dict, px: dict, cfg: dict) -> list[dict]:
    """Give every open position an exit plan the moment it exists.

    A day trade is defined by its exit, not its entry. Left to a 30-minute cadence the agent can
    watch a position round-trip a whole move without ever being asked. So any position without a
    protective order gets one now: a target to sell into strength and a stop to cap the loss. The
    brain can always place better ones itself; these only fill the gaps it left.
    """
    if not cfg or not cfg.get("enabled", True):
        return []
    tp_size = tp_size_pct(cfg)
    live = working(now)
    has = {(o["ticker"], o["kind"]) for o in live}
    protected = {o["ticker"] for o in live if o["kind"] in ("stop_loss", "trailing_stop")}
    out = []
    for t, pos in (positions or {}).items():
        entry = float(pos.get("avg_cost") or 0)
        if entry <= 0:
            continue
        tp, sl = levels(t, px, cfg)
        if tp > 0 and (t, "take_profit") not in has:
            out.append({"ticker": t, "kind": "take_profit", "price": round(entry * (1 + tp / 100), 2),
                        "pct_of_position": tp_size, "trail_pct": 0, "usd": 0,
                        "signals": ["risk_management", "auto_bracket"],
                        "evidence": f"entry ${entry:.2f}, target +{tp:.1f}%",
                        "why": f"take profit on {tp_size:.0f}% at +{tp:.1f}% from the entry"})
        if sl > 0 and t not in protected:
            out.append({"ticker": t, "kind": "stop_loss", "price": round(entry * (1 - sl / 100), 2),
                        "pct_of_position": 100, "trail_pct": 0, "usd": 0,
                        "signals": ["risk_management", "auto_bracket"],
                        "evidence": f"entry ${entry:.2f}, stop -{sl:.1f}%",
                        "why": f"cap the loss at -{sl:.1f}% from the entry"})
    return out

AUTO = "auto_bracket"

def levels(ticker: str, px: dict | None, cfg: dict) -> tuple[float, float]:
    """(target %, stop %) sized to THIS stock's own daily range where possible.

    A flat 2.5% stop is 3.5x SPY's average daily move and 0.39x OKLO's - unreachable on one, hit
    by lunchtime noise on the other. Measured across the watchlist that is a 9x spread, so one
    number cannot be right for both, and the drag is proportional to volatility: a fixed bracket
    costs 0.014pp per trade on SPY and 0.570pp on SOXL. Falls back to the fixed percentages when
    ATR is unavailable, and is bounded so a wild reading cannot produce an absurd level.
    """
    atr = float(((px or {}).get(ticker) or {}).get("atr_pct") or 0)
    sl_a = float(cfg.get("stop_loss_atr", 0) or 0)
    tp_a = float(cfg.get("take_profit_atr", 0) or 0)

    # THE LEVELS MUST MATCH THE HOLD PERIOD. Measured on real 30-minute bars: a 6x-ATR target was
    # reached in 0.0% of 30-minute windows on every watchlist name - INTC moves 0.41% in half an
    # hour against a target sitting at 26.58%, sixty-five times too far. With a 30-minute clock
    # that means the target and the stop NEVER fire and every position exits on time at a random
    # price minus the round trip, which is a guaranteed slow bleed rather than a strategy.
    #
    # Volatility grows with the square root of time, so the move available in M minutes is about
    # ATR x sqrt(M/390). The levels are scaled to that when an intraday clock is set.
    hold_m = float(cfg.get("_max_hold_minutes", 0) or 0)
    if atr > 0 and hold_m > 0:
        import math
        reach = atr * math.sqrt(max(1.0, hold_m) / 390.0)      # the move actually available
        tp = reach * float(cfg.get("intraday_target_mult", 0.6) or 0.6)
        sl = reach * float(cfg.get("intraday_stop_mult", 1.0) or 1.0)
        floor = float(cfg.get("intraday_floor_pct", 0.15) or 0.15)
        return round(max(tp, floor), 3), round(max(sl, floor), 3)

    if atr > 0 and sl_a > 0 and tp_a > 0:
        lo = float(cfg.get("stop_floor_pct", 1.5) or 1.5)
        hi = float(cfg.get("stop_cap_pct", 12) or 12)
        return round(atr * tp_a, 3), round(min(max(atr * sl_a, lo), hi), 3)
    return float(cfg.get("take_profit_pct", 3) or 0), float(cfg.get("stop_loss_pct", 2) or 0)

def _is_auto(o: dict) -> bool:
    return AUTO in (o.get("signals") or [])

def _closed_after(order: dict, pos: dict) -> bool:
    """Did this order fill AFTER the current position was opened?

    Without this, a take-profit banked on an earlier, already-closed position in the same ticker
    keeps applying to every later one - suppressing its target and pinning its stop to break-even.
    A position with no opened_ts (pre-dating the field) is treated as new, which is the safe
    reading: it gets an ordinary target and an ordinary stop.
    """
    opened = pos.get("opened_ts") or pos.get("last_buy_ts")
    if not opened:
        return False
    stamp = order.get("closed") or ""
    try:
        closed = datetime.strptime(str(stamp)[:16], "%Y-%m-%d %H:%M").replace(tzinfo=ET).timestamp()
    except (ValueError, TypeError):
        return False
    # An order's close time is recorded to the MINUTE while opened_ts is to the second, so compare
    # at the coarser precision. Without this a target banked in the same minute as the buy parses
    # as 14:30:00 against an open at 14:30:45 and reads as "before the position existed" - which
    # silently disabled the break-even stop the rule exists to provide.
    return closed >= (float(opened) // 60) * 60

def rebalance_brackets(now: datetime, positions: dict, px: dict, cfg: dict) -> tuple[list[dict], int]:
    """Keep every position's exit plan pinned to its CURRENT average cost, and offer to average in.

    This is the pattern behind the "wait until the whole thing is green, then close it" videos: buy
    in tranches as it falls, and let the exit follow the blended average so the basket is closed as
    one. Two differences from the version in those clips, both deliberate:

      * the number of tranches is capped, so the position size cannot grow without bound;
      * there is a hard basket stop. The strategy wins small and often and loses everything rarely.
        Removing the rare branch is the whole job, and the clips have nothing in that place.

    Returns (orders_to_place, number_of_stale_orders_cancelled).
    """
    if not cfg or not cfg.get("enabled", True):
        return [], 0
    tp_size = tp_size_pct(cfg)
    scale = cfg.get("scale_in") or {}
    scale_on = bool(scale.get("enabled"))
    max_tranches = int(scale.get("max_tranches", 1) or 1)
    add_drop = float(scale.get("add_after_drop_pct", 0) or 0)
    # Sized as a fraction of the budget: a hard-coded dollar amount silently stopped working the
    # moment the account changed size, and every add was dropped for months of checks.
    budget = float(cfg.get("_weekly_budget", 0) or 0)
    add_usd = float(scale.get("add_usd", 0) or 0)
    pct = float(scale.get("add_pct_of_budget", 0) or 0)
    if pct > 0 and budget > 0:
        add_usd = round(budget * pct / 100, 2)

    live = working(now)
    done = all_orders()
    want, cancelled = [], 0
    for t, pos in (positions or {}).items():
        entry = float(pos.get("avg_cost") or 0)
        if entry <= 0:
            continue
        tp, sl = levels(t, px, cfg)
        price = float(((px or {}).get(t) or {}).get("price") or 0)
        mine = [o for o in live if o["ticker"] == t and _is_auto(o)]
        # Has this position's automatic target already been taken? Selling does not change
        # avg_cost, so without this check a new target is recreated at the same price after every
        # fill and the position is liquidated in halves at +tp%: seen live on AMD, sold four times
        # at $521.99 for 0.0491 -> 0.0245 -> 0.0123 -> 0.0061 shares. That caps the best possible
        # outcome of every trade at the target, which is the opposite of scaling out.
        # ...BY THIS POSITION. The check used to ask whether the TICKER had ever banked a target,
        # with no time limit, which was equivalent while a name was bought once and held for days.
        # Under a 30-minute clock and a 45-minute rebuy cooldown a name is re-bought repeatedly, so
        # by the afternoon almost every ticker had "banked" - and every NEW position in it was born
        # with no profit target and a stop sitting exactly at its entry price. Measured live on
        # 2026-09-11: five positions stopped out at -0.05% (exactly the slippage), three of them
        # held zero minutes, all in names that had banked a target hours earlier.
        banked = any(o["ticker"] == t and o["kind"] == "take_profit" and o.get("status") == "filled"
                     and _is_auto(o) and _closed_after(o, pos) for o in done)
        targets = {}
        if tp > 0 and not banked:
            targets["take_profit"] = px_round(entry * (1 + tp / 100))
        if sl > 0:
            # (Daily-path rule. On the intraday path the target takes 100%, so "banked" never
            # occurs and this branch is unreachable - by design.)
            # Once part of the position has been sold into a target, the rest rides for free: the
            # stop moves up to the entry. Without this the arithmetic is upside down - banking
            # +2.5% on HALF while stopping out ALL of it means risking 2 to make 1.25, which needs
            # a 63% win rate just to break even. Break-even stops turn every partial win into a
            # position that can no longer lose money.
            floor_px = entry if banked else entry * (1 - sl / 100)

            # THE RATCHET. A trade that works usually works fast: measured on 2026-09-11, exits
            # that hit their target did so in 8 minutes at +0.32%, while everything that rode the
            # full 30-minute clock averaged +0.09% - the gain was made and then handed back while
            # the position waited for a timer. So once a position is a decent way toward its
            # target, the stop climbs behind the price and never steps back down. A winner that
            # stalls is sold near its high instead of at whatever the clock happens to find.
            after = float(cfg.get("ratchet_after_pct_of_target", 0) or 0)
            keep = float(cfg.get("ratchet_keep_pct_of_gain", 0) or 0)
            if price > entry and tp > 0 and after > 0 and keep > 0:
                gain = (price / entry - 1) * 100
                if gain >= tp * after / 100:
                    floor_px = max(floor_px, entry * (1 + (gain * keep / 100) / 100))
                # a ratchet only ever tightens: never re-pin below where the stop already sits
                cur = next((float(o["price"]) for o in mine if o["kind"] == "stop_loss"), 0.0)
                if cur > 0:
                    floor_px = max(floor_px, cur)
            targets["stop_loss"] = px_round(floor_px)
        if scale_on and add_drop > 0 and add_usd > 0 and int(pos.get("tranches", 1)) < max_tranches:
            targets["buy_limit"] = px_round(entry * (1 - add_drop / 100))
        # a hand-placed protective order still counts, so we never double up on stops
        if any(o["kind"] in ("stop_loss", "trailing_stop") and not _is_auto(o) for o in live if o["ticker"] == t):
            targets.pop("stop_loss", None)
        for o in mine:
            k = o["kind"]
            # A ratcheting stop would otherwise be re-pinned on every tick for a fraction of a
            # cent. Sells need a wider tolerance than the 0.05% used for levels that must be exact.
            tol = targets[k] * (0.0015 if k in SELL_KINDS else 0.0005) if k in targets else 0
            stale = k not in targets or abs(float(o["price"]) - targets[k]) > max(1e-9, tol)
            # SIZE matters as much as price. An order left over from a smaller account keeps its
            # old dollar amount forever, fires on every check, and is thrown away by the minimum
            # order rule every time - which is exactly what happened when the account went from
            # $400 to $25,000 and a stale $25 add order looped all morning.
            if not stale and k in BUY_KINDS:
                stale = abs(float(o.get("usd") or 0) - add_usd) > max(0.01, add_usd * 0.02)
            if not stale and k in SELL_KINDS:
                stale = abs(float(o.get("pct_of_position") or 0) - (tp_size if k == "take_profit" else 100)) > 0.5
            if stale:
                close(o["id"], now, "cancelled", "level or size no longer matches"); cancelled += 1
            else:
                targets.pop(k, None)                     # already working at the right level
        for kind, price in targets.items():
            row = {"ticker": t, "kind": kind, "price": price, "trail_pct": 0,
                   "signals": ["risk_management", AUTO],
                   "evidence": f"average cost ${entry:.6f}".rstrip("0").rstrip("."),
                   "usd": 0, "pct_of_position": 0}
            if kind == "take_profit":
                row.update(pct_of_position=tp_size, why=f"close {tp_size:.0f}% at +{tp:.1f}% over the average cost")
            elif kind == "stop_loss":
                row.update(pct_of_position=100, why=f"close it all at -{sl:.1f}% under the average cost")
            else:
                row.update(usd=add_usd, why=f"average in another ${add_usd:.0f} if it falls {add_drop:.1f}% below the average cost")
            want.append(row)
    return want, cancelled

def dip_hunt(now: datetime, held: set, allowed: set, px: dict, cfg: dict, budget: float) -> list[dict]:
    """Rest buy orders UNDER the market on names it does not own yet.

    Until now the only buy-limit the agent could place was scale_in, which averages down into a
    position it already holds. So it could never buy a dip as an ENTRY - only add to something
    already going against it. That is backwards, and it is why no dip order ever fired on a new
    name.

    What gets an order: names with positive one-month momentum that are currently in the LOWER
    part of today's range. Strong stock, weak day - the order sits below the market and fills only
    if the dip actually comes to it.

    Honest status of the gate: the replay's only "real" row is momentum_1w at 21 days. One-month
    momentum is indistinguishable from luck at every horizon it measured, and nothing at all has
    been measured at 30 minutes. This screen is unproven at the horizon it is used on, and is
    kept because it is cheap, explainable, and graded - the dip_entry tag lets the loop score it.
    """
    if not cfg or not cfg.get("enabled", True) or budget <= 0:
        return []
    n = int(cfg.get("names", 6) or 6)
    # How deep the dip has to be, per stock. A flat 1.5% is the same mistake the targets made:
    # measured over a month of 30-minute bars it is reached in only 7.2% of windows on average and
    # 2.8% on META, so the orders sat there all day and never filled. Depth now scales with the
    # move each name actually makes in the hold window - a real dip, but one that arrives.
    hold_m = float(cfg.get("_max_hold_minutes", 0) or 0)
    dip_mult = float(cfg.get("dip_atr_mult", 0.75) or 0.75)
    flat_below = float(cfg.get("below_pct", 1.5) or 1.5)
    # Size off the ACCOUNT, not the leftovers: 4% of what remains falls under the $100 minimum the
    # moment the book is mostly deployed, and never reaches the $1,000 target once anything is held.
    # Then cap by what is actually affordable, and place nothing rather than an order that would fire
    # and be dropped for the rest of its life.
    floor = float(cfg.get("_min_order_usd", 0) or 0)
    base = float(cfg.get("_budget_full", 0) or 0) or budget
    usd = max(round(base * float(cfg.get("usd_pct_of_budget", 4) or 4) / 100, 2), floor)
    cap = float(cfg.get("_cash_cap", 0) or 0)
    if cap > 0:
        usd = min(usd, round(cap, 2))
        n = min(n, max(1, int(cap // usd))) if usd > 0 else 0
    if usd <= 0 or usd < floor:
        return []
    skip = {str(x).upper() for x in (cfg.get("_skip") or [])}   # names inside the rebuy cooldown
    live = {(o["ticker"], o["kind"]) for o in working(now)}
    cands = []
    for t in sorted(set(allowed) - set(held) - skip):
        q = px.get(t) or {}
        price, m1m = q.get("price"), q.get("change_1m_pct")
        rng = q.get("pct_of_day_range")
        if not price or m1m is None or m1m <= 0:
            continue                                   # only names with the measured signal behind them
        if rng is None or rng > 60:
            continue        # near the day's high, or the day has no range yet to measure - either
                            # way this is not a measured dip. Thin names print one price for the
                            # first minutes and the key is absent, which was admitting them.
        cands.append((m1m, t, price, rng))
    cands.sort(reverse=True)
    out = []
    for m1m, t, price, rng in cands[:n]:
        if (t, "buy_limit") in live:
            continue
        atr = float((px.get(t) or {}).get("atr_pct") or 0)
        if atr > 0 and hold_m > 0:
            import math
            below = max(atr * math.sqrt(max(1.0, hold_m) / 390.0) * dip_mult,
                        float(cfg.get("dip_floor_pct", 0.2) or 0.2))
        else:
            below = flat_below
        level = px_round(price * (1 - below / 100))
        out.append({"ticker": t, "kind": "buy_limit", "price": level, "usd": usd,
                    "pct_of_position": 0, "trail_pct": 0,
                    # a dip order sized for half an hour has no business resting for a week
                    "good_until": (now.date() + timedelta(days=int(cfg.get("good_for_days", 1) or 1))).isoformat(),
                    "signals": ["momentum", "dip_entry"],
                    "evidence": f"+{m1m:.1f}% over the month, sitting at {rng:.0f}% of today's range",
                    "why": f"strong month, weak day: resting {below:.2f}% under ${price:.2f} to catch the dip"})
    return out

def summary(px: dict, now: datetime | None = None) -> list[dict]:
    """Working book for the brain and the dashboard, with distance to each level."""
    out = []
    for o in working(now):
        last = (px.get(o["ticker"]) or {}).get("price")
        away = round((o["price"] / last - 1) * 100, 2) if last and o["price"] else None
        out.append({"id": o["id"], "ticker": o["ticker"], "kind": o["kind"], "price": o["price"],
                    "usd": o.get("usd"), "pct_of_position": o.get("pct_of_position"),
                    "trail_pct": o.get("trail_pct"), "last": last, "pct_away": away,
                    "good_until": o["good_until"], "why": o["why"], "signals": o.get("signals") or []})
    return sorted(out, key=lambda r: (abs(r["pct_away"]) if r["pct_away"] is not None else 999))
