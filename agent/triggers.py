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

BUY_KINDS = {"buy_limit", "buy_stop"}
SELL_KINDS = {"take_profit", "stop_loss", "trailing_stop"}
KINDS = BUY_KINDS | SELL_KINDS
MAX_WORKING = 24                 # keep the working book readable and the file small
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
            "id": uuid.uuid4().hex[:8], "ticker": ticker, "kind": kind, "price": round(price, 4),
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
                rec["high_water"] = round(last, 4)
                rec["price"] = round(last * (1 - rec["trail_pct"] / 100), 4) if last else 0.0
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
    for raw in (plan_triggers or [])[:12]:
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
                stop = round(hw * (1 - trail), 4)
                if float(b["l"]) <= stop:
                    hit = (b, stop); break
            o["high_water"] = round(hw, 4)
            o["price"] = round(hw * (1 - trail), 4)             # shown on the dashboard as the live stop
            if not hit:
                continue
            b, stop = hit
            o["price"] = stop
            fill = round(stop * (1 - slippage_pct / 100), 4)
            fires.append({**o, "fill_price": fill, "fired_ts": int(b["t"]), "stop_at": stop})
        else:
            hit = next((b for b in seq if _crossed(o, float(b["l"]), float(b["h"]))), None)
            if not hit:
                continue
            fill = o["price"]
            if o["kind"] == "buy_stop":                        # a stop becomes a market order: pay up
                fill = round(fill * (1 + slippage_pct / 100), 4)
            elif o["kind"] == "stop_loss":
                fill = round(fill * (1 - slippage_pct / 100), 4)
            fires.append({**o, "fill_price": round(fill, 4), "fired_ts": int(hit["t"])})
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

def cancel_all_for(ticker: str, kinds: set, now: datetime, reason: str) -> int:
    d = _load(); n = 0
    for o in d["orders"]:
        if o.get("status") == "working" and o["ticker"] == ticker and o["kind"] in kinds:
            o["status"] = "cancelled"; o["closed"] = now.strftime("%Y-%m-%d %H:%M"); o["cancel_reason"] = reason; n += 1
    if n:
        _save(d)
    return n

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
