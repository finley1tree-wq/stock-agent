#!/usr/bin/env python3
"""Unit checks for the per-name spread cost model and the simulator's fills.

Plain python3, no pytest:   python3 tests/test_costs.py
Prints PASS/FAIL per check and exits 1 if anything failed.

What is pinned down here (the three faults fixed after commit 33498d1):
  * prices.spread_pct tiers on DOLLARS a day (avg_volume * price), not shares, with a half-cent
    tick floor (0.5 / price, capped at 2.0) and never less than the flat default.
  * SimBroker._spread returns 0 when spread_pct is 0 - that zero is how run._at_price says a
    standing order (stop, take-profit, dip/limit entry) fills at its own level.
  * Market fills still pay the per-name spread.

Isolation: every broker built here writes its ledger to a fresh temp directory, never to the repo's
portfolio.json / portfolio.md. As a belt-and-braces check the test hashes the repo's ledger files
before and after and fails if any of them changed. run.make_broker is deliberately NOT used: it
constructs SimBroker on the default ledger path.
"""
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import prices                      # noqa: E402
from agent.broker_sim import SimBroker        # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []
INFO: list[str] = []
TMP_DIRS: list[str] = []

# Real-ish quotes from 2026-09-14: (price, avg shares/day) and the expected ONE-WAY cost in percent.
REAL = {
    "HLI":  (137.82, 876_474,    0.04),    # ~$120.8M/day: was charged 0.40 under the share tiers
    "TPL":  (365.27, 373_490,    0.04),    # ~$136.4M/day: likewise
    "MAIA": (1.39,   500_460,    0.50),    # ~$0.70M/day: bottom tier; tick floor 0.36 is below it
    "FLD":  (0.5253, 441_130,    0.9518),  # ~$0.23M/day: tick floor 0.5/0.5253 dominates the 0.50 tier
    "AAPL": (333.08, 53_820_953, 0.02),    # ~$17.9B/day
    "IBM":  (249.09, 4_928_220,  0.02),    # ~$1.23B/day
}
LEDGER_FILES = ("portfolio.json", "portfolio.md", "state.json", "triggers.json", "journal.json",
                "decisions.json", "instruments.json", "log.md")


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail and not ok else ""))
    return bool(ok)


def close(a, b, tol=1e-9) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol * max(1.0, abs(float(a)), abs(float(b)))
    except (TypeError, ValueError):
        return False


def quotes() -> dict:
    return {s: {"price": p, "avg_volume": v} for s, (p, v, _) in REAL.items()}


def new_broker(spread: float, px: dict | None = None, cash: float = 25_000.0) -> SimBroker:
    d = tempfile.mkdtemp(prefix="test_costs_")
    TMP_DIRS.append(d)
    b = SimBroker({}, {"starting_cash": cash, "weekly_deposit": 0},
                  portfolio_path=Path(d) / "portfolio.json", report_path=Path(d) / "portfolio.md")
    assert Path(b._pf).parent == Path(d), "broker ledger is not in the temp dir"
    b.spread_pct = spread
    if px is not None:
        b.set_prices(px)
    return b


