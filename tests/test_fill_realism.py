"""Standing orders fill only at prices that traded; implausible levels never reach the book.

Regression for 2026-09-21: the model placed an AMD stop_loss at 2438.48 against a 609.62 quote. Every
bar's low was under it, so it fired on the first bar and the ledger booked a sale at $2,437.26
(+$7,493, +299.72%) that never traded - and learn.py then folded that sale into 27 earlier AMD buys.

Plain python3 (prints PASS/FAIL per check, exits 1 on any failure), also collectable by pytest:

    python3 tests/test_fill_realism.py

Every order book and journal lives in a temp directory; nothing here touches the repo's ledger, the
network, a broker or the model.
"""
import json
import random
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from agent import learn, triggers  # noqa: E402

ET = ZoneInfo("America/New_York")
NOW = datetime(2026, 9, 21, 11, 46, tzinfo=ET)
T0 = int(NOW.timestamp())
SLIP = 0.05                                      # config.yaml trigger_slippage_pct
AMD = {"AMD": {"price": 609.62}}
FAILS: list[str] = []
CHECKS = 0


def check(name, ok, detail=""):
    global CHECKS
    CHECKS += 1
    if not ok:
        FAILS.append(name)
    print(("PASS  " if ok else "FAIL  ") + name + (f"  ({detail})" if detail and not ok else ""))
    return bool(ok)


def fresh_book():
    triggers.FILE = Path(tempfile.mkdtemp(prefix="test_fill_")) / "triggers.json"


def stored(ticker, kind, price, **kw):
    """An order written straight into the book, bypassing placement - to test evaluate() on its own."""
    o = {"id": f"{ticker}-{kind}-{price}", "ticker": ticker, "kind": kind, "price": price, "status": "working",
         "created": "2026-09-21 09:30", "created_ts": 0, "why": "", "evidence": "x", "signals": [],
         "good_until": "2099-12-31", "pct_of_position": 100, "usd": 1000}
    o.update(kw)
    return o


def fire(order, bars, px=None):
    fresh_book()
    triggers._save({"orders": [order]})
    fires, _ = triggers.evaluate(NOW, px or {}, {order["ticker"]: bars}, {order["ticker"]}, SLIP)
    return fires[0] if fires else None


def bar(t, o, h, l, c):
    return {"t": T0 + t, "o": o, "h": h, "l": l, "c": c}


def near(a, b, tol=1e-6):
    return a is not None and b is not None and abs(float(a) - float(b)) <= tol


def _group(fn):
    """Run one group; under pytest a failing check in it fails the test."""
    before = len(FAILS)
    fn()
    assert len(FAILS) == before, f"{len(FAILS) - before} check(s) failed: {FAILS[before:]}"


