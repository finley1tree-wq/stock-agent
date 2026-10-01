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
from agent import evolve, experiments  # noqa: E402

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


def trip(sym, hour, signals, pnl, date="2026-09-21", qty=1.0, pct=None, hold=None):
    buy = {"symbol": sym, "side": "buy", "status": "filled", "qty": qty, "date": date,
           "time_et": f"{hour:02d}:05", "hour_et": hour, "signals": signals}
    if hold is not None:
        buy["hold_minutes"] = hold
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


def test_queue():
    g = {"experiments": [{"name": "hold", "param": "hold_minutes", "arms": [30, 90]},
                         {"name": "ratchet", "param": "ratchet", "arms": ["on", "off"]},
                         {"name": "hold_long", "param": "hold_minutes", "arms": [90, 120]}],
         "experiment_rules": {"min_trips_per_arm": 40, "decide_t": 2.0, "max_trips_per_arm": 150}}
    st_ = experiments.standings(g, [])
    check("queue: first experiment runs, the rest wait", [r["status"] for r in st_] == ["running", "queued", "queued"])
    st = {}
    flips = iter([0.1, 0.9])
    a = experiments.assign(st, g, "AAA", set(), rows=[], rng=lambda: next(flips))
    b = experiments.assign(st, g, "BBB", {"AAA"}, rows=[], rng=lambda: next(flips))
    check("queue: a coin picks each new position's arm", (a["params"], b["params"]) == ({"hold_minutes": 30}, {"hold_minutes": 90}), str((a, b)))
    check("queue: an add keeps its position's arm", experiments.assign(st, g, "BBB", {"AAA", "BBB"}, rows=[], rng=lambda: 0.0) is b)
    check("queue: a closed position's arm is forgotten", experiments.assign(st, g, "BBB", {"AAA"}, rows=[], rng=lambda: 0.0)["params"] == {"hold_minutes": 30})
    check("queue: hold_for reads the arm", experiments.hold_for(st, g, "AAA", 15) == 30)
    check("queue: journal tags carry the arm", experiments.journal_tags(a) == {"experiments": {"hold": 30}, "hold_minutes": 30})
    random.seed(3)
    rows = []
    for i in range(45):          # legacy rows: hold_minutes only, as the first trial wrote them
        rows += trip(f"S{i}", 10, ["x"], 1.0, pct=random.gauss(-0.10, 0.3), hold=30)
        rows += trip(f"L{i}", 10, ["x"], 3.0, pct=random.gauss(0.25, 0.3), hold=90)
    active, fixed = experiments.current(g, rows)
    check("queue: a decided winner is fixed and the next experiment runs", fixed == {"hold_minutes": 90} and active["name"] == "ratchet")
    rec = experiments.assign({}, g, "C", set(), rows=rows, rng=lambda: 0.9)
    check("queue: new positions get the winner plus the running coin", rec == {"params": {"hold_minutes": 90, "ratchet": "off"}, "tags": {"ratchet": "off"}}, str(rec))
    check("queue: ratchet off becomes a bracket override", experiments.bracket_overrides({"exp_arm": {"C": rec}}) == {"C": {"ratchet_after_pct_of_target": 0}})
    tagged = sum((trip(f"R{i}", 10, ["x"], 1.0, pct=0.1, hold=90) for i in range(3)), [])
    for r in tagged:
        if r["side"] == "buy":
            r["experiments"] = {"ratchet": "on"}
    after = experiments.standings(g, rows + tagged)
    check("queue: tagged rows count for their experiment only", after[0]["arms"]["90"]["n"] == 45 and after[1]["arms"]["on"]["n"] == 3)
    check("queue: legacy hold_trial still works as a one-item queue", [r["name"] for r in experiments.standings({"hold_trial": {}}, [])] == ["hold"])


