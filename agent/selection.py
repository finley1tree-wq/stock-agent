"""Entry culls: two habits that lost money, switched off by config (guardrails in config.yaml).

Post-mortem over 797 closed round trips, 2026-09-08..09-28, after costs, fake AMD fill removed:

    entries at 14:00-15:59 ET              -$365 over 146 trips, 42-45% of them won
    momentum-only entries, all sources     -$88; win rate 63%, then 55%, then 49%, week by week
      ...by the rules-only autopilot       -$164 after costs
    kept: entries at 09:00-10:59 ET +$592; congress-backed +$215; insider-backed +$97;
          take-profit exits +$2,727
    the whole book                          +$286, t = 0.58

Nothing in that table is proven - the whole book is indistinguishable from zero. These cuts are made
only because a trade that shows no edge still pays the spread twice, so not taking it saves the cost.
Exits are untouched: stops, targets, the time stop and the session flatten all keep working.

Pure standard library, so it can be tested without the network, a broker or the model.
"""
from datetime import datetime, time

# Tags that say HOW an entry came about (which mechanism placed it), not WHY it was worth taking.
# Strip these and an entry whose remaining reasons are exactly {"momentum"} is momentum-only: the
# autopilot's ["momentum", "autopilot"], a dip order's ["momentum", "dip_entry"], or a model buy
# tagged only "momentum".
MECHANICS = {"autopilot", "standing_order", "patience", "dip_entry", "auto_bracket", "risk_management",
             "intraday_limit", "time_stop", "session_close"}


def momentum_only(signals) -> bool:
    real = {s for s in (signals or []) if isinstance(s, str)} - MECHANICS
    return real == {"momentum"}


def entry_blocked(signals, g: dict) -> str | None:
    """Why a NEW entry carrying these signals may not be taken, or None if it may."""
    if not g.get("allow_momentum_only_entries", True) and momentum_only(signals):
        return "momentum-only entry (guardrails.allow_momentum_only_entries is false)"
    return None


def past_entry_time(now: datetime, g: dict) -> bool:
    """At or after guardrails.no_new_entries_after_et ("HH:MM", New York time). Off when unset."""
    s = str(g.get("no_new_entries_after_et") or "").strip()
    if not s:
        return False
    try:
        h, m = s.split(":")
        cut = time(int(h), int(m))
    except ValueError:
        return False
    return now.time() >= cut
