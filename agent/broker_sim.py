"""Built-in paper simulator: pretend money, real prices, buys AND sells. No brokerage account needed.

This is the safety lock before any real money. It holds a small pretend balance (config.yaml -> sim),
fills orders at the latest market price the agent fetched, tracks each position's weight and profit,
books realised P/L on sells, and rewrites portfolio.md after every check so you can read it on your phone.

portfolio.json  -> the ledger (cash, positions, fills, realised P/L)
portfolio.md    -> human-readable snapshot, regenerated every check
"""
import json
import math
from datetime import date, datetime, time
from zoneinfo import ZoneInfo
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO = ROOT / "portfolio.json"
REPORT = ROOT / "portfolio.md"
ET = ZoneInfo("America/New_York")

# NYSE full-day closures. Update once a year.
HOLIDAYS = {
    "2026-09-07", "2026-11-26", "2026-12-25",
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31", "2027-06-18", "2027-07-05",
    "2027-09-06", "2027-11-25", "2027-12-24",
}
EARLY_CLOSE_1PM = {"2026-11-27", "2026-12-24", "2027-11-26"}

def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d.isoformat() not in HOLIDAYS

def close_time(d: date) -> time:
    return time(13, 0) if d.isoformat() in EARLY_CLOSE_1PM else time(16, 0)

def last_trading_day_of_week(d: date) -> bool:
    """True when no trading day remains between d and the weekend (Friday normally, Thursday before a holiday Friday)."""
    from datetime import timedelta
    return is_trading_day(d) and not any(is_trading_day(d + timedelta(days=i)) for i in range(1, 5 - d.weekday()))

def _px(v: float) -> float:
    """Round for display without destroying sub-cent assets.

    A memecoin trades at $0.000003. Rounding its price to two decimals makes it exactly zero, and
    every level computed from it becomes meaningless, so small numbers keep significant digits.
    """
    v = float(v)
    if v == 0:
        return 0.0
    return round(v, 2) if abs(v) >= 1 else float(f"{v:.8g}")

