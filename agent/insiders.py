"""Corporate insider trades (SEC Form 4) via Financial Modeling Prep, with OpenInsider as the free backup.

This is how people like Elon Musk or Jeff Bezos show up in public data: they must file a
Form 4 within 2 business days when they buy or sell shares of a company they're an insider of
(officer, director, >10% holder). It does NOT cover their private holdings or other people's funds.

recent_trades(env, lookback_days) -> [{who, role, ticker, type: 'buy'|'sell', shares, price,
                                       transaction_date, filing_date}]
Names in `followed_people` (config.yaml) are matched case-insensitively as substrings of `who`.
"""
import html as _html
import re
from datetime import date, timedelta
import requests
from . import feeds_cache
from .redact import redact

# OpenInsider republishes the same SEC Form 4 filings as a public table, free, with no key and no
# daily quota. It is the backup when FMP refuses (its free plan ran out by late morning on
# 2026-09-15), so the insider signal no longer depends on FMP's quota. The SEC's own EDGAR endpoints
# were tried first and refuse this kind of automated request ("undeclared automated tool").
OPENINSIDER_URL = "http://openinsider.com/screener"
OI_HEADERS = {"User-Agent": "Mozilla/5.0 (stock-agent personal research)"}

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
            backup = _openinsider_cached(lookback_days)
            if backup:
                print(f"[insiders] FMP refused ({redact(e)}); using OpenInsider ({len(backup)} rows)")
                last_status = "ok (openinsider)"
                return _finish(backup, lookback_days)
            if isinstance(cached.get("rows"), list) and age < STALE_OK_S:
                rows, last_status = cached["rows"], f"cached {age // 60} min old"
                print(f"[insiders] FMP and OpenInsider refused ({redact(e)}); using the download from {age // 60} min ago")
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
    return _finish(out, lookback_days)


def _finish(out: list[dict], lookback_days: int) -> list[dict]:
    cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()
    out = [r for r in out if r["ticker"] and r["type"] in ("buy", "sell") and (r.get("filing_date") or "9999")[:10] >= cutoff]
    out.sort(key=lambda r: r.get("filing_date") or "", reverse=True)
    return out


def _cell(c: str) -> str:
    return _html.unescape(re.sub(r"<[^>]+>", "", c)).replace("\xa0", " ").strip()


def _num(v: str):
    v = re.sub(r"[^0-9.\-]", "", v or "")
    try:
        return float(v) if v not in ("", "-", ".") else None
    except ValueError:
        return None


def parse_openinsider(page: str) -> list[dict]:
    """The screener's results table -> the same row shape recent_trades returns.

    Columns: X, Filing Date, Trade Date, Ticker, Company, Insider, Title, Trade Type, Price, Qty,
    Owned, dOwn, Value, ... Located by header name, so a reordered table still parses."""
    m = re.search(r'<table[^>]*class="tinytable"[^>]*>(.*?)</table>', page or "", re.S)
    if not m:
        return []
    trs = re.findall(r"<tr[^>]*>(.*?)</tr>", m.group(1), re.S)
    if not trs:
        return []
    head = [_cell(h).lower() for h in re.findall(r"<th[^>]*>(.*?)</th>", trs[0], re.S)]
    col = {name: head.index(name) for name in ("filing date", "trade date", "ticker", "insider name", "title",
                                               "trade type", "price", "qty") if name in head}
    if len(col) < 8:
        return []
    out = []
    for tr in trs[1:]:
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if len(tds) <= max(col.values()):
            continue
        link = re.search(r'href="/([A-Za-z][A-Za-z0-9.\-]{0,9})"', tds[col["ticker"]])
        ticker = (link.group(1) if link else _cell(tds[col["ticker"]]).split()[-1] if _cell(tds[col["ticker"]]) else "").upper()
        code = _cell(tds[col["trade type"]]).upper()
        kind = "buy" if code.startswith("P") else "sell" if code.startswith("S") else "other"
        qty = _num(_cell(tds[col["qty"]]))
        out.append({
            "who": _cell(tds[col["insider name"]]), "role": _cell(tds[col["title"]]),
            "ticker": ticker if re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", ticker or "") else "",
            "type": kind, "shares": abs(qty) if qty is not None else None, "price": _num(_cell(tds[col["price"]])),
            "transaction_date": _cell(tds[col["trade date"]])[:10], "filing_date": _cell(tds[col["filing date"]])[:10],
        })
    return out


def _openinsider_cached(lookback_days: int) -> list[dict]:
    """OpenInsider's latest 100 Form 4 purchases and sales, reused for an hour like the FMP download."""
    cached = feeds_cache.load().get("insiders_openinsider") or {}
    if isinstance(cached.get("rows"), list) and feeds_cache.now() - int(cached.get("fetched_ts") or 0) < FRESH_S:
        return cached["rows"]
    try:
        r = requests.get(OPENINSIDER_URL, headers=OI_HEADERS, timeout=30, params={
            "fd": min(max(int(lookback_days), 1), 30), "xp": 1, "xs": 1, "sortcol": 0, "cnt": 100, "page": 1})
        r.raise_for_status()
        rows = parse_openinsider(r.text)
    except Exception as e:
        print("[insiders] OpenInsider no data:", redact(e))
        return cached["rows"] if isinstance(cached.get("rows"), list) and feeds_cache.now() - int(cached.get("fetched_ts") or 0) < STALE_OK_S else []
    if rows:
        feeds_cache.update("insiders_openinsider", {"fetched_ts": feeds_cache.now(), "rows": rows})
    return rows

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
