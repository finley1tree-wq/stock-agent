"""Selection culls: no new entries from 14:00 ET, no momentum-only entries (agent/selection.py).

Plain python3 (prints PASS/FAIL per check, exits 1 on any failure), also collectable by pytest:

    python3 tests/test_selection.py

agent/run.py cannot be imported here without the network libraries it pulls in (yfinance, anthropic,
the feeds), so the four run.py functions this change touches are compiled STRAIGHT FROM ITS SOURCE
into a namespace with stubs for prices/state/learn/instruments. Nothing here touches the network, a
broker, the model or the repo's ledger: standing orders live in a temp file.
"""
import ast
import re
import sys
import tempfile
from datetime import datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from agent import autopilot, evolve, experiments, selection, triggers  # noqa: E402
from agent.broker_sim import close_time, is_trading_day  # noqa: E402

ET = ZoneInfo("America/New_York")
FAILS: list[str] = []
CHECKS = 0
CULL = {"no_new_entries_after_et": "14:00", "allow_momentum_only_entries": False}


def check(name, ok, detail=""):
    global CHECKS
    CHECKS += 1
    if not ok:
        FAILS.append(name)
    print(("PASS  " if ok else "FAIL  ") + name + (f"  ({detail})" if detail and not ok else ""))
    return bool(ok)


def _group(fn):
    before = len(FAILS)
    fn()
    assert len(FAILS) == before, f"{len(FAILS) - before} check(s) failed: {FAILS[before:]}"


def run_functions(**stubs):
    """Compile the named top-level definitions of agent/run.py, and only those, into a namespace."""
    src = (ROOT / "agent" / "run.py").read_text(encoding="utf-8")
    names = {"SIGNALS", "_clean_signals", "apply_guardrails", "apply_sell_guardrails", "_at_price",
             "fill_standing_orders", "past_entry_cutoff", "_evolve_verdict"}
    body = [n for n in ast.parse(src).body
            if (isinstance(n, ast.FunctionDef) and n.name in names)
            or (isinstance(n, ast.Assign) and any(getattr(t, "id", None) in names for t in n.targets))]
    ns = {"datetime": datetime, "timedelta": timedelta, "time": time, "ET": ET,
          "is_trading_day": is_trading_day, "close_time": close_time,
          "selection": selection, "evolve": evolve, "experiments": experiments, "triggers": triggers, **stubs}
    exec(compile(ast.Module(body=body, type_ignores=[]), str(ROOT / "agent" / "run.py"), "exec"), ns)
    return ns, src


# --------------------------------------------------------------------------------------------------
def _signals():
    cases = [(["momentum"], True), (["momentum", "autopilot"], True), (["momentum", "dip_entry"], True),
             (["momentum", "dip_entry", "standing_order"], True), (["momentum", "patience"], True),
             (["momentum", "congress", "autopilot"], False), (["momentum", "news"], False),
             (["insider"], False), (["risk_management", "auto_bracket"], False), ([], False), (None, False)]
    bad = [(s, want) for s, want in cases if selection.momentum_only(s) != want]
    check("momentum_only: only momentum (plus mechanism tags) counts; any other reason clears it", not bad, str(bad))
    check("entry_blocked: off by default (key absent) - nothing changes without the config",
          selection.entry_blocked(["momentum", "autopilot"], {}) is None)
    check("entry_blocked: allow_momentum_only_entries false blocks a momentum-only entry",
          bool(selection.entry_blocked(["momentum", "autopilot"], CULL)))
    check("entry_blocked: ...but not a congress-backed one, nor an averaging-in bracket",
          selection.entry_blocked(["momentum", "congress"], CULL) is None
          and selection.entry_blocked(["risk_management", "auto_bracket"], CULL) is None)


def test_signals():
    _group(_signals)


def _entry_time():
    ns, _ = run_functions()
    cut = ns["past_entry_cutoff"]
    g = {**CULL, "max_hold_minutes": 30}
    mon = lambda h, m: datetime(2026, 9, 28, h, m, tzinfo=ET)          # a Monday, full session
    check("selection.past_entry_time: 13:59 no, 14:00 yes, unset/garbled -> off",
          not selection.past_entry_time(mon(13, 59), g) and selection.past_entry_time(mon(14, 0), g)
          and not selection.past_entry_time(mon(15, 0), {}) and not selection.past_entry_time(mon(15, 0), {"no_new_entries_after_et": "2pm"}))
    check("run.past_entry_cutoff: 13:59 ET entries allowed", cut(mon(13, 59), g) is False)
    check("run.past_entry_cutoff: 14:00 and 15:00 ET no new entries", cut(mon(14, 0), g) and cut(mon(15, 0), g))
    check("run.past_entry_cutoff: not on a weekend", cut(datetime(2026, 9, 26, 14, 30, tzinfo=ET), g) is False)
    g0 = {"max_hold_minutes": 30}
    check("run.past_entry_cutoff without the key: unchanged (15:27 open, 15:28 closed)",
          cut(mon(15, 27), g0) is False and cut(mon(15, 28), g0) is True and cut(mon(15, 0), g0) is False)