def test_day_reset():
    rows = [{"symbol": "TPL", "side": "buy", "status": "filled", "qty": 1, "date": "2026-09-11", "hour_et": 14, "signals": ["congress"]}]
    rows += trip("TPL", 10, ["news"], 4.0, date="2026-09-14")         # the 09-11 sell is missing from the journal
    t = evolve.round_trips(rows)
    check("pairing: a day with no sell does not leak into the next day's trip",
          len(t) == 1 and t[0]["hour"] == 10 and t[0]["date"] == "2026-09-14", str(t))


def test_trial_without_evolve():
    rows = []
    random.seed(3)
    for i in range(45):
        rows += trip(f"S{i}", 10, ["x"], 1.0, pct=random.gauss(-0.10, 0.3), hold=30)
        rows += trip(f"L{i}", 10, ["x"], 3.0, pct=random.gauss(0.25, 0.3), hold=90)
    g = {"hold_trial": {}}                                            # evolve switched off
    check("trial: works with evolve off", evolve.load(g, rows) is None and evolve.trial_state(g, rows)["winner"] == 90)


def test_settings():
    check("settings: absent -> off", evolve.settings({}) is None)
    check("settings: enabled false -> off", evolve.settings({"evolve": {"enabled": False}}) is None)
    check("settings: empty block -> defaults", evolve.settings({"evolve": {}}) == evolve.DEFAULTS)
    check("settings: override merges", evolve.settings({"evolve": {"cull_t": -2}})["cull_t"] == -2)
    check("load: off returns None", evolve.load({}) is None)
    check("summary: None-safe", evolve.summary(None) == {})


def test_hold_trial():
    g = {"evolve": {}, "hold_trial": {}}
    check("trial: absent -> off", evolve.trial_settings({}) is None and experiments.assign({}, {}, "X", set(), rows=[]) is None)

    cfg = evolve.trial_settings(g)
    random.seed(3)
    rows = []
    for i in range(45):
        rows += trip(f"S{i}", 10, ["congress"], 1.0, pct=random.gauss(-0.10, 0.3), hold=30)
        rows += trip(f"L{i}", 10, ["congress"], 3.0, pct=random.gauss(0.25, 0.3), hold=90)
    r = evolve.trial(rows, cfg)
    check("trial: a clearly better arm wins", r["winner"] == 90 and r["arms"]["90"]["n"] == 45, str(r))
    later = rows + sum((trip(f"M{i}", 10, ["congress"], -5.0, pct=-2.0, hold=90) for i in range(60)), [])
    check("trial: the verdict is final - the winner's later losses do not reopen it",
          evolve.trial(later, cfg)["winner"] == 90)
    young = sum((trip(f"Y{i}", 10, ["x"], 1.0, pct=1.0 if i % 2 else -0.2, hold=90 if i % 2 else 30) for i in range(20)), [])
    check("trial: no verdict before min_trips_per_arm", evolve.trial(young, cfg)["winner"] is None)
    random.seed(5)
    close = []
    for i in range(160):
        close += trip(f"A{i}", 10, ["x"], 1.0, pct=random.gauss(0.02, 1.0), hold=30)
        close += trip(f"B{i}", 10, ["x"], 1.0, pct=random.gauss(0.05, 1.0), hold=90)
    rc = evolve.trial(close, cfg)
    check("trial: a close race is settled by the average after max_trips_per_arm",
          rc["winner"] in (30, 90) and "not proven" in (rc["why"] or ""), str(rc["why"]))
    pre = trip("P", 10, ["x"], 1.0, pct=5.0)          # before the trial: no hold_minutes on the buy
    check("trial: trades from before the trial are not counted", evolve.trial(pre, cfg)["arms"]["30"]["n"] == 0)
    check("load: attaches the trial when both are on", "hold_trial" in evolve.load(g, rows))


if __name__ == "__main__":
    test_hold_trial()
    test_queue()
    test_day_reset()
    test_trial_without_evolve()
    test_pairing()
    test_stages()
    test_settings()
    print(f"\n{CHECKS - len(FAILS)}/{CHECKS} passed")
    sys.exit(1 if FAILS else 0)
