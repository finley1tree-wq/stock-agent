"""OpenInsider backup for the insider feed: parses the real table and takes over when FMP refuses.

Plain python3, no pytest: prints PASS/FAIL per check and exits 1 on any failure. No network - the
FMP call, the OpenInsider call and the cache file are all replaced. The sample page under
tests/fixtures is a trimmed copy of the live OpenInsider screener captured on 2026-09-15.

    python3 tests/test_openinsider.py
"""
import builtins
import re
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import feeds_cache, insiders  # noqa: E402

FAILS = 0
CHECKS = 0
SAMPLE = (ROOT / "tests" / "fixtures" / "openinsider_sample.html").read_text()


def check(name, ok, detail=""):
    global FAILS, CHECKS
    CHECKS += 1
    if not ok:
        FAILS += 1
    print(("PASS  " if ok else "FAIL  ") + name + (f"  ({detail})" if detail and not ok else ""))


def quiet(fn, *a, **k):
    real = builtins.print
    builtins.print = lambda *x, **y: None
    try:
        return fn(*a, **k)
    finally:
        builtins.print = real


def fresh_cache():
    feeds_cache.FILE = Path(tempfile.mkdtemp()) / "feeds_cache.json"


def set_clock(ts):
    feeds_cache.now = lambda: ts


class Resp:
    def __init__(self, status=200, rows=None, text=""):
        self.status_code, self.rows, self.text = status, rows, text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"{self.status_code} Client Error for url: https://financialmodelingprep.com/x?apikey=SECRETKEY123")

    def json(self):
        return self.rows


class Router:
    """requests.get stand-in: FMP and OpenInsider each answer as configured, and calls are counted."""
    def __init__(self, fmp="429", oi="ok", oi_text=None):
        self.fmp, self.oi, self.oi_text = fmp, oi, oi_text if oi_text is not None else SAMPLE
        self.calls = {"fmp": 0, "oi": 0}

    def __call__(self, url, params=None, headers=None, timeout=None, **kw):
        if "financialmodelingprep" in url:
            self.calls["fmp"] += 1
            return Resp(429) if self.fmp == "429" else Resp(200, rows=[])
        if "openinsider" in url:
            self.calls["oi"] += 1
            return Resp(500) if self.oi == "fail" else Resp(200, text=self.oi_text)
        raise AssertionError("unexpected url " + url)


ENV = {"fmp_key": "SECRETKEY123"}


def test_parser():
    rows = insiders.parse_openinsider(SAMPLE)
    check("real sample: 4 rows parsed", len(rows) == 4, str(len(rows)))
    check("real sample: 2 buys and 2 sells", sorted(r["type"] for r in rows) == ["buy", "buy", "sell", "sell"], str([r["type"] for r in rows]))
    check("tickers are clean upper-case symbols", all(re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", r["ticker"]) for r in rows), str([r["ticker"] for r in rows]))
    check("prices are numbers", all(isinstance(r["price"], float) and r["price"] > 0 for r in rows), str([r["price"] for r in rows]))
    check("shares are positive numbers", all(isinstance(r["shares"], float) and r["shares"] > 0 for r in rows), str([r["shares"] for r in rows]))
    check("dates are YYYY-MM-DD", all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", r["filing_date"]) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", r["transaction_date"]) for r in rows))
    check("insider names present", all(r["who"] for r in rows))
    check("same keys as the FMP rows", all(set(r) == {"who", "role", "ticker", "type", "shares", "price", "transaction_date", "filing_date"} for r in rows))
    check("no table: nothing, no crash", insiders.parse_openinsider("<html>blocked</html>") == [])
    check("empty page: nothing, no crash", insiders.parse_openinsider("") == [] and insiders.parse_openinsider(None) == [])
    header_only = re.sub(r"</tr>.*</table>", "</tr></table>", SAMPLE, count=1, flags=re.S)
    check("header with no rows: nothing", insiders.parse_openinsider(header_only) == [])
    no_price_col = SAMPLE.replace(">Price<", ">Cost<", 1)
    check("a missing required column: nothing rather than wrong data", insiders.parse_openinsider(no_price_col) == [])


