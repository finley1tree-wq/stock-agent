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
from .redact import redact

def recent_trades(env: dict, lookback_days: int = 30) -> list[dict]:
    key = env.get("fmp_key")
    if not key:
        return []
    try:
        r = requests.get("https://financialmodelingprep.com/stable/insider-trading/latest",
                         params={"apikey": key, "page": 0, "limit": 100}, timeout=30)
        r.raise_for_status()
        rows = r.json()
    except Exception as e:
        print("[insiders] no data:", redact(e))
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
