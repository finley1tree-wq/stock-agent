"""Recent congressional stock trades (STOCK Act disclosures).

Sources, tried in order:
  1. Quiver Quantitative  (QUIVER_API_KEY)  — paid, cleanest data
  2. Financial Modeling Prep (FMP_API_KEY)  — paid tier only (free tier returns 402)
  3. CongressWatch + House Clerk            — FREE, no key. congresswatch.us publishes a daily JSON of House + Senate
     trades built from the official filings; the House Clerk's yearly index gives the filing (disclosure) date for
     House rows by DocID. Senate rows carry only the transaction date. Verified live 2026-09-06.
Returns a normalized list of dicts:
  {who, party, chamber, ticker, type: 'buy'|'sell', amount, transaction_date, disclosure_date}
Note: filings can lag the actual trade by up to 45 days. Presidents/family are NOT in this data.
Public-records use only (5 U.S.C. 13107(c) forbids commercial use of these disclosures).
"""
import io, json, re, zipfile
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from pathlib import Path
import requests
from .redact import redact

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache"
UA = {"User-Agent": "stock-agent/1.0 (personal research)"}
CW_URL = "https://www.congresswatch.us/data/trades.json"
HOUSE_ZIP = "https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{year}FD.zip"

last_source: str | None = None   # which source produced the rows of the last call
last_errors: list[str] = []

def _norm_type(s: str) -> str:
    s = (s or "").lower()
    return "buy" if "purchase" in s or s.startswith("buy") else "sell"

def _quiver(key: str) -> list[dict]:
    r = requests.get("https://api.quiverquant.com/beta/live/congresstrading",
                     headers={"accept": "application/json", "Authorization": f"Bearer {key}"}, timeout=30)
    r.raise_for_status()
    out = []
    for row in r.json():
        out.append({
            "who": row.get("Representative") or row.get("Name"),
            "party": row.get("Party"),
            "chamber": row.get("House"),
            "ticker": (row.get("Ticker") or "").upper(),
            "type": _norm_type(row.get("Transaction")),
            "amount": row.get("Range") or row.get("Amount"),
            "transaction_date": row.get("TransactionDate"),
            "disclosure_date": row.get("ReportDate"),
        })
    return out

def _fmp(key: str) -> list[dict]:
    out = []
    for chamber, path in (("Senate", "senate-latest"), ("House", "house-latest")):
        r = requests.get(f"https://financialmodelingprep.com/stable/{path}", params={"apikey": key, "page": 0, "limit": 100}, timeout=30)
        r.raise_for_status()
        for row in r.json():
            out.append({
                "who": f"{row.get('firstName','')} {row.get('lastName','')}".strip() or row.get("office"),
                "party": row.get("party"),
                "chamber": chamber,
                "ticker": (row.get("symbol") or "").upper(),
                "type": _norm_type(row.get("type")),
                "amount": row.get("amount"),
                "transaction_date": row.get("transactionDate"),
                "disclosure_date": row.get("disclosureDate"),
            })
    return out

# ---- free source: CongressWatch aggregate + House Clerk index ------------------------------------
def _get_cached(url: str, name: str) -> bytes:
    """Conditional GET (ETag / Last-Modified); serves the cached body on 304. Cache lives in .cache/ (gitignored)."""
    CACHE.mkdir(exist_ok=True)
    meta, body = CACHE / f"{name}.meta.json", CACHE / f"{name}.bin"
    h = dict(UA)
    if meta.exists() and body.exists():
        try:
            m = json.loads(meta.read_text())
            if m.get("etag"): h["If-None-Match"] = m["etag"]
            if m.get("last_modified"): h["If-Modified-Since"] = m["last_modified"]
        except Exception:
            pass
    r = requests.get(url, headers=h, timeout=90)
    if r.status_code == 304 and body.exists():
        return body.read_bytes()
    r.raise_for_status()
    body.write_bytes(r.content)
    meta.write_text(json.dumps({"etag": r.headers.get("ETag"), "last_modified": r.headers.get("Last-Modified")}))
    return r.content