# --------------------------------------------------------------------------------------------------
# placement (triggers.place -> _clean)
# --------------------------------------------------------------------------------------------------
def _placement():
    held, allowed = {"AMD"}, {"AMD"}

    def place(price, kind="stop_loss", px=AMD, signals=("momentum", "news", "risk_management"), **kw):
        fresh_book()
        raw = {"ticker": "AMD", "kind": kind, "price": price, "pct_of_position": 100, "usd": 1000,
               "trail_pct": 0, "signals": list(signals), "evidence": "ATR 4.18%, protect new position",
               "why": "Protective stop on new AMD position"}
        raw.update(kw)
        return triggers.place([raw], NOW, held, allowed, px)

    placed, rej = place(2438.48)
    check("the 2026-09-21 AMD stop_loss at 2438.48 (4.0x the 609.62 quote) is rejected", not placed, str(placed))
    check("  ...and the rejection says why (the level vs the quote)", bool(rej) and "4.00x" in rej[0], str(rej))
    placed, rej = place(600.00)
    check("a sane stop_loss at 600.00 under a 609.62 quote is accepted", len(placed) == 1, str(rej))
    placed, rej = place(612.00, signals=("risk_management", "auto_bracket"))
    check("an auto_bracket break-even stop at 612.00 (entry) above a 609.62 quote is accepted",
          len(placed) == 1, str(rej))
    placed, rej = place(612.00)
    check("the same stop at 612.00 NOT tagged auto_bracket (at/above the quote) is rejected", not placed, str(placed))
    placed, rej = place(600.00, px={})
    check("a stop_loss with no quote to check it against is rejected", not placed, str(placed))
    placed, rej = place(600.00, kind="buy_limit", px={})
    check("a buy_limit with no quote is rejected", not placed, str(placed))
    placed, rej = place(615.00, kind="buy_limit")
    check("a buy_limit above the quote (it would fill at once, not on a dip) is rejected", not placed, str(placed))
    placed, rej = place(600.00, kind="take_profit")
    check("a take_profit below the quote is rejected", not placed, str(placed))
    placed, rej = place(600.00, kind="buy_stop")
    check("a buy_stop below the quote is rejected", not placed, str(placed))
    placed, rej = place(609.62 * 1.6, kind="take_profit")
    check("a take_profit at 1.6x the quote (outside the 0.5-1.5x band) is rejected", not placed, str(placed))
    placed, rej = place(609.62 * 0.45, kind="buy_limit")
    check("a buy_limit at 0.45x the quote is rejected", not placed, str(placed))
    placed, rej = place(0, kind="trailing_stop", trail_pct=2.0)
    check("a trailing_stop is still accepted (its level comes from the quote)", len(placed) == 1, str(rej))


def test_placement():
    _group(_placement)


# --------------------------------------------------------------------------------------------------
# fills (triggers.evaluate)
# --------------------------------------------------------------------------------------------------
def _fills():
    s = SLIP / 100
    # the incident itself: a stop 4x over the market fires on the first bar, but at a traded price
    f = fire(stored("AMD", "stop_loss", 2438.48), [bar(300, 609.70, 609.90, 609.40, 609.62)])
    check("AMD stop at 2438.48 against a ~609.6 bar fills at the bar's open, not the level",
          f and near(f["fill_price"], triggers.px_round(609.70 * (1 - s)), 1e-4), str(f and f["fill_price"]))
    f = fire(stored("X", "stop_loss", 100.0), [bar(0, 95.0, 96.0, 94.0, 95.5)])
    check("gap-through stop_loss (level 100, bar opens 95) fills at the open less slippage",
          f and near(f["fill_price"], triggers.px_round(95.0 * (1 - s)), 1e-4), str(f and f["fill_price"]))
    f = fire(stored("X", "stop_loss", 100.0), [bar(0, 101.0, 101.5, 99.5, 100.2)])
    check("stop_loss inside the bar fills at its level less slippage",
          f and near(f["fill_price"], triggers.px_round(100.0 * (1 - s)), 1e-4), str(f and f["fill_price"]))
    f = fire(stored("X", "buy_stop", 100.0), [bar(0, 103.0, 104.0, 102.5, 103.5)])
    check("gap-through buy_stop (level 100, bar opens 103) pays the open plus slippage",
          f and near(f["fill_price"], triggers.px_round(103.0 * (1 + s)), 1e-4), str(f and f["fill_price"]))
    f = fire(stored("X", "take_profit", 105.0), [bar(0, 107.0, 108.0, 106.5, 107.5)])
    check("take_profit gapped above (level 105, bar 106.5-108) is clamped into the bar: 106.5",
          f and near(f["fill_price"], 106.5), str(f and f["fill_price"]))
    f = fire(stored("X", "take_profit", 105.0), [bar(0, 104.0, 105.5, 103.8, 105.2)])
    check("take_profit reached inside the bar fills at its level", f and near(f["fill_price"], 105.0),
          str(f and f["fill_price"]))
    f = fire(stored("X", "buy_limit", 95.0), [bar(0, 93.0, 94.0, 92.0, 93.5)])
    check("buy_limit gapped below (level 95, bar 92-94) is clamped into the bar: 94.0",
          f and near(f["fill_price"], 94.0), str(f and f["fill_price"]))
    f = fire(stored("X", "buy_limit", 95.0), [bar(0, 96.0, 96.5, 94.5, 95.8)])
    check("buy_limit reached inside the bar fills at its level", f and near(f["fill_price"], 95.0),
          str(f and f["fill_price"]))
    # trailing stop, 2% under a high-water mark of 100: the stop is 98 going into the first bar
    trail = stored("X", "trailing_stop", 98.0, trail_pct=2.0, high_water=100.0)
    f = fire(dict(trail), [bar(0, 99.5, 100.5, 99.2, 99.8), bar(300, 95.0, 96.0, 94.5, 95.5)])
    check("trailing stop gapped through (stop 98.49 live, next bar opens 95) fills at the open",
          f and near(f["fill_price"], triggers.px_round(95.0 * (1 - s)), 1e-4) and f["fired_ts"] == T0 + 300,
          str(f and (f["fill_price"], f["fired_ts"])))
    f = fire(dict(trail), [bar(0, 100.0, 101.0, 97.0, 97.5)])
    check("trailing stop hit inside the bar fills at the raised stop (101 x 0.98) less slippage",
          f and near(f["fill_price"], triggers.px_round(98.98 * (1 - s)), 1e-4), str(f and f["fill_price"]))
    f = fire(stored("X", "stop_loss", 100.0), [{"t": T0, "h": 96.0, "l": 94.0, "c": 95.5}])
    check("a bar recorded without an open falls back to its close (95.5)",
          f and near(f["fill_price"], triggers.px_round(95.5 * (1 - s)), 1e-4), str(f and f["fill_price"]))
    # backstop in run._at_price
    pf = getattr(triggers, "plausible_fill", None)
    check("plausible_fill refuses the 2437.26 AMD fill against a 609.62 quote",
          pf is not None and pf(2437.26, 609.62) is False, "missing" if pf is None else "")
    check("plausible_fill accepts 609.32 against 609.62, and anything when there is no quote",
          pf is not None and pf(609.32, 609.62) and pf(609.32, None) and pf(609.32, 0), "missing" if pf is None else "")
    check("plausible_fill: 20% is the edge (119.9 ok, 120.1 refused against 100)",
          pf is not None and pf(119.9, 100) and not pf(120.1, 100) and pf(80.1, 100) and not pf(79.9, 100))


