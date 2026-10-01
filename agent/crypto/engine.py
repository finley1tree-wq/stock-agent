"""The cloud crypto paper trader: every liquid Coinbase coin, a strategy chosen per coin by natural
selection, pretend money only.

Owner's instruction, 2026-10-01: trade every coin, not just Bitcoin; hold whatever needs holding;
find a strategy for each coin. Run hourly by .github/workflows/crypto.yml; decisions once a day on
the closed daily bar (UTC), marks every run.

Each (coin, strategy) is an organism. Its fitness is its own backtest on that coin's full Coinbase
daily history after Coinbase costs, plus its live forward record since it started being tracked:
    SURVIVOR   passes the pre-registered bar (see _stage)            full sleeve
    PROBATION  unproven                                               probation_size of a sleeve
    CULLED     dead in the backtest, or losing live (n >= 10, t <= -1) no money
Each coin's CHAMPION is its best non-culled organism (survivors first, then by Sharpe); "hold" is
a candidate like any other, so a coin can simply be held. Every organism keeps a shadow position
whether or not it has the money, so a challenger that starts winning live can take the coin over.

The book: pretend start_usd split into equal sleeves, one per coin in the universe. A coin's sleeve
is bought when its champion goes long and sold when it goes flat or loses the coin; positions are
not resized day to day, because every trade pays Coinbase's fee twice.
Outputs crypto/book.json (holdings with quantities, for the dashboard), crypto/ledger.json,
crypto/organisms.json.
"""
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from . import coinbase
from .strategies import STRATEGIES, WARMUP

ROOT = Path(__file__).resolve().parent.parent.parent
DIR = ROOT / "crypto"
CFG = DIR / "config.json"
BOOK = DIR / "book.json"
LEDGER = DIR / "ledger.json"
ORGS = DIR / "organisms.json"

DEFAULTS = {"start_usd": 10000.0, "fee_pct": 0.60, "slippage_pct": 0.05, "min_dollar_volume": 5e6,
            "max_coins": 40, "probation_size": 0.25, "history_days": 1100,
            "pass": {"min_trips": 30, "min_days_in_market": 365, "min_sharpe": 0.5, "dd_edge_pts": 20},
            "live_cull": {"min_trips": 10, "t": -1.0}}


def _load(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _save(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=1), encoding="utf-8")


def config() -> dict:
    c = {**DEFAULTS, **_load(CFG, {})}
    c["pass"] = {**DEFAULTS["pass"], **(c.get("pass") or {})}
    c["live_cull"] = {**DEFAULTS["live_cull"], **(c.get("live_cull") or {})}
    return c


# ---- backtest ---------------------------------------------------------------------------------
def backtest(bars: list[dict], name: str, cost_pct: float) -> dict:
    """Decide on bar i's close, fill at bar i+1's open, pay cost_pct per side, mark at closes.
    Also returns the decision on the LAST closed bar ("signal"): the position for the next day."""
    fn, st, pos = STRATEGIES[name], {}, 0
    c = 1 - cost_pct / 100
    eq, peak, max_dd, entry_eq = 1.0, 1.0, 0.0, None
    curve, trips, days_in = [], [], 0
    n, mid = len(bars), WARMUP + (len(bars) - WARMUP) // 2
    first = [None, None]
    second = [None, None]
    signal = 0
    for i in range(WARMUP, n):
        want, st = fn(bars, i, st)
        if i == n - 1:
            signal = want
            break
        nxt, prev = bars[i + 1], eq
        if want and not pos:                       # buy at the next open
            entry_eq = eq
            eq *= c * nxt["c"] / nxt["o"]
        elif pos and not want:                     # sell at the next open
            eq *= nxt["o"] / bars[i]["c"] * c
            trips.append(eq / entry_eq - 1)
        elif pos:
            eq *= nxt["c"] / bars[i]["c"]
        pos = want
        days_in += pos
        curve.append(eq)
        peak = max(peak, eq)
        max_dd = max(max_dd, 1 - eq / peak)
        h = first if i < mid else second
        if h[0] is None:
            h[0] = prev
        h[1] = eq
    if pos and entry_eq:
        trips.append(eq / entry_eq - 1)            # still open: marked at the last close
    daily = [b / a - 1 for a, b in zip([1.0] + curve[:-1], curve)]
    years = max(len(daily) / 365, 1e-9)
    mean = sum(daily) / len(daily) if daily else 0.0
    sd = math.sqrt(sum((x - mean) ** 2 for x in daily) / (len(daily) - 1)) if len(daily) > 1 else 0.0
    rc = curve[-366:]
    ret = lambda h: round(h[1] / h[0] - 1, 4) if h[0] else 0.0
    return {"days": len(daily), "trips": len(trips), "days_in_market": days_in,
            "exposure": round(days_in / len(daily), 3) if daily else 0.0,
            "net_return": round(eq - 1, 4), "cagr": round(eq ** (1 / years) - 1, 4) if eq > 0 else -1.0,
            "sharpe": round(mean / sd * math.sqrt(365), 2) if sd > 0 else 0.0, "max_dd": round(max_dd, 4),
            "first_half": ret(first), "second_half": ret(second),
            "recent_365": round(rc[-1] / rc[0] - 1, 4) if len(rc) > 1 else 0.0,
            "win_rate": round(sum(t > 0 for t in trips) / len(trips), 3) if trips else None,
            "signal": int(signal)}