def recent_filings():
    # the fixture's filing dates are fixed; rewrite them to today so the 30-day cutoff keeps them
    return re.sub(r"\d{4}-\d{2}-\d{2}( \d{2}:\d{2}:\d{2})?", date.today().isoformat() + r"\1", SAMPLE)


def test_fallback():
    t0 = 1_800_000_000
    fresh_cache(); set_clock(t0)
    rt = Router(fmp="429", oi="ok", oi_text=recent_filings())
    insiders.requests.get = rt
    out = quiet(insiders.recent_trades, ENV, 30)
    check("FMP refused: OpenInsider rows are used", len(out) == 4, str(len(out)))
    check("FMP refused: status names the backup", insiders.last_status == "ok (openinsider)", str(insiders.last_status))
    check("FMP refused: one FMP try, one OpenInsider fetch", rt.calls == {"fmp": 1, "oi": 1}, str(rt.calls))

    set_clock(t0 + 30 * 60)
    out2 = quiet(insiders.recent_trades, ENV, 30)
    check("30 min later: OpenInsider served from cache, not refetched", len(out2) == 4 and rt.calls["oi"] == 1, str(rt.calls))

    set_clock(t0 + 61 * 60)
    quiet(insiders.recent_trades, ENV, 30)
    check("after an hour: OpenInsider fetched again", rt.calls["oi"] == 2, str(rt.calls))

    # both refuse, but FMP had a good download 2h ago
    fresh_cache(); set_clock(t0)
    feeds_cache.update("insiders", {"fetched_ts": t0 - 7200, "rows": [
        {"reportingName": "Jane Director", "typeOfOwner": "director", "symbol": "AAPL", "transactionType": "P-Purchase",
         "securitiesTransacted": 10, "price": 330, "transactionDate": date.today().isoformat(), "filingDate": date.today().isoformat()}]})
    rt = Router(fmp="429", oi="fail")
    insiders.requests.get = rt
    out3 = quiet(insiders.recent_trades, ENV, 30)
    check("both refused, FMP cache 2h old: cached rows served", len(out3) == 1 and out3[0]["ticker"] == "AAPL", str(out3))
    check("both refused: status says how old", insiders.last_status == "cached 120 min old", str(insiders.last_status))

    fresh_cache(); set_clock(t0)
    insiders.requests.get = Router(fmp="429", oi="fail")
    out4 = quiet(insiders.recent_trades, ENV, 30)
    check("both refused, nothing cached: nothing, unavailable", out4 == [] and insiders.last_status == "unavailable", str(insiders.last_status))

    fresh_cache(); set_clock(t0)
    rt = Router(fmp="429", oi="ok", oi_text="<html>Access denied</html>")
    insiders.requests.get = rt
    out5 = quiet(insiders.recent_trades, ENV, 30)
    check("OpenInsider page unreadable: not cached, unavailable", out5 == [] and insiders.last_status == "unavailable" and "insiders_openinsider" not in feeds_cache.load())

    printed = []
    real = builtins.print
    builtins.print = lambda *a, **k: printed.append(" ".join(str(x) for x in a))
    try:
        fresh_cache(); set_clock(t0)
        insiders.requests.get = Router(fmp="429", oi="ok", oi_text=recent_filings())
        insiders.recent_trades(ENV, 30)
    finally:
        builtins.print = real
    check("the FMP key never appears in the log", not any("SECRETKEY123" in p for p in printed), str(printed))

    fresh_cache(); set_clock(t0)
    rt = Router(fmp="429", oi="ok")
    insiders.requests.get = rt
    out6 = quiet(insiders.recent_trades, {}, 30)
    check("no FMP key: unchanged behaviour, no requests at all", out6 == [] and rt.calls == {"fmp": 0, "oi": 0}, str(rt.calls))


def main():
    test_parser()
    test_fallback()
    print(f"\n{CHECKS - FAILS}/{CHECKS} checks passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