def test_entry_time():
    _group(_entry_time)


def _apply_guardrails():
    ns, _ = run_functions()
    g = {"_weekly_budget": 25000.0, "max_daily_deploy_pct": 100, "max_per_ticker_pct": 100, "min_order_usd": 100,
         "max_orders_per_day": 200, "rebuy_cooldown_minutes": 0, "min_positions": 8}
    st = {"spent_today": 0.0, "orders_today": 0, "by_ticker": {}, "sold_today": [], "sold_ts": {}}
    plan = {"orders": [
        {"ticker": "AAA", "usd": 2000, "signals": ["momentum"], "evidence": "+8% over the month", "why": "model"},
        {"ticker": "BBB", "usd": 2000, "signals": ["momentum", "autopilot"], "evidence": "+5% over the month", "why": "rules"},
        {"ticker": "CCC", "usd": 2000, "signals": ["momentum", "congress", "autopilot"], "evidence": "2 members bought", "why": "rules"},
        {"ticker": "DDD", "usd": 2000, "signals": ["news"], "evidence": "a headline", "why": "model"}]}
    allowed = {"AAA", "BBB", "CCC", "DDD"}
    out, dropped, _ = ns["apply_guardrails"](plan, allowed, 25000.0, st, {**g, **CULL}, False, None, chase_check=False)
    got = sorted(o["ticker"] for o in out)
    check("apply_guardrails: momentum-only buys (model and autopilot) are dropped, the others fill",
          got == ["CCC", "DDD"], f"filled {got}")
    check("apply_guardrails: the drop says why",
          sum("momentum-only" in d for d in dropped) == 2, str(dropped))
    out, dropped, _ = ns["apply_guardrails"](plan, allowed, 25000.0, st, g, False, None, chase_check=False)
    check("apply_guardrails without the key: all four fill, as before",
          sorted(o["ticker"] for o in out) == ["AAA", "BBB", "CCC", "DDD"], str(dropped))


def test_apply_guardrails():
    _group(_apply_guardrails)


def _standing_buys():
    """A momentum-only standing buy that fires is CANCELLED (not left to be dropped every tick); a
    disclosure-backed one on the same bar fills at its level."""
    triggers.FILE = Path(tempfile.mkdtemp(prefix="test_selection_")) / "triggers.json"
    now = datetime(2026, 9, 28, 10, 30, tzinfo=ET)
    base = {"kind": "buy_limit", "price": 95.0, "status": "working", "created": "2026-09-28 10:00", "created_ts": 0,
            "why": "", "evidence": "x", "good_until": "2099-12-31", "usd": 1000.0}
    triggers._save({"orders": [{**base, "id": "momo", "ticker": "MOMO", "signals": ["momentum", "dip_entry"]},
                               {**base, "id": "cong", "ticker": "CONG", "signals": ["momentum", "congress"]},
                               # an unknown tag is not a reason: apply_guardrails cleans it away, so
                               # this is momentum-only and must be cancelled, not dropped every tick
                               {**base, "id": "odd", "ticker": "ODD", "signals": ["momentum", "breakout"]}]})
    bar = [{"t": int(now.timestamp()) - 300, "o": 96.0, "h": 96.5, "l": 94.5, "c": 95.2}]
    calls = []

    class Broker:
        prices, spread_pct = {}, 0.0

        def positions(self):
            return {}

        def buy_notional(self, sym, usd):
            calls.append((sym, usd, self.prices.get(sym)))
            return {"symbol": sym, "status": "filled", "notional": usd, "qty": usd / self.prices[sym],
                    "price": self.prices[sym]}

    noop = lambda *a, **k: None
    ns, _ = run_functions(prices=SimpleNamespace(intraday=lambda tickers, since_ts=0: {t: bar for t in tickers}),
                          state=SimpleNamespace(record_order=noop, save=noop),
                          learn=SimpleNamespace(record=noop, record_sell=noop, entry_signals=lambda s: []),
                          instruments=SimpleNamespace(check=lambda t: {}))
    g = {"_weekly_budget": 25000.0, "max_daily_deploy_pct": 100, "max_per_ticker_pct": 100, "min_order_usd": 100,
         "max_orders_per_day": 200, "rebuy_cooldown_minutes": 0, "trigger_slippage_pct": 0.05, **CULL}
    st = {"spent_today": 0.0, "orders_today": 0, "by_ticker": {}, "sold_today": [], "sold_ts": {}}
    logs = []
    bought, sold, did = ns["fill_standing_orders"](now, now.date(), Broker(), {}, {}, st, g, {"MOMO", "CONG", "ODD"},
                                                   25000.0, {}, {}, logs.append)
    orders = {o["id"]: o for o in triggers.all_orders()}
    check("a momentum-only standing buy that fires is cancelled, with the reason",
          orders["momo"]["status"] == "cancelled" and "momentum-only" in orders["momo"].get("cancel_reason", ""),
          str(orders["momo"]))
    check("a standing buy tagged momentum plus an unknown tag is cancelled too (same cleaned tags as the guardrails)",
          orders["odd"]["status"] == "cancelled" and "momentum-only" in orders["odd"].get("cancel_reason", ""),
          str(orders["odd"]))
    check("the congress-backed standing buy on the same bar fills at its level (95.0)",
          calls == [("CONG", 1000.0, 95.0)] and orders["cong"]["status"] == "filled", f"{calls} {orders['cong']['status']}")


