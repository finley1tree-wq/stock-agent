"""Tracks this week's and today's activity. Stored in state.json.

  week / spent / by_ticker / orders        — reset every Monday (ISO week, New York time)
  day / spent_today / orders_today / sells_today / sold_today — reset every trading day
"""
import json
from datetime import date, datetime
from zoneinfo import ZoneInfo
from pathlib import Path

STATE = Path(__file__).resolve().parent.parent / "state.json"
ET = ZoneInfo("America/New_York")

def today_et() -> date:
    return datetime.now(ET).date()

def week_key(d: date | None = None) -> str:
    d = d or today_et()
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"

def load() -> dict:
    s = json.loads(STATE.read_text()) if STATE.exists() else {}
    if s.get("week") != week_key():
        s = {"week": week_key(), "spent": 0.0, "by_ticker": {}, "orders": []}
    s.setdefault("by_ticker", {})
    s.setdefault("orders", [])
    d = today_et().isoformat()
    if s.get("day") != d:
        s.update({"day": d, "spent_today": 0.0, "orders_today": 0, "sells_today": 0, "sold_today": []})
    s.setdefault("sells_today", 0)
    s.setdefault("sold_today", [])
    s.setdefault("sold_ts", {})
    return s

def record_order(s: dict, ticker: str, usd: float, rec: dict) -> None:
    s["spent"] = round(s["spent"] + usd, 2)
    s["spent_today"] = round(s.get("spent_today", 0.0) + usd, 2)
    s["orders_today"] = int(s.get("orders_today", 0)) + 1
    s["by_ticker"][ticker] = round(s["by_ticker"].get(ticker, 0.0) + usd, 2)
    s["orders"].append(rec)

def record_sell(s: dict, ticker: str, rec: dict, proceeds: float = 0.0) -> None:
    """A sell returns its proceeds to the week's allowance.

    weekly_budget is a limit on NEW money entering the market, not on how many times the same
    dollar may be used. Without this, selling frees cash but not budget room, so the agent can
    exit a position and then be unable to buy anything with the proceeds - it can only ever buy
    and hold until Monday.
    """
    s["sells_today"] = int(s.get("sells_today", 0)) + 1
    if ticker not in s["sold_today"]:
        s["sold_today"].append(ticker)
    # when it was sold, so a cooldown can replace the all-day ban on re-entry
    s.setdefault("sold_ts", {})[ticker] = int(datetime.now(ET).timestamp())
    p = max(0.0, float(proceeds or 0.0))
    s["spent"] = round(max(0.0, s.get("spent", 0.0) - p), 2)
    s["spent_today"] = round(max(0.0, s.get("spent_today", 0.0) - p), 2)
    if ticker in s.get("by_ticker", {}):                      # frees the per-ticker room it gave back
        s["by_ticker"][ticker] = round(max(0.0, s["by_ticker"][ticker] - p), 2)
        if s["by_ticker"][ticker] <= 0:
            s["by_ticker"].pop(ticker, None)
    s["orders"].append(rec)

def save(s: dict) -> None:
    STATE.write_text(json.dumps(s, indent=2))
