"""The ratchet stop only ever tightens - including when the price dips back under the entry.

Plain python3: prints PASS/FAIL per check, exits 1 on any failure. Orders go to a temp file.

    python3 tests/test_ratchet.py
"""
import sys, tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from agent import triggers  # noqa: E402

FAILS = CHECKS = 0
NOW = datetime(2026, 9, 16, 10, 0, tzinfo=ZoneInfo("America/New_York"))


def check(name, ok, detail=""):
    global FAILS, CHECKS
    CHECKS += 1; FAILS += not ok
    print(("PASS  " if ok else "FAIL  ") + name + (f"  ({detail})" if detail and not ok else ""))


def cfg(ratchet=True):
    return {"enabled": True, "intraday_target_mult": 0.4, "intraday_stop_mult": 1.0, "intraday_floor_pct": 0.15,
            "ratchet_after_pct_of_target": 50 if ratchet else 0, "ratchet_keep_pct_of_gain": 60,
            "_max_hold_minutes": 30, "scale_in": {"enabled": False}}


def fresh():
    triggers.FILE = Path(tempfile.mkdtemp()) / "triggers.json"


def orders(kind):
    return [o for o in triggers.working(NOW) if o["ticker"] == "XYZ" and o["kind"] == kind]


def run(price, c):
    pos = {"XYZ": {"qty": 30.0, "avg_cost": 100.0}}
    px = {"XYZ": {"price": price, "atr_pct": 2.6}}
    auto, _ = triggers.rebalance_brackets(NOW, pos, px, c)      # exactly as run.py uses it
    if auto:
        triggers.place(auto, NOW, set(pos), set(pos), px)
    return auto


def main():
    initial = 100 * (1 - 2.6 * (30 / 390) ** 0.5 / 100)          # entry x (1 - stop%)

    fresh(); run(100.0, cfg())
    s = orders("stop_loss")
    check("fresh position: one stop at entry x (1 - stop%)", len(s) == 1 and abs(float(s[0]["price"]) - initial) < 0.02, str(s))
    tp0 = orders("take_profit")
    check("fresh position: a take-profit is placed", len(tp0) == 1, str(tp0))

    run(100.20, cfg())                                            # +0.20% is past half the ~0.29% target
    up = float(orders("stop_loss")[0]["price"])
    check("price rises past the threshold: stop moves up above entry", up > 100.0, str(up))

    run(99.90, cfg())                                             # dips back under the entry
    after = float(orders("stop_loss")[0]["price"])
    check("price dips under entry: ratcheted stop does NOT step back down", after >= up - 1e-6, f"{up} -> {after}")
    check("take-profit unchanged through the ratchet", [o["price"] for o in orders("take_profit")] == [tp0[0]["price"]])

    fresh(); run(100.0, cfg(ratchet=False)); run(100.20, cfg(ratchet=False))
    s = orders("stop_loss")
    check("ratchet disabled: stop stays at the initial level", len(s) == 1 and abs(float(s[0]["price"]) - initial) < 0.02, str(s))

    print(f"\n{CHECKS - FAILS}/{CHECKS} checks passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