def _house_filing_dates(year: int) -> dict[str, str]:
    """DocID -> ISO filing date for House Periodic Transaction Reports (FilingType P)."""
    try:
        raw = _get_cached(HOUSE_ZIP.format(year=year), f"house_{year}")
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            xml = z.read(f"{year}FD.xml")
    except Exception as e:
        last_errors.append(f"house-clerk {year}: {redact(e)}")
        return {}
    out = {}
    for m in ET.fromstring(xml).findall("Member"):
        if m.findtext("FilingType") == "P":
            try:
                out[m.findtext("DocID")] = datetime.strptime(m.findtext("FilingDate"), "%m/%d/%Y").date().isoformat()
            except Exception:
                continue
    return out

def _congresswatch() -> list[dict]:
    rows = json.loads(_get_cached(CW_URL, "congresswatch"))
    today = date.today()
    fd = _house_filing_dates(today.year)
    if today.month <= 2:
        fd.update(_house_filing_dates(today.year - 1))
    out = []
    for r in rows if isinstance(rows, list) else []:
        ticker = (r.get("ticker") or "").strip().upper()
        t = (r.get("type") or "")
        if not ticker or ticker in ("--", "N/A") or not t or "exchange" in t.lower():
            continue
        doc = (r.get("ptr_link") or "").rsplit("/", 1)[-1].replace(".pdf", "").rstrip("/")
        tx = r.get("transaction_date") or None
        if tx and tx > (today + timedelta(days=1)).isoformat():   # typos like 2026-12-26 in a September filing
            tx = None
        out.append({
            "who": r.get("member_name"), "party": r.get("party"), "chamber": r.get("chamber"),
            "ticker": ticker, "type": _norm_type(t), "amount": r.get("amount"),
            "transaction_date": tx, "disclosure_date": fd.get(doc),   # Senate rows: None (only the trade date is published here)
            "owner": r.get("owner"), "source": "congresswatch",
        })
    return out

def _anchor(r: dict) -> str:
    return r.get("disclosure_date") or r.get("transaction_date") or ""

def recent_trades(env: dict, lookback_days: int = 30) -> list[dict]:
    global last_source, last_errors
    last_errors = []
    rows: list[dict] = []
    last_source = None
    if env.get("quiver_key"):
        try: rows = _quiver(env["quiver_key"]); last_source = "quiver" if rows else None
        except Exception as e: last_errors.append(f"quiver: {redact(e)}")
    if not rows and env.get("fmp_key"):
        try: rows = _fmp(env["fmp_key"]); last_source = "fmp" if rows else None
        except Exception as e: last_errors.append(f"fmp: {redact(e)}")
    if not rows:
        try: rows = _congresswatch(); last_source = "congresswatch" if rows else None
        except Exception as e: last_errors.append(f"congresswatch: {redact(e)}")
    cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()
    rows = [r for r in rows if r["ticker"] and _anchor(r) >= cutoff]
    rows.sort(key=_anchor, reverse=True)
    if last_errors and not rows:
        print("[politicians] no data:", "; ".join(last_errors))
    elif last_errors:
        print("[politicians] fell back:", "; ".join(last_errors), f"-> using {last_source}")
    return rows

def buy_pressure(trades: list[dict], followed: list[str], skill: dict | None = None) -> dict:
    """Tickers ranked by net recent buying.

    Not every disclosure is worth the same. Names you chose to follow count 3x, and `skill`
    (from traders.py) tilts the rest by what that member's past filings were actually worth
    against the index — so a member whose disclosed buys have trailed SPY counts for less than
    one whose have beaten it. Without that, following Congress is following an average, and the
    average includes everyone who is bad at this.
    """
    score: dict[str, float] = {}
    for t in trades:
        who = t.get("who") or ""
        w = 3.0 if who and any(f.lower() in who.lower() for f in followed) else 1.0
        if skill:
            w *= float(skill.get(who, 1.0))
        score[t["ticker"]] = score.get(t["ticker"], 0) + (w if t["type"] == "buy" else -w)
    return dict(sorted(score.items(), key=lambda kv: kv[1], reverse=True))

def who_bought(trades: list[dict], ticker: str, limit: int = 4) -> list[dict]:
    """The named people behind a ticker's pressure, so the evidence can say who rather than how much."""
    out = []
    for t in trades:
        if t["ticker"] == ticker and t.get("who"):
            out.append({"who": t["who"], "type": t["type"], "amount": t.get("amount"),
                        "disclosed": t.get("disclosure_date") or t.get("transaction_date")})
        if len(out) >= limit:
            break
    return out