def repo_ledger_hashes() -> dict:
    out = {}
    for f in LEDGER_FILES:
        p = ROOT / f
        out[f] = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
    data = ROOT / "site" / "data"
    if data.is_dir():
        for p in sorted(data.rglob("*")):
            if p.is_file():
                out[str(p.relative_to(ROOT))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


# --------------------------------------------------------------------------------------------------
# prices.spread_pct
# --------------------------------------------------------------------------------------------------
def test_tier_boundaries():
    # price 100 so shares * price is exact in binary floating point; tick floor at $100 is 0.005,
    # below every tier, so only the tier decides.
    cases = [
        ("1e9 exactly",   10_000_000, 0.02), ("1e9 just above", 10_000_001, 0.02), ("1e9 just below", 9_999_999, 0.04),
        ("50e6 exactly",  500_000,    0.04), ("50e6 just above", 500_001,   0.04), ("50e6 just below", 499_999,   0.10),
        ("10e6 exactly",  100_000,    0.10), ("10e6 just above", 100_001,   0.10), ("10e6 just below", 99_999,    0.25),
        ("2e6 exactly",   20_000,     0.25), ("2e6 just above",  20_001,    0.25), ("2e6 just below",  19_999,    0.50),
    ]
    for label, vol, want in cases:
        for default in (0.0, 0.02):
            got = prices.spread_pct("X", {"X": {"price": 100.0, "avg_volume": vol}}, default=default)
            check(f"spread tier {label} (${vol * 100:,.0f}/day, default {default}) -> {want}",
                  close(got, want), f"got {got}")
    # a cent either side of the boundary, not just a share
    got_lo = prices.spread_pct("X", {"X": {"price": 99.99, "avg_volume": 10_000_000}})
    got_hi = prices.spread_pct("X", {"X": {"price": 100.01, "avg_volume": 10_000_000}})
    check("spread tier 1e9 decided by dollars: $99.99 x 10M shares -> 0.04", close(got_lo, 0.04), f"got {got_lo}")
    check("spread tier 1e9 decided by dollars: $100.01 x 10M shares -> 0.02", close(got_hi, 0.02), f"got {got_hi}")


def test_real_names():
    px = quotes()
    for sym, (p, v, want) in REAL.items():
        got = prices.spread_pct(sym, px)
        check(f"spread {sym} ${p} x {v:,} (${p * v / 1e6:,.1f}M/day) -> {want}", close(got, want), f"got {got}")
    # the regression itself: same share-ish volume, wildly different dollars, must NOT cost the same
    hli, tpl, maia = (prices.spread_pct(s, px) for s in ("HLI", "TPL", "MAIA"))
    check("spread HLI and TPL are >= 10x cheaper than MAIA (share-volume tiering is gone)",
          hli * 10 <= maia and tpl * 10 <= maia, f"HLI {hli} TPL {tpl} MAIA {maia}")
    check("spread HLI is not the old 0.40 share-tier charge", not close(hli, 0.40), f"got {hli}")


def test_tick_floor():
    big = 1e10  # shares: guarantees top dollar tier (0.02) at every price used below
    cases = [
        (0.5253, 0.9518),   # FLD-like price, even with enormous volume
        (0.50,   1.0),
        (1.39,   0.3597),   # 0.5/1.39 = 0.35971 -> 4dp
        (5.00,   0.10),     # the floor applies above the old $5 cut-off too
        (10.00,  0.05),
        (25.00,  0.02),     # 0.5/25 == top tier
        (0.25,   2.0),      # exactly at the cap
        (0.20,   2.0),      # would be 2.5: capped
        (0.01,   2.0),      # would be 50: capped
        (0.000003, 2.0),    # memecoin-sized: capped, not astronomical
    ]
    for price, want in cases:
        got = prices.spread_pct("X", {"X": {"price": price, "avg_volume": big}})
        check(f"tick floor ${price} with top-tier volume -> {want}", close(got, want), f"got {got}")
    got = prices.spread_pct("X", {"X": {"price": 0.10, "avg_volume": 100}})
    check("tick floor capped at 2.0 even in the bottom tier ($0.10 x 100 shares)", close(got, 2.0), f"got {got}")
    # the floor lifts the tier only when it is larger than the tier: $1.39 bottom tier stays 0.50
    got = prices.spread_pct("X", {"X": {"price": 1.39, "avg_volume": 500_460}})
    check("tick floor does not lower a higher tier (MAIA stays 0.50, floor 0.36)", close(got, 0.50), f"got {got}")
    # default above the cap wins
    got = prices.spread_pct("X", {"X": {"price": 0.01, "avg_volume": big}}, default=3.0)
    check("default above the 2.0 cap is still the floor (3.0)", close(got, 3.0), f"got {got}")


def test_missing_inputs():
    d = 0.07  # a default no tier or floor could produce by coincidence at these inputs
    cases = [
        ("missing volume",            {"X": {"price": 137.82}}),
        ("missing price",             {"X": {"avg_volume": 876_474}}),
        ("price None",                {"X": {"price": None, "avg_volume": 876_474}}),
        ("volume None",               {"X": {"price": 137.82, "avg_volume": None}}),
        ("price 0",                   {"X": {"price": 0, "avg_volume": 876_474}}),
        ("volume 0 and no 'volume'",  {"X": {"price": 137.82, "avg_volume": 0}}),
        ("negative volume",           {"X": {"price": 137.82, "avg_volume": -5}}),
        ("negative price",            {"X": {"price": -1.0, "avg_volume": 876_474}}),
        ("non-numeric volume",        {"X": {"price": 137.82, "avg_volume": "n/a"}}),
        ("non-numeric price",         {"X": {"price": "n/a", "avg_volume": 876_474}}),
        ("quote is None",             {"X": None}),
        ("empty quote",               {"X": {}}),
        ("ticker absent",             {"Y": {"price": 137.82, "avg_volume": 876_474}}),
        ("empty px map",              {}),
        ("px None",                   None),
    ]
    for label, px in cases:
        try:
            got = prices.spread_pct("X", px, default=d)
            check(f"spread {label} -> default", close(got, d), f"got {got}")
        except Exception as e:  # noqa: BLE001
            check(f"spread {label} -> default", False, f"raised {type(e).__name__}: {e}")
    check("spread default argument is 0.02 when not given", close(prices.spread_pct("X", None), 0.02),
          f"got {prices.spread_pct('X', None)}")
    got = prices.spread_pct("X", {"X": {"price": "137.82", "avg_volume": "876474"}})
    check("spread numeric strings are parsed (HLI as strings -> 0.04)", close(got, 0.04), f"got {got}")


def test_never_below_default():
    prices_ = (0.000003, 0.01, 0.25, 0.5253, 1.39, 4.99, 5.0, 25.0, 100.0, 137.82, 365.27, 5000.0)
    vols = (1, 100, 19_999, 20_000, 441_130, 876_474, 4_928_220, 53_820_953, 1e10)
    defaults = (0.0, 0.02, 0.05, 0.3, 0.75, 1.0, 3.0)
    bad = []
    for p in prices_:
        for v in vols:
            for d in defaults:
                got = prices.spread_pct("X", {"X": {"price": p, "avg_volume": v}}, default=d)
                if got < d - 1e-12 or got > max(2.0, d) + 1e-12:
                    bad.append((p, v, d, got))
    check(f"spread never below default and never above max(2.0, default) "
          f"({len(prices_) * len(vols) * len(defaults)} combos)", not bad, f"violations {bad[:5]}")
    got = prices.spread_pct("AAPL", quotes(), default=0.75)
    check("spread default 0.75 (memecoin-style) lifts AAPL's 0.02 to 0.75", close(got, 0.75), f"got {got}")


def test_volume_key_fallback():
    got = prices.spread_pct("X", {"X": {"price": 100.0, "volume": 500_000}})
    check("'volume' key used when avg_volume absent ($50M -> 0.04)", close(got, 0.04), f"got {got}")
    got = prices.spread_pct("X", {"X": {"price": 100.0, "avg_volume": 0, "volume": 20_000}})
    check("'volume' key used when avg_volume is 0 ($2M -> 0.25)", close(got, 0.25), f"got {got}")
    got = prices.spread_pct("X", {"X": {"price": 100.0, "avg_volume": None, "volume": 99_999}})
    check("'volume' key used when avg_volume is None ($9.9999M -> 0.25)", close(got, 0.25), f"got {got}")
    got = prices.spread_pct("X", {"X": {"price": 100.0, "avg_volume": 10_000_000, "volume": 1}})
    check("avg_volume takes precedence over 'volume' when both present", close(got, 0.02), f"got {got}")


def probe_nan():
    """Informational only: NaN is not 'unknown' to the `<= 0` guard. snapshot() cannot produce it
    today (int(NaN) raises and is caught there), so this is reported, not failed."""
    for label, q in (("NaN volume", {"price": 100.0, "avg_volume": float("nan")}),
                     ("NaN price", {"price": float("nan"), "avg_volume": 1_000_000})):
        try:
            got = prices.spread_pct("X", {"X": q}, default=0.02)
            INFO.append(f"{label}: returned {got}")
        except Exception as e:  # noqa: BLE001
            INFO.append(f"{label}: raised {type(e).__name__} (would propagate out of buy_notional/sell_qty)")


# --------------------------------------------------------------------------------------------------
# SimBroker fills
# --------------------------------------------------------------------------------------------------
def test_market_buy():
    for sym, (p, _, sp) in REAL.items():
        b = new_broker(0.02, quotes())
        rec = b.buy_notional(sym, 1000.0)
        want = round(p * (1 + sp / 100), 6)
        pos = b.p["positions"].get(sym, {})
        ok = (rec.get("status") == "filled" and close(pos.get("avg_cost"), want)
              and close(rec.get("qty"), round(1000.0 / want, 6), 1e-9) and close(b.p["cash"], 24_000.0))
        check(f"market buy {sym} at spread_pct 0.02 fills at price x (1 + {sp}/100) = {want}", ok,
              f"rec {rec} avg_cost {pos.get('avg_cost')}")
    b = new_broker(0.02, quotes())
    b.buy_notional("HLI", 1000.0)
    check("market buy HLI pays 4bp, not the old 40bp",
          close(b.p["positions"]["HLI"]["avg_cost"] / 137.82 - 1, 0.0004, 1e-6),
          f"avg_cost {b.p['positions']['HLI']['avg_cost']}")


def test_market_sell():
    for sym, (p, _, sp) in REAL.items():
        b = new_broker(0.02, quotes())
        b.buy_notional(sym, 1000.0)
        qty = b.p["positions"][sym]["qty"]
        avg = b.p["positions"][sym]["avg_cost"]           # whatever the entry cost; only the sell is judged here
        cash0 = b.p["cash"]
        rec = b.sell_qty(sym, qty)
        want = round(p * (1 - sp / 100), 6)
        got_fill = (b.p["cash"] - cash0) / qty
        ok = (rec.get("status") == "filled" and sym not in b.p["positions"]
              and close(got_fill, want, 1e-9) and close(b.p["realized_pnl"], (want - avg) * qty, 1e-9))
        check(f"market sell {sym} at spread_pct 0.02 fills at the bid price x (1 - {sp}/100) = {want}", ok,
              f"rec {rec} implied fill {got_fill}")


def test_level_fills_zero_spread():
    for sym, (p, _, _) in REAL.items():
        b = new_broker(0.0, quotes())
        rec_b = b.buy_notional(sym, 1000.0)
        pos = b.p["positions"].get(sym, {})
        check(f"spread_pct 0.0 buy {sym} fills exactly at {p} (per-name model bypassed)",
              rec_b.get("status") == "filled" and pos.get("avg_cost") == p, f"avg_cost {pos.get('avg_cost')}")
        qty = pos.get("qty", 0)
        cash0 = b.p["cash"]
        rec_s = b.sell_qty(sym, qty)
        got_fill = (b.p["cash"] - cash0) / qty if qty else None
        check(f"spread_pct 0.0 sell {sym} fills exactly at {p}; round trip realises 0",
              rec_s.get("status") == "filled" and close(got_fill, p, 1e-12) and abs(b.p["realized_pnl"]) < 1e-9,
              f"implied fill {got_fill} realized {b.p['realized_pnl']}")
    b = new_broker(0.0, quotes())
    check("_spread returns 0.0 for every quoted name when spread_pct is 0",
          all(b._spread(s) == 0.0 for s in REAL), str({s: b._spread(s) for s in REAL}))
    b.spread_pct = None
    check("_spread returns 0.0 when spread_pct is None (falsy)", b._spread("FLD") == 0.0, str(b._spread("FLD")))


def test_at_price():
    try:
        from agent import run
    except Exception as e:  # noqa: BLE001
        check("import agent.run for _at_price", False, f"{type(e).__name__}: {e}")
        return
    # buy_limit / dip entry: level below market, market-time spread must not apply
    b = new_broker(0.02, quotes())
    seen = {}
    def buy():
        seen["spread_inside"] = b.spread_pct
        seen["price_inside"] = b.prices.get("HLI")
        return b.buy_notional("HLI", 1000.0)
    rec = run._at_price(b, "HLI", 135.0, buy)
    check("_at_price buy fills exactly at the level (135.0)",
          rec.get("status") == "filled" and b.p["positions"]["HLI"]["avg_cost"] == 135.0,
          f"rec {rec} avg_cost {b.p['positions'].get('HLI', {}).get('avg_cost')}")
    check("_at_price sets spread_pct 0 and the level price during the fill",
          seen.get("spread_inside") == 0.0 and seen.get("price_inside") == 135.0, str(seen))
    check("_at_price restores spread_pct (0.02) after the fill", b.spread_pct == 0.02, str(b.spread_pct))
    check("_at_price restores the check-time price (137.82) after the fill", b.prices.get("HLI") == 137.82,
          str(b.prices.get("HLI")))
    # take-profit / stop: sell at level
    qty = b.p["positions"]["HLI"]["qty"]
    cash0 = b.p["cash"]
    rec = run._at_price(b, "HLI", 140.0, lambda: b.sell_qty("HLI", qty))
    fill = (b.p["cash"] - cash0) / qty
    check("_at_price sell fills exactly at the level (140.0)", rec.get("status") == "filled" and close(fill, 140.0, 1e-12),
          f"rec {rec} implied fill {fill}")
    check("_at_price level round trip realises exactly (140 - 135) x qty",
          close(b.p["realized_pnl"], 5.0 * qty, 1e-9), f"realized {b.p['realized_pnl']} want {5.0 * qty}")
    check("_at_price restores spread_pct and price after a sell", b.spread_pct == 0.02 and b.prices.get("HLI") == 137.82,
          f"spread {b.spread_pct} price {b.prices.get('HLI')}")
    # a thin, cheap name would otherwise pay its tick floor: FLD level fill must still be exact
    b = new_broker(0.02, quotes())
    rec = run._at_price(b, "FLD", 0.50, lambda: b.buy_notional("FLD", 500.0))
    check("_at_price FLD buy at 0.50 is exact (tick floor 1.0% not charged)",
          rec.get("status") == "filled" and b.p["positions"]["FLD"]["avg_cost"] == 0.50,
          f"avg_cost {b.p['positions'].get('FLD', {}).get('avg_cost')}")
    # the next MARKET fill after a level fill pays the per-name spread again
    b.buy_notional("HLI", 1000.0)
    check("market buy right after _at_price pays per-name spread again (HLI 0.04)",
          close(b.p["positions"]["HLI"]["avg_cost"], round(137.82 * 1.0004, 6)),
          f"avg_cost {b.p['positions']['HLI']['avg_cost']}")
    # symbol with no check-time price: the temporary price is removed afterwards
    b = new_broker(0.02, quotes())
    rec = run._at_price(b, "ZZZ", 42.0, lambda: b.buy_notional("ZZZ", 100.0))
    check("_at_price on an unpriced symbol fills at the level and removes the temp price",
          rec.get("status") == "filled" and b.p["positions"]["ZZZ"]["avg_cost"] == 42.0 and "ZZZ" not in b.prices
          and b.spread_pct == 0.02, f"rec {rec} prices has ZZZ: {'ZZZ' in b.prices}")
    # restoration survives an exception inside the fill
    b = new_broker(0.02, quotes())
    def boom():
        raise RuntimeError("fill failed")
    try:
        run._at_price(b, "AAPL", 300.0, boom)
        raised = False
    except RuntimeError:
        raised = True
    check("_at_price restores spread_pct and price when the fill raises",
          raised and b.spread_pct == 0.02 and b.prices.get("AAPL") == 333.08,
          f"raised {raised} spread {b.spread_pct} price {b.prices.get('AAPL')}")


def test_round_trip_ledger():
    # thin name: MAIA 0.50 one-way
    b = new_broker(0.02, quotes())
    fb = round(1.39 * 1.005, 6)
    fs = round(1.39 * 0.995, 6)
    b.buy_notional("MAIA", 1000.0)
    qty = b.p["positions"]["MAIA"]["qty"]
    check("round trip MAIA buy: qty = 1000 / (1.39 x 1.005), cash 24,000",
          close(qty, 1000.0 / fb) and close(b.p["cash"], 24_000.0), f"qty {qty} cash {b.p['cash']}")
    rec = b.sell_qty("MAIA", qty)
    proceeds = qty * fs
    check("round trip MAIA sell: cash = 24,000 + qty x 1.39 x 0.995",
          close(b.p["cash"], 24_000.0 + proceeds), f"cash {b.p['cash']} want {24_000.0 + proceeds}")
    check("round trip MAIA realized_pnl = (sell fill - buy fill) x qty",
          close(b.p["realized_pnl"], (fs - fb) * qty), f"realized {b.p['realized_pnl']} want {(fs - fb) * qty}")
    check("round trip MAIA costs ~1.0% of notional (two half-spreads of 0.50%)",
          close(-b.p["realized_pnl"], 1000.0 * (1 - fs / fb), 1e-9) and 9.9 < -b.p["realized_pnl"] < 10.0,
          f"realized {b.p['realized_pnl']}")
    check("round trip MAIA ledger closes: cash == deposited + realized_pnl",
          close(b.p["cash"], b.p["deposited"] + b.p["realized_pnl"]), f"cash {b.p['cash']} dep {b.p['deposited']}")
    check("round trip MAIA sell record reports the bid fill and rounded P/L",
          rec.get("price") == round(fs, 2) and rec.get("realized_pnl") == round((fs - fb) * qty, 2), str(rec))
    # liquid name, partial exit, then a level exit: invariant cash + basis == deposited + realized
    b = new_broker(0.02, quotes())
    b.buy_notional("AAPL", 2000.0)
    half = b.p["positions"]["AAPL"]["qty"] / 2
    b.sell_qty("AAPL", half)
    pos = b.p["positions"]["AAPL"]
    check("partial exit AAPL: cash + qty x avg_cost == deposited + realized_pnl",
          close(b.p["cash"] + pos["qty"] * pos["avg_cost"], b.p["deposited"] + b.p["realized_pnl"]),
          f"lhs {b.p['cash'] + pos['qty'] * pos['avg_cost']} rhs {b.p['deposited'] + b.p['realized_pnl']}")
    fb = round(333.08 * 1.0002, 6); fs = round(333.08 * 0.9998, 6)
    check("partial exit AAPL realized_pnl = (bid - offer) x half",
          close(b.p["realized_pnl"], (fs - fb) * half), f"realized {b.p['realized_pnl']}")
    saved = json.loads(Path(b._pf).read_text())
    check("ledger written to the temp path matches memory",
          close(saved["cash"], b.p["cash"]) and close(saved["realized_pnl"], b.p["realized_pnl"]), "")


def test_no_quotes_fallback():
    px = quotes()
    px["NOVOL"] = {"price": 50.0}                      # priced, no volume at all
    b = new_broker(0.02, px)
    b.buy_notional("NOVOL", 1000.0)
    check("no-volume symbol falls back to flat 0.02: fill 50 x 1.0002",
          close(b.p["positions"]["NOVOL"]["avg_cost"], round(50.0 * 1.0002, 6)),
          f"avg_cost {b.p['positions']['NOVOL']['avg_cost']}")
    qty = b.p["positions"]["NOVOL"]["qty"]; cash0 = b.p["cash"]
    b.sell_qty("NOVOL", qty)
    check("no-volume symbol sell at flat 0.02: fill 50 x 0.9998",
          close((b.p["cash"] - cash0) / qty, round(50.0 * 0.9998, 6), 1e-9), "")
    b.prices["BARE"] = 20.0                           # priced but absent from quotes entirely
    b.buy_notional("BARE", 100.0)
    check("symbol absent from quotes falls back to flat 0.02: fill 20 x 1.0002",
          close(b.p["positions"]["BARE"]["avg_cost"], round(20.0 * 1.0002, 6)),
          f"avg_cost {b.p['positions']['BARE']['avg_cost']}")
    b2 = new_broker(0.02)                             # set_prices never called: no .quotes attribute
    b2.prices = {"CHEAP": 0.60}
    b2.buy_notional("CHEAP", 100.0)
    check("broker without quotes (set_prices never called) uses flat 0.02, no tick floor",
          close(b2.p["positions"]["CHEAP"]["avg_cost"], round(0.60 * 1.0002, 6)),
          f"avg_cost {b2.p['positions']['CHEAP']['avg_cost']}")
    b3 = new_broker(0.75, {"PEPE": {"price": 0.000003, "volume24_usd": 5_000_000}})   # memecoin-shaped quote
    check("memecoin-shaped quote (volume24_usd only) keeps its flat 0.75", close(b3._spread("PEPE"), 0.75),
          str(b3._spread("PEPE")))


def main() -> int:
    before = repo_ledger_hashes()
    probe_nan()
    tests = [test_tier_boundaries, test_real_names, test_tick_floor, test_missing_inputs,
             test_never_below_default, test_volume_key_fallback, test_market_buy, test_market_sell,
             test_level_fills_zero_spread, test_at_price, test_round_trip_ledger, test_no_quotes_fallback]
    for t in tests:
        print(f"--- {t.__name__}")
        try:
            t()
        except Exception as e:  # noqa: BLE001
            check(f"{t.__name__} ran without raising", False, f"{type(e).__name__}: {e}")
    print("--- isolation")
    after = repo_ledger_hashes()
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    check("repo ledger/state/site-data files unchanged by the test run", not changed, f"changed: {changed}")
    for d in TMP_DIRS:
        shutil.rmtree(d, ignore_errors=True)
    for line in INFO:
        print(f"INFO  {line}")
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)} passed, {len(failed)} failed, {len(RESULTS)} checks")
    return 1 if failed else 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    sys.exit(main())
