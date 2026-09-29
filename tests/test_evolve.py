"""Natural selection over entry strategies (agent/evolve.py).

Plain python3 (prints PASS/FAIL per check, exits 1 on any failure), also collectable by pytest:

    python3 tests/test_evolve.py

Synthetic journals only: nothing here reads the repo's ledger, the network or a broker.
"""
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from agent import evolve  # noqa: E402

FAILS: list[str] = []
CHECKS = 0
CFG = {**evolve.DEFAULTS}


def check(name, ok, detail=""):
    global CHECKS
    CHECKS += 1
    if not ok:
        FAILS.append(name)
    print(("PASS  " if ok else "FAIL  ") + name + (f"  ({detail})" if detail and not ok else ""))
    return bool(ok)


def trip(sym, hour, signals, pnl, date="2026-09-21", qty=1.0, pct=None):
    buy = {"symbol": sym, "side": "buy", "status": "filled", "qty": qty, "date": date,
           "time_et": f"{hour:02d}:05", "hour_et": hour, "signals": signals}
    sell = {"symbol": sym, "side": "sell", "status": "filled", "qty": qty, "date": date,
            "realized_pnl": pnl, "realized_pct": pct if pct is not None else pnl / 20, "trigger": "time_stop",
            "signals": signals + ["time_stop"]}
    return [buy, sell]


def book(hour, signals, pnls, sym="AAA"):
    rows = []
    for p in pnls:
        rows += trip(sym, hour, signals, p)
    return rows


def test_pairing():
    rows = trip("X", 9, ["congress"], 5.0)
    rows += [{"symbol": "Y", "side": "buy", "status": "filled", "qty": 2, "date": "2026-09-21", "hour_et": 11,
              "signals": ["insider"]},
             {"symbol": "Y", "side": "buy", "status": "filled", "qty": 1, "date": "2026-09-21", "hour_et": 12,
              "signals": ["momentum"]},
             {"symbol": "Y", "side": "sell", "status": "filled", "qty": 3, "realized_pnl": -2.0, "realized_pct": -1}]
    rows += [{"symbol": "Z", "side": "sell", "status": "filled", "qty": 1, "realized_pnl": 9.0}]   # no entry: skipped
    rows += [{"symbol": "W", "side": "buy", "status": "rejected", "qty": 1, "hour_et": 10}]
    t = evolve.round_trips(rows)
    check("pairing: one trip per sell with an opening buy", len(t) == 2, str(t))
    check("pairing: an add-on buy keeps the OPENING buy's hour and signals",
          t[1]["hour"] == 11 and t[1]["signals"] == ["insider"], str(t[1]))
    flagged = evolve.round_trips(trip("F", 9, ["congress"], 900.0, pct=75.0))
    check("pairing: a 50%+ sell is flagged as a simulator error", flagged[0]["flagged"])


def test_stages():
    random.seed(7)
    win = [random.gauss(3.0, 4.0) for _ in range(60)]
    lose = [random.gauss(-3.0, 4.0) for _ in range(60)]
    flat = [random.gauss(0.0, 4.0) for _ in range(60)]
    young = [-10.0] * 10
    rows = book(9, ["congress"], win, "A") + book(14, ["congress"], lose, "B") + book(11, ["congress"], flat, "C") \
        + book(12, ["news"], young, "D")
    s = evolve.score(rows, CFG)
    h = s["lenses"]["hour"]
    check("stage: a consistent winner survives", h["09"]["stage"] == evolve.SURVIVOR, str(h["09"]))
    check("stage: a consistent loser is culled", h["14"]["stage"] == evolve.CULLED, str(h["14"]))
    check("stage: noise stays on probation", h["11"]["stage"] == evolve.PROBATION, str(h["11"]))
    check("stage: too few trips is probation however bad", h["12"]["stage"] == evolve.PROBATION, str(h["12"]))
    check("score: flagged fills never count",
          evolve.score(rows + trip("E", 9, ["congress"], 5000.0, pct=90.0), CFG)["trips"] == s["trips"])
    check("score: weekly breakdown present", list(h["09"]["weeks"]) == ["2026-W39"]
          and abs(h["09"]["weeks"]["2026-W39"] - sum(win)) < 0.05, str(h["09"]["weeks"]))

    w, why = evolve.verdict(s, ["congress", "autopilot"], 9)
    check("verdict: survivor hour -> full size", w == 1.0 and why.startswith("survivor"), why)
    w, why = evolve.verdict(s, ["congress"], 14)
    check("verdict: culled hour -> blocked", w == 0.0 and "culled" in why, why)
    w, why = evolve.verdict(s, ["congress"], 11)
    check("verdict: probation hour -> probation_size", w == CFG["probation_size"], why)
    w, _ = evolve.verdict(s, ["brand_new_signal"], 10)
    check("verdict: never-seen hour and mix -> probation, not blocked", w == CFG["probation_size"])
    w, _ = evolve.verdict(s, ["news"], 9)
    check("verdict: any culling lens wins over a surviving one", w == 1.0)   # news is young: probation
    s2 = evolve.score(rows + book(10, ["momentum"], lose, "M"), CFG)
    w, why = evolve.verdict(s2, ["momentum"], 9)
    check("verdict: a culled signal mix is blocked even in a survivor hour", w == 0.0 and "signals" in why, why)


def test_settings():
    check("settings: absent -> off", evolve.settings({}) is None)
    check("settings: enabled false -> off", evolve.settings({"evolve": {"enabled": False}}) is None)
    check("settings: empty block -> defaults", evolve.settings({"evolve": {}}) == evolve.DEFAULTS)
    check("settings: override merges", evolve.settings({"evolve": {"cull_t": -2}})["cull_t"] == -2)
    check("load: off returns None", evolve.load({}) is None)
    check("summary: None-safe", evolve.summary(None) == {})


if __name__ == "__main__":
    test_pairing()
    test_stages()
    test_settings()
    print(f"\n{CHECKS - len(FAILS)}/{CHECKS} passed")
    sys.exit(1 if FAILS else 0)
