"""Cloud crypto paper trader (agent/crypto): backtest arithmetic, stages, champion choice, the book.

Plain python3 (prints PASS/FAIL per check, exits 1 on any failure); synthetic bars only, no network:

    python3 tests/test_crypto.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from agent.crypto import engine, strategies  # noqa: E402

FAILS: list[str] = []
CHECKS = 0
DAY = 86400
T0 = 1700006400          # a Wednesday, 00:00 UTC


def check(name, ok, detail=""):
    global CHECKS
    CHECKS += 1
    if not ok:
        FAILS.append(name)
    print(("PASS  " if ok else "FAIL  ") + name + (f"  ({detail})" if detail and not ok else ""))


def bars_from(closes):
    out, prev = [], closes[0]
    for i, c in enumerate(closes):
        out.append({"t": T0 + i * DAY, "o": prev, "h": max(prev, c) * 1.001, "l": min(prev, c) * 0.999, "c": c, "v": 1e6})
        prev = c
    return out


def test_backtest():
    up = bars_from([100 * 1.01 ** i for i in range(300)])
    bt = engine.backtest(up, "hold", 0.0)
    # hold enters at the open of bar WARMUP+1 (= close of WARMUP) and rides to the last closed bar
    exp = up[-1]["c"] / up[strategies.WARMUP]["c"] - 1
    check("backtest: hold with no cost tracks the price", abs(bt["net_return"] - exp) < 1e-3, f"{bt['net_return']} vs {exp:.4f}")
    bt_c = engine.backtest(up, "hold", 0.65)
    check("backtest: one entry pays the cost once", abs((1 + bt_c["net_return"]) / (1 + bt["net_return"]) - (1 - 0.0065)) < 1e-6)
    check("backtest: the signal is the last closed bar's decision", bt["signal"] == 1)
    down = bars_from([100 * 0.99 ** i for i in range(300)])
    check("backtest: trend_ma stays out of a steady decline", engine.backtest(down, "trend_ma", 0.65)["exposure"] == 0.0)
    check("backtest: hold in a decline loses and has a drawdown", engine.backtest(down, "hold", 0.65)["max_dd"] > 0.8)
    saw = bars_from([100 + (10 if (i // 15) % 2 else -10) + i * 0.01 for i in range(400)])
    d = engine.backtest(saw, "donchian", 0.65)
    check("backtest: round trips are counted", d["trips"] >= 1, str(d))


def test_strategies():
    up = bars_from([100 * 1.01 ** i for i in range(120)])
    i = len(up) - 1
    check("trend_ma: long in an uptrend", strategies.trend_ma(up, i, {})[0] == 1)
    check("donchian: a new 20-day high enters", strategies.donchian(up, i, {})[0] == 1)
    check("tsm: positive 30-day return is long", strategies.tsm(up, i, {})[0] == 1)
    crash = bars_from([100] * 60 + [100 * 0.95 ** k for k in range(1, 15)])
    check("rsi_rev: deeply oversold enters", strategies.rsi_rev(crash, len(crash) - 1, {})[0] == 1)
    pos, st = 1, {"pos": 1, "age": 9}
    check("rsi_rev: exits after 10 days", strategies.rsi_rev(crash, len(crash) - 1, st)[0] == 0)


def test_stage_and_select():
    cfg = engine.config()
    good = {"trips": 40, "days_in_market": 500, "cagr": 0.3, "sharpe": 1.0, "first_half": 0.2, "second_half": 0.1,
            "net_return": 2.0, "max_dd": 0.4}
    hold = {**good, "net_return": 1.0, "max_dd": 0.8}
    check("stage: passes the bar -> SURVIVOR", engine._stage(good, hold, {}, cfg, False) == "SURVIVOR")
    check("stage: losing in both halves -> CULLED",
          engine._stage({**good, "first_half": -0.1, "second_half": -0.2}, hold, {}, cfg, False) == "CULLED")
    check("stage: losing live (n=10, t<=-1) -> CULLED", engine._stage(good, hold, {"n": 12, "t": -1.5}, cfg, False) == "CULLED")
    check("stage: too few trades -> PROBATION",
          engine._stage({**good, "trips": 5, "days_in_market": 100}, hold, {}, cfg, False) == "PROBATION")
    check("stage: not beating hold -> PROBATION",
          engine._stage({**good, "net_return": 0.5, "max_dd": 0.75}, hold, {}, cfg, False) == "PROBATION")
    orgs = {"hold": {"stage": "PROBATION", "backtest": {"sharpe": 2.0}},
            "tsm": {"stage": "SURVIVOR", "backtest": {"sharpe": 1.00}},
            "trend_ma": {"stage": "SURVIVOR", "backtest": {"sharpe": 1.10}},
            "rsi_rev": {"stage": "CULLED", "backtest": {"sharpe": 3.0}}}
    check("select: survivors before probation, then Sharpe", engine.select(orgs) == "trend_ma")
    check("select: an incumbent within the margin keeps the coin", engine.select(orgs, "tsm") == "tsm")
    check("select: a clearly better challenger takes it", engine.select({**orgs, "tsm": {"stage": "SURVIVOR", "backtest": {"sharpe": 0.8}}}, "tsm") == "trend_ma")
    check("select: everything culled -> no champion", engine.select({"a": {"stage": "CULLED", "backtest": {"sharpe": 1}}}) is None)


def test_book():
    book, ledger = {"cash": 1000.0, "holdings": {}, "realized": 0.0}, []
    engine._buy(book, ledger, "ETH", 2000.0, 500.0, 0.65, "d", "tsm", "SURVIVOR")
    h = book["holdings"]["ETH"]
    check("book: a buy spends the dollars and pays the cost", book["cash"] == 500.0 and abs(h["qty"] - 500 * 0.9935 / 2000) < 1e-12)
    engine._sell(book, ledger, "ETH", 2000.0, 0.65, "d", "went flat")
    check("book: a round trip at the same price loses about twice the cost", abs(book["realized"] - (-6.48)) < 0.02, str(book["realized"]))
    check("book: the ledger records both sides", [x["side"] for x in ledger] == ["buy", "sell"])


if __name__ == "__main__":
    test_backtest()
    test_strategies()
    test_stage_and_select()
    test_book()
    print(f"\n{CHECKS - len(FAILS)}/{CHECKS} passed")
    sys.exit(1 if FAILS else 0)