def test_fills():
    _group(_fills)


def _invariant():
    """Random orders at random (often absurd) levels against random bars: every fill lies inside the
    bar that fired it, give or take the configured slippage and px_round's own rounding."""
    rng = random.Random(20260921)
    s = SLIP / 100
    kinds = ["buy_limit", "buy_stop", "take_profit", "stop_loss", "trailing_stop"]
    bad, fired, n = [], 0, 0

    def tol(v):
        return 1e-4 if abs(v) >= 1 else abs(v) * 1e-7 + 1e-15

    for batch in range(10):
        orders, bars = [], {}
        for i in range(200):
            t = f"T{batch}_{i}"
            base = rng.choice([rng.uniform(0.2, 1.0), rng.uniform(1, 50), rng.uniform(50, 3000)])
            kind = rng.choice(kinds)
            level = triggers.px_round(base * rng.choice([rng.uniform(0.2, 5.0), rng.uniform(0.97, 1.03)]))
            extra = {}
            if kind == "trailing_stop":
                extra = {"trail_pct": round(rng.uniform(0.5, 10), 2), "high_water": triggers.px_round(base * rng.uniform(0.8, 1.3))}
                level = 0.0
            orders.append(stored(t, kind, level, **extra))
            seq, p = [], base
            for k in range(rng.randint(1, 5)):
                o = p * (1 + rng.gauss(0, 0.02)) * (rng.choice([1, 1, 1, 0.9, 1.1]))    # sometimes a gap
                c = o * (1 + rng.gauss(0, 0.01))
                h = max(o, c) * (1 + abs(rng.gauss(0, 0.005)))
                lo = min(o, c) * (1 - abs(rng.gauss(0, 0.005)))
                r = triggers.px_round
                seq.append({"t": T0 + 300 * k, "o": r(o), "h": r(h), "l": r(lo), "c": r(c)})
                p = c
            bars[t] = seq
            n += 1
        fresh_book()
        triggers._save({"orders": orders})
        fires, _ = triggers.evaluate(NOW, {}, bars, set(bars), SLIP)
        for f in fires:
            fired += 1
            b = next(x for x in bars[f["ticker"]] if x["t"] == f["fired_ts"])
            lo, hi = b["l"] * (1 - s), b["h"] * (1 + s)
            if not (lo - tol(lo) <= f["fill_price"] <= hi + tol(hi)):
                bad.append((f["kind"], f["price"], f["fill_price"], b["l"], b["h"]))
    check(f"invariant: {fired} fills from {n} random orders all inside [low x (1-slip), high x (1+slip)] "
          f"of the bar that fired them", fired > 100 and not bad,
          f"{len(bad)} outside, e.g. (kind, level, fill, bar low, bar high) {bad[:3]}")