def test_standing_buys():
    _group(_standing_buys)


def _autopilot():
    g = {"min_order_usd": 100, "max_entry_range_pct": 85, "min_decision_minutes": 6}
    # scores: MOMO 0.95 (low in range) + 60/50 = 2.15; CONG 1.2 (one net congressional buyer) + 0.40 + 0.04 = 1.64
    ctx = {"prices": {"MOMO": {"price": 50.0, "change_1m_pct": 60.0, "pct_of_day_range": 5.0},
                      "CONG": {"price": 80.0, "change_1m_pct": 2.0, "pct_of_day_range": 60.0}},
           "allowed_tickers": ["MOMO", "CONG"], "current_positions": {}, "min_positions": 1,
           "remaining_budget_usd": 5000.0, "congress_net_buy_pressure": {"CONG": 1.0},
           "who_disclosed_it": {}, "congress_recent_trades": [], "insider_recent_trades": [],
           "datetime_et": "2026-09-28 10:00"}
    before = [o["ticker"] for o in autopilot.plan(ctx, g)["orders"]]
    check("autopilot (no cull): the best-scoring name is the momentum-only MOMO", before == ["MOMO"], str(before))
    p = autopilot.plan(ctx, {**g, **CULL})
    after = [(o["ticker"], o["signals"]) for o in p["orders"]]
    check("autopilot (cull): skips MOMO and takes the congress-backed CONG instead",
          after == [("CONG", ["momentum", "autopilot", "congress"])], str(after))
    ctx2 = {**ctx, "prices": {"MOMO": ctx["prices"]["MOMO"]}, "allowed_tickers": ["MOMO"]}
    p2 = autopilot.plan(ctx2, {**g, **CULL})
    check("autopilot (cull): with only momentum-only names it buys nothing and says why",
          not p2["orders"] and "allow_momentum_only_entries" in p2["reasoning"], p2["reasoning"])
    p3 = autopilot.plan({**ctx, "no_new_entries_this_check": True}, {**g, **CULL})
    check("autopilot: nothing past the entry cutoff", not p3["orders"])


def test_autopilot():
    _group(_autopilot)


def _main_wiring():
    """run.main cannot be executed offline; pin down that it culls resting buys and dip orders too."""
    _, src = run_functions()
    fn = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "main")
    body = ast.get_source_segment(src, fn)
    check("run.main culls the model's buy triggers through selection.entry_blocked",
          bool(re.search(r"selection\.entry_blocked\(_clean_signals\(t\), g\) if .*BUY_KINDS", body)))
    check("run.main culls dip_hunt's orders through selection.entry_blocked",
          bool(re.search(r"auto \+= \[o for o in dips if not selection\.entry_blocked\(o\.get\(\"signals\"\), g\)\]", body)))
    check("run.main drops buy triggers past either cutoff, clock or no clock",
          bool(re.search(r"\n    if cutoff:[^\n]*\n        want = \[t for t in want if str\(t\.get\(\"kind\", \"\"\)\)\.lower\(\) not in triggers\.BUY_KINDS\]", body)))


def test_main_wiring():
    _group(_main_wiring)


def main():
    for name, fn in (("signals", _signals), ("entry time", _entry_time), ("apply_guardrails", _apply_guardrails),
                     ("standing buys", _standing_buys), ("autopilot", _autopilot), ("run.main wiring", _main_wiring)):
        print(f"--- {name}")
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            check(f"{name} ran without raising", False, f"{type(e).__name__}: {e}")
    print(f"\n{CHECKS - len(FAILS)}/{CHECKS} checks passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