def _week_key(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"

class SimBroker:
    name = "sim"
    client = None  # run.py checks this to decide how to test market hours

    def __init__(self, env: dict, sim_cfg: dict | None = None,
                 portfolio_path=None, report_path=None, name: str | None = None):
        """portfolio_path lets a second sleeve keep its own books.

        The memecoin sleeve must not be able to spend the stock sleeve's money or corrupt its
        ledger, so it runs as a separate SimBroker over separate files with its own invariant.
        """
        sim_cfg = sim_cfg or {}
        self._pf = Path(portfolio_path) if portfolio_path else PORTFOLIO
        self._rp = Path(report_path) if report_path else REPORT
        if name:
            self.name = name
        self.start = float(sim_cfg.get("starting_cash", 400))
        self.deposit = float(sim_cfg.get("weekly_deposit", 0))
        self.prices: dict[str, float] = {}
        # Every market fill is this much worse than the quoted price (buys pay up, sells receive
        # less). Without it a round trip is free and the agent learns that churning costs nothing.
        # Standing limit orders set it to 0 for their own fill: they get the level they asked for.
        self.spread_pct = 0.0
        self.p = self._load()
        self._weekly_deposit()

    # ---- ledger -------------------------------------------------------------------------
    def _load(self) -> dict:
        if self._pf.exists():
            return json.loads(self._pf.read_text())
        today = datetime.now(ET).date()
        # A ledger created on a weekend belongs to the coming week, so starting_cash counts as that week's deposit.
        first_wk = today if today.weekday() < 5 else date.fromordinal(today.toordinal() + 7 - today.weekday())
        return {"cash": self.start, "deposited": self.start, "created": today.isoformat(),
                "last_deposit_week": _week_key(first_wk), "positions": {}, "fills": [], "realized_pnl": 0.0}

    def _save(self) -> None:
        self._pf.write_text(json.dumps(self.p, indent=2))

    def _weekly_deposit(self) -> None:
        """One deposit per NEW ISO week. Compares ordered (year, week) so a ledger stamped with the coming week
        (created on a weekend) is never re-credited, and a stale stamp is only advanced forward."""
        today = datetime.now(ET).date()
        wk = _week_key(today)
        def _ord(k: str) -> tuple[int, int]:
            y, w = str(k).split("-W"); return int(y), int(w)
        last = self.p.get("last_deposit_week") or wk
        if self.deposit > 0 and _ord(wk) > _ord(last):
            # Ledger arithmetic is kept EXACT (no per-step rounding): cash + cost basis must always equal
            # deposited + realised P/L, and safety.ledger_intact halts trading if it drifts past 5 cents.
            self.p["cash"] += self.deposit
            self.p["deposited"] += self.deposit
            self.p["fills"].append({"type": "deposit", "usd": self.deposit, "date": today.isoformat()})
        if _ord(wk) > _ord(last):
            self.p["last_deposit_week"] = wk
        self._save()

    def set_prices(self, px: dict) -> None:
        self.prices = {k: float(v["price"]) for k, v in px.items() if v.get("price")}

    def held_tickers(self) -> list[str]:
        return sorted(self.p["positions"])

    # ---- broker interface -----------------------------------------------------------------
    def market_open(self) -> bool:
        now = datetime.now(ET)
        if not is_trading_day(now.date()):
            return False
        return time(9, 30) <= now.time() < close_time(now.date())

    def cash(self) -> float:
        return round(self.p["cash"], 2)

    def equity(self) -> float:
        mv = sum(pos["qty"] * self.prices.get(s, pos["avg_cost"]) for s, pos in self.p["positions"].items())
        return round(self.p["cash"] + mv, 2)

    def positions(self) -> dict:
        eq = self.equity() or 1.0
        today = datetime.now(ET).date()
        out = {}
        for s, pos in self.p["positions"].items():
            price = self.prices.get(s, pos["avg_cost"])
            mv = pos["qty"] * price
            out[s] = {"qty": round(pos["qty"], 6), "avg_cost": _px(pos["avg_cost"]), "price": _px(price),
                      "market_value": round(mv, 2), "unrealized_plpc": round((price / pos["avg_cost"] - 1) * 100, 2),
                      "weight_pct": round(mv / eq * 100, 1),
                      "days_held": (today - date.fromisoformat(pos["opened"])).days,
                      # min_hold_days is enforced on this: adding to a position restarts the clock, so a fresh lot
                      # can't be flipped the same day just because the position is old
                      "days_since_buy": (today - date.fromisoformat(pos.get("last_buy") or pos["opened"])).days,
                      "tranches": int(pos.get("tranches", 1)),
                      # Positions bought before the minute-clock existed have no timestamp. Falling
                      # back to the DAY they were opened is what makes the intraday stop apply to
                      # them at all - otherwise the whole legacy book is silently exempt from it,
                      # which is exactly why nothing sold when the 30-minute rule went live.
                      # Measured from when the position was OPENED. Using the last add restarted
                      # the clock every time it averaged in, so a "30-minute" position could
                      # legally run 60 or 90 minutes by topping itself up.
                      "minutes_held": (round((datetime.now(ET).timestamp() - float(pos.get("opened_ts") or pos["last_buy_ts"])) / 60)
                                       if (pos.get("opened_ts") or pos.get("last_buy_ts"))
                                       else (today - date.fromisoformat(pos.get("last_buy") or pos["opened"])).days * 1440)}
        return out

    def summary(self) -> dict:
        eq = self.equity()
        dep = self.p["deposited"] or 1.0
        return {"cash": self.cash(), "equity": eq, "deposited": round(self.p["deposited"], 2),
                "total_return_pct": round((eq / dep - 1) * 100, 2), "realized_pnl": round(self.p["realized_pnl"], 2),
                "unrealized_pnl": round(eq - self.p["cash"] - sum(p["qty"] * p["avg_cost"] for p in self.p["positions"].values()), 2)}

    def buy_notional(self, symbol: str, usd: float) -> dict:
        rec = {"symbol": symbol, "notional": round(usd, 2), "side": "buy"}
        price = self.prices.get(symbol)
        if not price:
            rec["status"] = "rejected_no_price"; return rec
        usd = round(usd, 2)
        if usd > self.p["cash"]:                      # never overdraw: floor to the cent actually available
            usd = math.floor(self.p["cash"] * 100 + 1e-9) / 100
        if usd <= 0:
            rec["status"] = "rejected_no_cash"; return rec
        fill = round(price * (1 + self.spread_pct / 100), 6)     # you buy at the offer
        qty = usd / fill
        today = datetime.now(ET).date().isoformat()
        pos = self.p["positions"].get(symbol)
        if pos and pos["qty"] >= 1e-6:
            total_cost = pos["qty"] * pos["avg_cost"] + usd
            pos["qty"] += qty
            pos["avg_cost"] = total_cost / pos["qty"]
            pos["last_buy"] = today
            pos["last_buy_ts"] = int(datetime.now(ET).timestamp())
            pos.setdefault("opened_ts", pos["last_buy_ts"])            # never moved by an add
            pos["tranches"] = int(pos.get("tranches", 1)) + 1     # how many times it has averaged in
        else:
            self.p["positions"][symbol] = {"qty": qty, "avg_cost": fill, "opened": today,
                                           "last_buy": today, "tranches": 1,
                                           "last_buy_ts": int(datetime.now(ET).timestamp()),
                                           "opened_ts": int(datetime.now(ET).timestamp())}
        self.p["cash"] -= usd                          # exact, see _weekly_deposit
        rec.update({"status": "filled", "qty": round(qty, 6), "price": _px(fill), "notional": usd})
        self.p["fills"].append({**rec, "type": "buy", "date": datetime.now(ET).strftime("%Y-%m-%d %H:%M")})
        self._save()
        return rec

    def sell_qty(self, symbol: str, qty: float) -> dict:
        rec = {"symbol": symbol, "side": "sell", "qty": round(qty, 6)}
        pos = self.p["positions"].get(symbol)
        price = self.prices.get(symbol)
        if not pos:
            rec["status"] = "rejected_not_held"; return rec
        if not price:
            rec["status"] = "rejected_no_price"; return rec
        qty = min(qty, pos["qty"])
        avg = pos["avg_cost"]                                    # kept: the position may be deleted below
        if pos["qty"] - qty < 1e-6:   # full close: positions() reports qty at 6 dp, so a 100% sell arrives a hair short
            qty = pos["qty"]
        fill = round(price * (1 - self.spread_pct / 100), 6)     # you sell at the bid
        proceeds = qty * fill
        realized = (fill - pos["avg_cost"]) * qty
        pos["qty"] -= qty
        if pos["qty"] < 1e-9:
            del self.p["positions"][symbol]
        self.p["cash"] += proceeds                     # exact: rounding cash and P/L separately drifted the
        self.p["realized_pnl"] += realized             # ledger ~1c per sell and eventually tripped the halt
        rec.update({"status": "filled", "qty": round(qty, 6), "price": _px(fill), "proceeds": round(proceeds, 2),
                    "realized_pnl": round(realized, 2), "realized_pct": round((fill / avg - 1) * 100, 2)})
        self.p["fills"].append({**rec, "type": "sell", "date": datetime.now(ET).strftime("%Y-%m-%d %H:%M")})
        self._save()
        return rec

    # ---- report ---------------------------------------------------------------------------
    def write_report(self) -> None:
        s = self.summary()
        now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
        lines = [f"# Pretend portfolio — {now}", "",
                 f"**Equity ${s['equity']:.2f}** on ${s['deposited']:.2f} put in → **{s['total_return_pct']:+.2f}%**  ",
                 f"Cash ${s['cash']:.2f} · Unrealised {s['unrealized_pnl']:+.2f} · Realised {s['realized_pnl']:+.2f}", "",
                 "| Ticker | Weight | Value | Avg cost | Price | P/L | Held |", "|---|---:|---:|---:|---:|---:|---:|"]
        for sym, p in sorted(self.positions().items(), key=lambda kv: -kv[1]["market_value"]):
            fmt = (lambda v: f"${v:,.2f}") if p["price"] >= 1 else (lambda v: f"${v:.8g}")
            lines.append(f"| {sym} | {p['weight_pct']:.1f}% | ${p['market_value']:.2f} | {fmt(p['avg_cost'])} | {fmt(p['price'])} | {p['unrealized_plpc']:+.2f}% | {p['days_held']}d |")
        if not self.p["positions"]:
            lines.append("| — | 100% cash | | | | | |")
        lines += ["", "## Last fills", ""]
        for f in self.p["fills"][-12:][::-1]:
            if f.get("type") == "deposit":
                lines.append(f"- {f['date']} deposit +${f['usd']:.2f}")
            elif f.get("type") == "sell":
                lines.append(f"- {f['date']} SELL {f['qty']} {f['symbol']} @ ${f['price']} → ${f['proceeds']:.2f} ({f['realized_pct']:+.2f}%)")
            else:
                lines.append(f"- {f['date']} BUY ${f['notional']:.2f} {f['symbol']} @ ${f['price']}")
        self._rp.write_text("\n".join(lines) + "\n")