def test_invariant():
    _group(_invariant)


# --------------------------------------------------------------------------------------------------
# learn.py: each buy is graded on its own position's sells
# --------------------------------------------------------------------------------------------------
def _learn_window():
    tmp = Path(tempfile.mkdtemp(prefix="test_learn_"))
    learn.JOURNAL = tmp / "journal.json"
    learn.LESSONS = tmp / "lessons.md"

    def b(sym, ts, qty=1.0):
        return {"symbol": sym, "side": "buy", "ts": ts, "date": "2026-09-21", "qty": qty,
                "notional": 100.0 * qty, "price": 100.0, "entry_price": 100.0, "signals": ["momentum"]}

    def sl(sym, ts, pct, proceeds, qty=1.0):
        return {"symbol": sym, "side": "sell", "ts": ts, "date": "2026-09-21", "qty": qty,
                "realized_pct": pct, "realized_pnl": proceeds - 100.0 * qty, "proceeds": proceeds,
                "signals": ["momentum"]}

    rows = [
        b("AMD", 1000), sl("AMD", 1100, -1.0, 99.0),                 # position 1: -1%
        b("AMD", 1100), sl("AMD", 1300, 50.0, 150.0),                # position 2 opens in the same second
        b("MSFT", 2000), sl("MSFT", 2050, 2.0, 51.0, qty=0.5),       # position 3: partial exit...
        b("MSFT", 2100),                                             # ...an ADD (still open) ...
        sl("MSFT", 2200, -1.0, 148.0, qty=1.5),                      # ...and the close
        b("MSFT", 3000), sl("MSFT", 3100, 10.0, 110.0),              # position 4
    ]
    learn.JOURNAL.write_text(json.dumps(rows))
    learn.score({}, set())                                           # nothing held: every buy is closed
    got = [r.get("ret_final") for r in json.loads(learn.JOURNAL.read_text()) if r["side"] == "buy"]
    want_msft1 = round((2.0 * 51 - 1.0 * 148) / (51 + 148), 2)
    check("a later AMD position's +50% sell does not leak into an earlier AMD buy (graded -1.0)",
          got[0] == -1.0, f"got {got[0]}")
    check("the re-opening AMD buy is graded on its own sell only (+50.0), even sharing a timestamp",
          got[1] == 50.0, f"got {got[1]}")
    check(f"MSFT opening buy is graded on its partial and closing sells ({want_msft1}) but not the next position",
          got[2] == want_msft1, f"got {got[2]}")
    check("MSFT add (a buy into an open position) is graded on the sells after it (-1.0)",
          got[3] == -1.0, f"got {got[3]}")
    check("MSFT's next position is graded on its own sell (+10.0)", got[4] == 10.0, f"got {got[4]}")


def test_learn_window():
    _group(_learn_window)


def main():
    for name, fn in (("placement", _placement), ("fills", _fills), ("invariant", _invariant),
                     ("learn window", _learn_window)):
        print(f"--- {name}")
        try:
            fn()
        except Exception as e:  # noqa: BLE001 - report a crash as a failed check and keep going
            check(f"{name} ran without raising", False, f"{type(e).__name__}: {e}")
    print(f"\n{CHECKS - len(FAILS)}/{CHECKS} checks passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
