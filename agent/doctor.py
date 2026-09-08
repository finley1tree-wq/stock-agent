"""Health check. Run it any time; it changes nothing.

    python -m agent.doctor      (or double-click check.command)

Verifies: keys, feeds, prices, market calendar, ledger integrity, schedule, disk, and the safety gate.
Never prints a key. Exits 1 if anything is broken.
"""
import json, os, subprocess, sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from . import config, prices, politicians, insiders, news, state, safety, backtest, reflect
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

    # Where does it actually run? GitHub Actions (laptop-free) or this Mac's LaunchAgent — but not both.
    def _sh(cmd, t=15):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=t)
            return r.returncode, (r.stdout or "").strip()
        except Exception:
            return 1, ""
    mac_on = _sh(["launchctl", "print", f"gui/{os.getuid()}/com.finley.stock-agent"])[0] == 0
    awake_on = _sh(["launchctl", "print", f"gui/{os.getuid()}/com.finley.stock-agent-awake"])[0] == 0
    cloud_on, cloud_detail = False, ""
    rc, remote = _sh(["git", "-C", str(ROOT), "remote", "get-url", "origin"])
    if rc == 0 and remote:
        repo = remote.split("github.com/")[-1].removesuffix(".git").strip("/:")
        rc2, wf = _sh(["gh", "workflow", "list", "-R", repo], 25)
        if rc2 == 0 and "active" in wf:
            cloud_on = True
            rc3, runs = _sh(["gh", "run", "list", "-R", repo, "--limit", "1",
                             "--json", "status,conclusion,createdAt",
                             "-q", '.[0] | .createdAt + " " + .status + "/" + (.conclusion // "-")'], 25)
            cloud_detail = f"GitHub Actions on {repo}" + (f", last run {runs}" if rc3 == 0 and runs else "")
        elif rc2 == 0:
            cloud_detail = f"workflow found on {repo} but NOT active"
    if cloud_on and mac_on:
        add(FAIL, "where it runs", "BOTH GitHub Actions and this Mac are scheduled — two agents would trade one budget. "
                                  "Turn the Mac off: bash autopilot-mac.command stop")
    elif cloud_on:
        add(OK, "where it runs", cloud_detail + " — laptop can stay off")
        if awake_on:
            add(WARN, "keep-awake", "still installed but unnecessary now that it runs in the cloud (bash keep-awake-mac.command stop)")
    elif mac_on:
        add(OK, "where it runs", f"this Mac's LaunchAgent, every {cfg['run_every_minutes']} min during market hours")
        add(OK if awake_on else WARN, "keep-awake",
            "installed" if awake_on else "not installed — a sleeping Mac skips checks (keep-awake-mac.command)")
    else:
        add(FAIL, "where it runs", "NOTHING is scheduled — " + (cloud_detail or "run push.command for the cloud, or autopilot-mac.command for this Mac"))

    cf = reflect.report(prices.snapshot(config.all_watchlist_tickers(cfg)) if False else {})
    n_dec = cf.get("decisions_recorded", 0)
    add(OK, "self-learning", f"{n_dec} decisions recorded" + (f", {cf['decisions_graded']} graded, regret {cf['avg_regret_pct']}%" if cf.get("decisions_graded") else " (grading starts after the first full day)"))

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
