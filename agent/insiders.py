"""Corporate insider trades (SEC Form 4) via Financial Modeling Prep.

This is how people like Elon Musk or Jeff Bezos show up in public data: they must file a
Form 4 within 2 business days when they buy or sell shares of a company they're an insider of
(officer, director, >10% holder). It does NOT cover their private holdings or other people's funds.

recent_trades(env, lookback_days) -> [{who, role, ticker, type: 'buy'|'sell', shares, price,
                                       transaction_date, filing_date}]
Names in `followed_people` (config.yaml) are matched case-insensitively as substrings of `who`.
"""
from datetime import date, timedelta
import requests
from . import feeds_cache
from .redact import redact

# Reuse a download for an hour: filings arrive a few times a day, and asking every two minutes used up
# the free FMP quota by late morning. When FMP refuses (quota, outage), serve the last good download
# for up to a day and say how old it is, rather than going blind.
FRESH_S = 3600
STALE_OK_S = 24 * 3600
last_status: str | None = None     # "ok", "cached N min old", "unavailable", or None when there is no key

def recent_trades(env: dict, lookback_days: int = 30) -> list[dict]:
    global last_status
    last_status = None
    key = env.get("fmp_key")
    if not key:
        return []
    cached = feeds_cache.load().get("insiders") or {}
    age = feeds_cache.now() - int(cached.get("fetched_ts") or 0)
    if isinstance(cached.get("rows"), list) and age < FRESH_S:
        rows, last_status = cached["rows"], "ok"
    else:
        try:
            r = requests.get("https://financialmodelingprep.com/stable/insider-trading/latest",
                             params={"apikey": key, "page": 0, "limit": 100}, timeout=30)
            r.raise_for_status()
            rows = r.json()
            if isinstance(rows, list):
                feeds_cache.update("insiders", {"fetched_ts": feeds_cache.now(), "rows": rows})
            last_status = "ok"
        except Exception as e:
            if isinstance(cached.get("rows"), list) and age < STALE_OK_S:
                rows, last_status = cached["rows"], f"cached {age // 60} min old"
                print(f"[insiders] FMP refused ({redact(e)}); using the download from {age // 60} min ago")
            else:
                print("[insiders] no data:", redact(e))
                last_status = "unavailable"
                return []
    out = []
    for row in rows if isinstance(rows, list) else []:
        code = str(row.get("transactionType") or "").strip().upper()
        kind = "buy" if code.startswith("P") else "sell" if code.startswith("S") else "other"
        out.append({
            "who": row.get("reportingName"), "role": row.get("typeOfOwner"),
            "ticker": (row.get("symbol") or "").upper(), "type": kind,
            "shares": row.get("securitiesTransacted"), "price": row.get("price"),
            "transaction_date": row.get("transactionDate"), "filing_date": row.get("filingDate"),
        })
    cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()
    out = [r for r in out if r["ticker"] and r["type"] in ("buy", "sell") and (r.get("filing_date") or "9999")[:10] >= cutoff]
    out.sort(key=lambda r: r.get("filing_date") or "", reverse=True)
    return out

def _followed(who: str | None, followed: list[str]) -> bool:
    return bool(who) and any(f.lower() in who.lower() for f in followed)

def buy_pressure(trades: list[dict], followed: list[str]) -> dict:
    """Tickers ranked by net insider buying. Followed people count 3x."""
    score: dict[str, float] = {}
    for t in trades:
        w = 3.0 if _followed(t["who"], followed) else 1.0
        score[t["ticker"]] = score.get(t["ticker"], 0) + (w if t["type"] == "buy" else -w)
    return dict(sorted(score.items(), key=lambda kv: kv[1], reverse=True))

def by_followed(trades: list[dict], followed: list[str]) -> list[dict]:
    return [t for t in trades if _followed(t["who"], followed)]
