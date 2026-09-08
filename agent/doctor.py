"""Health check. Run it any time; it changes nothing.

    python -m agent.doctor      (or double-click check.command)

Verifies: keys, feeds, prices, market calendar, ledger integrity, schedule, disk, and the safety gate.
Never prints a key. Exits 1 if anything is broken.
"""
import json, os, subprocess, sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from . import config, prices, politicians, insiders, news, state, safety, backtest
from .broker_sim import is_trading_day, close_time, HOLIDAYS
from .redact import redact

ROOT = Path(__file__).resolve().parent.parent
ET = ZoneInfo("America/New_York")
OK, WARN, FAIL = "  ok  ", " warn ", " FAIL "
rows: list[tuple[str, str, str]] = []

def add(status, name, detail=""):
    rows.append((status, name, detail))

def main() -> int:
    cfg = config.load_config()
    env, g = cfg["env"], cfg["guardrails"]
    now = datetime.now(ET)

    add(OK if env["anthropic_key"] else FAIL, "Anthropic key",
        "set" if env["anthropic_key"] else "MISSING — run setup.command; the agent cannot decide without it")
    add(OK if (env["fmp_key"] or env["quiver_key"]) else WARN, "Congress/insider key",
        "set" if (env["fmp_key"] or env["quiver_key"]) else "none — insider feed off; Congress still works free")
    add(OK, "broker", f"{env['broker']} ({'pretend money' if env['broker'] == 'sim' else 'REAL BROKER'})")

    try:
        import anthropic
        ids = [m.id for m in anthropic.Anthropic(api_key=env["anthropic_key"], max_retries=1).models.list(limit=50).data]
        add(OK if env["anthropic_model"] in ids else FAIL, "Anthropic auth",
            f"model {env['anthropic_model']} available" if env["anthropic_model"] in ids else f"model {env['anthropic_model']} NOT available")
    except Exception as e:
        add(FAIL, "Anthropic auth", redact(e)[:110])

    watch = config.all_watchlist_tickers(cfg)
    try:
        px = prices.snapshot(watch)
        good, bad = safety.sane_prices(px, g.get("max_daily_move_pct", 0))
        missing = [t for t in watch if t not in good]
        add(OK if not missing else WARN, "prices", f"{len(good)}/{len(watch)} watchlist quotes" + (f"; missing {', '.join(missing)}" if missing else ""))
    except Exception as e:
        add(FAIL, "prices", redact(e)[:110])

    try:
        ct = politicians.recent_trades(env, g["politician_lookback_days"])
        add(OK if ct else WARN, "Congress feed", f"{len(ct)} trades in {g['politician_lookback_days']}d via {politicians.last_source}" if ct else "no rows")
    except Exception as e:
        add(FAIL, "Congress feed", redact(e)[:110])
    try:
        it = insiders.recent_trades(env, g.get("insider_lookback_days", 30))
        add(OK if it else WARN, "Insider feed", f"{len(it)} Form 4 filings" if it else "no rows (may need a paid FMP tier)")
    except Exception as e:
        add(FAIL, "Insider feed", redact(e)[:110])
    try:
        h = news.ticker_headlines(watch[:4], per=1)
        add(OK if h else WARN, "news", f"headlines for {len(h)}/4 sampled tickers")
    except Exception as e:
        add(FAIL, "news", redact(e)[:110])

    from .run import make_broker
    broker = make_broker(cfg)
    may, problems = safety.preflight(broker, g)
    add(OK if may else FAIL, "safety gate", "clear" if may else " | ".join(problems)[:160])
    if hasattr(broker, "summary"):
        s = broker.summary()
        add(OK, "portfolio", f"equity ${s['equity']:.2f} on ${s['deposited']:.2f} in ({s['total_return_pct']:+.2f}%), cash ${s['cash']:.2f}")
    st = state.load()
    add(OK, "budget", f"week {st['week']}: ${st['spent']:.2f} of ${cfg['weekly_budget']:.0f} spent; today {st['orders_today']} buys, {st['sells_today']} sells")

    today = now.date()
    nxt = today
    for _ in range(10):
        if is_trading_day(nxt) and not (nxt == today and now.time() >= close_time(today)):
            break
        nxt = nxt.fromordinal(nxt.toordinal() + 1)
    add(OK, "market", f"today {today} trading={is_trading_day(today)}; next session {nxt} (close {close_time(nxt)} ET)")
    last_holiday = max(HOLIDAYS)
    add(OK if last_holiday > today.isoformat() else WARN, "holiday calendar",
        f"through {last_holiday}" + ("" if last_holiday > today.isoformat() else " — STALE, update HOLIDAYS in agent/broker_sim.py"))

    try:
        out = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/com.finley.stock-agent"],
                             capture_output=True, text=True, timeout=10).stdout
        runs = next((l.split("=")[1].strip() for l in out.splitlines() if "runs =" in l), "?")
        add(OK if out else FAIL, "schedule", f"loaded, {runs} runs so far, every {cfg['run_every_minutes']} min during market hours")
    except Exception:
        add(WARN, "schedule", "LaunchAgent not loaded — double-click autopilot-mac.command")
    try:
        awake = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/com.finley.stock-agent-awake"],
                               capture_output=True, text=True, timeout=10).returncode == 0
        add(OK if awake else WARN, "keep-awake", "installed" if awake else "not installed — a sleeping Mac skips checks (keep-awake-mac.command)")
    except Exception:
        add(WARN, "keep-awake", "unknown")

    bp = backtest.priors()
    add(OK if bp else WARN, "backtest", f"generated {bp['generated']}, stable_ranking={bp.get('stable_ranking')}" if bp else "never run — python3 -m agent.backtest")

    try:
        probe = ROOT / ".write_probe"; probe.write_text("x"); probe.unlink()
        add(OK, "disk", "writable")
    except Exception as e:
        add(FAIL, "disk", redact(e)[:110])

    print("\n  Stock Agent health check —", now.strftime("%Y-%m-%d %H:%M ET"), "\n")
    for status, name, detail in rows:
        print(f"  [{status}] {name:<18} {detail}")
    fails = sum(1 for s, _, _ in rows if s == FAIL)
    warns = sum(1 for s, _, _ in rows if s == WARN)
    print(f"\n  {len(rows) - fails - warns} ok, {warns} warnings, {fails} failures")
    print("  " + ("Ready to trade." if not fails else "NOT ready — fix the failures above.") + "\n")
    return 1 if fails else 0

if __name__ == "__main__":
    sys.exit(main())
