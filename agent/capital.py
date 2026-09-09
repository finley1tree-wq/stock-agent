"""Change how much pretend money the sleeve has, without disturbing anything it has learned.

Editing the ledger by hand is how ledgers get broken. This does it as a real deposit: cash and
`deposited` both rise by the same amount, so the invariant that guards everything —

    cash + cost basis  ==  deposited + realised P/L

— holds before and after, and the change is written into the fill history like any other event.
Positions, journal, decisions, lessons and the trader leaderboard are untouched; only the size
of the account changes, so the track record stays continuous and comparable.

    python -m agent.capital 1000            # top the sleeve up to $1000 of money put in
    python -m agent.capital 1000 --dry-run  # say what it would do, change nothing
"""
import json
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from .broker_sim import PORTFOLIO, ET

def invariant(p: dict) -> float:
    cost = sum(v["qty"] * v["avg_cost"] for v in p.get("positions", {}).values())
    return abs(p["cash"] + cost - (p["deposited"] + p["realized_pnl"]))

def set_deposited(target: float, dry_run: bool = False) -> dict:
    """Top the sleeve up so total money put in equals `target`. Never removes money."""
    if not PORTFOLIO.exists():
        raise SystemExit(f"no ledger at {PORTFOLIO} — nothing to top up")
    p = json.loads(PORTFOLIO.read_text())
    before = invariant(p)
    if before > 1e-6:
        raise SystemExit(f"REFUSING: the ledger is already out of balance by ${before:.6f}. "
                         "Fix that before adding money, or the error is baked in permanently.")
    add = round(float(target) - float(p["deposited"]), 2)
    if add <= 0:
        print(f"deposited is already ${p['deposited']:.2f}; nothing to add "
              f"(this only tops up, it never takes money out)")
        return p
    p["cash"] += add
    p["deposited"] += add
    p.setdefault("fills", []).append({
        "type": "deposit", "usd": add, "date": datetime.now(ET).strftime("%Y-%m-%d %H:%M"),
        "note": f"topped up to ${target:.2f}",
    })
    after = invariant(p)
    if after > 1e-6:
        raise SystemExit(f"REFUSING: this would break the ledger by ${after:.6f}")
    print(f"  added        ${add:,.2f}")
    print(f"  cash         ${p['cash']:,.2f}")
    print(f"  deposited    ${p['deposited']:,.2f}")
    print(f"  positions    {len(p['positions'])} kept, cost basis unchanged")
    print(f"  invariant    {after:.10f} (0 = exact)")
    if dry_run:
        print("  DRY RUN — nothing written")
        return p
    PORTFOLIO.write_text(json.dumps(p, indent=2))
    print(f"  written to   {PORTFOLIO.name}")
    return p

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        raise SystemExit("usage: python -m agent.capital <target_deposited_usd> [--dry-run]")
    set_deposited(float(args[0]), dry_run="--dry-run" in sys.argv)