def _stage(bt: dict, hold_bt: dict, live: dict, cfg: dict, is_hold: bool) -> str:
    p, lc = cfg["pass"], cfg["live_cull"]
    if live.get("n", 0) >= lc["min_trips"] and live.get("t", 0) <= lc["t"]:
        return "CULLED"
    dead = (bt["first_half"] < 0 and bt["second_half"] < 0) or bt["sharpe"] < 0
    if dead:
        return "CULLED"
    enough = bt["trips"] >= p["min_trips"] or bt["days_in_market"] >= p["min_days_in_market"]
    beats = is_hold or bt["net_return"] > hold_bt["net_return"] or (
        bt["net_return"] > 0 and (hold_bt["max_dd"] - bt["max_dd"]) * 100 >= p["dd_edge_pts"])
    if enough and bt["cagr"] > 0 and bt["sharpe"] >= p["min_sharpe"] and bt["first_half"] > 0 \
            and bt["second_half"] > 0 and beats:
        return "SURVIVOR"
    return "PROBATION"


def _live_stats(trips: list[float]) -> dict:
    n = len(trips)
    if not n:
        return {"n": 0, "mean": None, "t": 0.0}
    m = sum(trips) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in trips) / (n - 1)) if n > 1 else 0.0
    return {"n": n, "mean": round(m, 4), "t": round(m / (sd / math.sqrt(n)), 2) if sd > 0 else 0.0}


RANK = {"SURVIVOR": 0, "PROBATION": 1, "CULLED": 2}


def select(coin_orgs: dict, incumbent: str | None = None, margin: float = 0.15) -> str | None:
    """The coin's champion: the best non-culled organism, survivors first, then by Sharpe. The
    incumbent keeps the coin unless a challenger is a better stage or beats its Sharpe by `margin`:
    every switch pays the fee twice, so two near-equal strategies must not trade places daily."""
    live = [(RANK[o["stage"]], -o["backtest"]["sharpe"], k) for k, o in coin_orgs.items() if o["stage"] != "CULLED"]
    if not live:
        return None
    best = min(live)
    inc = next((x for x in live if x[2] == incumbent), None)
    if inc and inc[0] == best[0] and -inc[1] >= -best[1] - margin:
        return incumbent
    return best[2]


# ---- the run ----------------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(timezone.utc)


