"""Free news layer (yfinance, no key).

ticker_headlines(tickers)  -> {TICKER: [{title, source, when}, ...]}
people_news(names)         -> {"Elon Musk": [{title, source, when, tickers}, ...]}

The brain must cite one of these (or a filing / a number) as `evidence` on every order.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import yfinance as yf

def _ts(v) -> str | None:
    if not v:
        return None
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v, tz=timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    return str(v)[:16]

def _one_ticker(t: str, per: int) -> tuple[str, list[dict]]:
    try:
        items = yf.Ticker(t).news or []
    except Exception:
        return t, []
    rows = []
    for it in items[:per]:
        c = it.get("content") or it          # yfinance >=0.2.5x nests under "content"; older is flat
        title = c.get("title")
        if not title:
            continue
        rows.append({"title": title[:160],
                     "source": ((c.get("provider") or {}).get("displayName")) or it.get("publisher"),
                     "when": _ts(c.get("pubDate") or it.get("providerPublishTime"))})
    return t, rows

def ticker_headlines(tickers: list[str], per: int = 3) -> dict:
    out = {}
    if not tickers:
        return out
    with ThreadPoolExecutor(max_workers=8) as ex:
        for t, rows in ex.map(lambda t: _one_ticker(t, per), tickers):
            if rows:
                out[t] = rows
    return out

def people_news(names: list[str], per: int = 4) -> dict:
    out = {}
    for n in names or []:
        try:
            items = yf.Search(n, news_count=per).news or []
        except Exception:
            continue
        rows = [{"title": i.get("title", "")[:160], "source": i.get("publisher"),
                 "when": _ts(i.get("providerPublishTime")), "tickers": i.get("relatedTickers") or []}
                for i in items[:per] if i.get("title")]
        if rows:
            out[n] = rows
    return out