def universe(cfg: dict) -> dict[str, list[dict]]:
    """{coin: daily bars} for liquid coins, most liquid first, capped at max_coins."""
    rows = []
    for coin in coinbase.usd_products():
        try:
            recent = coinbase.candles(coin, 86400, 40)
        except Exception:
            continue
        dv = sorted(b["c"] * b["v"] for b in recent[-30:])
        if len(dv) >= 20 and dv[len(dv) // 2] >= cfg["min_dollar_volume"]:
            rows.append((dv[len(dv) // 2], coin))
    rows.sort(reverse=True)
    out = {}
    for _, coin in rows[: cfg["max_coins"]]:
        try:
            bars = coinbase.candles(coin, 86400, cfg["history_days"])
        except Exception:
            continue
        # the last candle is today's, still forming: decisions use closed days only
        today = int(_now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        bars = [b for b in bars if b["t"] < today]
        if len(bars) >= WARMUP + 30:
            out[coin] = bars
    return out


def decide(cfg: dict, data: dict[str, list[dict]], orgs: dict, book: dict, ledger: list, prices: dict) -> None:
    cost = cfg["fee_pct"] + cfg["slippage_pct"]
    day = datetime.fromtimestamp(max(b[-1]["t"] for b in data.values()), timezone.utc).date().isoformat()
    coins = sorted(data)
    for gone in [c for c in orgs if c not in data and c not in book["holdings"]]:
        orgs.pop(gone)                             # left the universe and nothing held: stop scoring it
    # 1. rescore every organism and step its shadow position on today's closed bar
    for coin in coins:
        bars = data[coin]
        co = orgs.setdefault(coin, {})
        hold_bt = backtest(bars, "hold", cost)
        for name in STRATEGIES:
            o = co.setdefault(name, {"shadow": {"pos": 0, "entry": None, "state": {}}, "live_trips": []})
            bt = hold_bt if name == "hold" else backtest(bars, name, cost)
            pos = bt["signal"]
            sh = o["shadow"]
            px = prices.get(coin) or bars[-1]["c"]
            if pos and not sh["pos"]:
                sh.update(pos=1, entry=px * (1 + cost / 100), since=day)
            elif not pos and sh["pos"]:
                if sh.get("entry"):
                    o["live_trips"].append(round(px * (1 - cost / 100) / sh["entry"] - 1, 5))
                sh.update(pos=0, entry=None, since=day)
            o["backtest"] = bt
            o["live"] = _live_stats(o["live_trips"])
            o["stage"] = _stage(bt, hold_bt, o["live"], cfg, name == "hold")
            o["signal"] = int(pos)
    # 2. champions, and the book follows them
    eq = equity(book, prices)
    sleeve = eq / max(len(coins), 1)
    weight = {"SURVIVOR": 1.0, "PROBATION": float(cfg["probation_size"])}
    for coin in coins:
        prev = next((k for k, o in orgs[coin].items() if o.get("champion")), None)
        champ = select(orgs[coin], prev)
        for name, o in orgs[coin].items():
            o["champion"] = name == champ
        h = book["holdings"].get(coin)
        want = bool(champ) and orgs[coin][champ]["signal"] == 1
        px = prices.get(coin)
        if not px:
            continue
        if h and (not want or h["strategy"] != champ):
            _sell(book, ledger, coin, px, cost, day, f"{h['strategy']} {'went flat' if h['strategy'] == champ else 'lost the coin to ' + str(champ)}")
            h = None
        if want and not h:
            usd = min(sleeve * weight[orgs[coin][champ]["stage"]], book["cash"])
            if usd >= 10:
                _buy(book, ledger, coin, px, usd, cost, day, champ, orgs[coin][champ]["stage"])
    # coins that left the universe are sold
    for coin in [c for c in book["holdings"] if c not in data]:
        if prices.get(coin):
            _sell(book, ledger, coin, prices[coin], cost, day, "left the liquid universe")
    book["last_decision_day"] = day


def _buy(book, ledger, coin, px, usd, cost, day, strategy, stage):
    qty = usd * (1 - cost / 100) / px              # Coinbase fee + slippage come off the top
    book["cash"] = round(book["cash"] - usd, 6)
    book["holdings"][coin] = {"asset": coin, "qty": qty, "entry_px": px, "cost_usd": usd, "since": day,
                              "strategy": strategy, "stage": stage}
    ledger.append({"ts": _now().isoformat(timespec="seconds"), "day": day, "side": "buy", "asset": coin, "qty": qty,
                   "price": px, "usd": round(usd, 2), "cost_pct": cost, "strategy": strategy, "stage": stage})


def _sell(book, ledger, coin, px, cost, day, why):
    h = book["holdings"].pop(coin)
    gross = h["qty"] * px
    net = gross * (1 - cost / 100)
    book["cash"] = round(book["cash"] + net, 6)
    pnl = net - h["cost_usd"]
    book["realized"] = round(book.get("realized", 0.0) + pnl, 2)
    ledger.append({"ts": _now().isoformat(timespec="seconds"), "day": day, "side": "sell", "asset": coin, "qty": h["qty"],
                   "price": px, "usd": round(net, 2), "pnl": round(pnl, 2), "pct": round(100 * (net / h["cost_usd"] - 1), 3),
                   "cost_pct": cost, "strategy": h["strategy"], "why": why})


def equity(book: dict, prices: dict) -> float:
    return book["cash"] + sum(h["qty"] * (prices.get(c) or h["entry_px"]) for c, h in book["holdings"].items())


def run(force_decide: bool = False) -> dict:
    cfg = config()
    book = _load(BOOK, None) or {"pretend_money": True, "start_usd": cfg["start_usd"], "cash": cfg["start_usd"],
                                  "holdings": {}, "realized": 0.0, "started": _now().date().isoformat(), "history": []}
    ledger = _load(LEDGER, [])
    orgs = _load(ORGS, {}).get("coins", {})
    closed_day = (_now().date()).isoformat()      # a new UTC day means yesterday's bar has closed
    due = force_decide or book.get("decided_for") != closed_day
    if due:
        data = universe(cfg)
        prices = coinbase.tickers(sorted(set(data) | set(book["holdings"])))
        decide(cfg, data, orgs, book, ledger, prices)
        book["decided_for"] = closed_day
        book["universe"] = sorted(data)
    else:
        prices = coinbase.tickers(sorted(book["holdings"]))
    eq = equity(book, prices)
    for c, h in book["holdings"].items():
        p = prices.get(c) or h["entry_px"]
        h.update(price=p, value_usd=round(h["qty"] * p, 2), pnl_usd=round(h["qty"] * p - h["cost_usd"], 2))
    book.update(generated_at=_now().isoformat(timespec="seconds"), equity=round(eq, 2),
                fees={"fee_pct": cfg["fee_pct"], "slippage_pct": cfg["slippage_pct"]},
                recent_fills=ledger[-30:])        # for the dashboard, which reads only this file
    hist = book.setdefault("history", [])
    hist.append([book["generated_at"], round(eq, 2)])
    del hist[:-24 * 120]                           # about four months of hourly marks
    _save(BOOK, book)
    _save(LEDGER, ledger[-5000:])
    _save(ORGS, {"generated_at": book["generated_at"], "fee_pct": cfg["fee_pct"], "coins": orgs})
    return book
