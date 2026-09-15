"""Insider and congressional feeds must survive the FMP free-tier quota.

Plain python3, no pytest: prints PASS/FAIL per check and exits 1 on any failure. Network is never
touched - requests.get, the CongressWatch source and the cache file are all replaced.

    python3 tests/test_feeds.py
"""
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import feeds_cache, insiders, politicians  # noqa: E402

FAILS = 0
CHECKS = 0


def check(name, ok, detail=""):
    global FAILS, CHECKS
    CHECKS += 1
    if not ok:
        FAILS += 1
    print(("PASS  " if ok else "FAIL  ") + name + (f"  ({detail})" if detail and not ok else ""))


class Resp:
    def __init__(self, rows=None, status=200):
        self.rows, self.status_code = rows, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"{self.status_code} Client Error: Too Many Requests for url: "
                               "https://financialmodelingprep.com/stable/x?apikey=SECRETKEY123")

    def json(self):
        return self.rows


TODAY = date.today().isoformat()
ROWS = [
    {"reportingName": "Jane Director", "typeOfOwner": "director", "symbol": "aapl", "transactionType": "P-Purchase",
     "securitiesTransacted": 100, "price": 330.0, "transactionDate": TODAY, "filingDate": TODAY},
    {"reportingName": "John Officer", "typeOfOwner": "officer", "symbol": "MSFT", "transactionType": "S-Sale",
     "securitiesTransacted": 50, "price": 505.0, "transactionDate": TODAY, "filingDate": TODAY},
]


class FakeGet:
    def __init__(self):
        self.calls, self.mode = 0, "ok"

    def __call__(self, url, params=None, timeout=None, **kw):
        self.calls += 1
        return Resp(ROWS) if self.mode == "ok" else Resp(None, 429)


def fresh_cache():
    feeds_cache.FILE = Path(tempfile.mkdtemp()) / "feeds_cache.json"


def set_clock(ts):
    feeds_cache.now = lambda: ts


ENV = {"fmp_key": "SECRETKEY123"}


def test_insiders():
    fresh_cache()
    get = FakeGet()
    insiders.requests.get = get
    t0 = 1_800_000_000
    set_clock(t0)

    out = insiders.recent_trades(ENV, 30)
    check("first call downloads once", get.calls == 1, f"calls={get.calls}")
    check("first call returns parsed buy and sell rows", [r["type"] for r in out] == ["buy", "sell"] or sorted(r["type"] for r in out) == ["buy", "sell"], str(out))
    check("first call status is ok", insiders.last_status == "ok", str(insiders.last_status))
    check("download is written to the cache", isinstance(feeds_cache.load().get("insiders", {}).get("rows"), list))
    check("tickers are upper-cased", {r["ticker"] for r in out} == {"AAPL", "MSFT"}, str(out))

    set_clock(t0 + 59 * 60)
    out2 = insiders.recent_trades(ENV, 30)
    check("within the hour: no new request", get.calls == 1, f"calls={get.calls}")
    check("within the hour: same rows, status ok", len(out2) == 2 and insiders.last_status == "ok")

    set_clock(t0 + 61 * 60)
    insiders.recent_trades(ENV, 30)
    check("after an hour: downloads again", get.calls == 2, f"calls={get.calls}")

    get.mode = "429"
    set_clock(t0 + 3 * 3600)
    printed = []
    real_print = __builtins__.print if hasattr(__builtins__, "print") else print
    import builtins
    builtins.print = lambda *a, **k: printed.append(" ".join(str(x) for x in a))
    try:
        out3 = insiders.recent_trades(ENV, 30)
    finally:
        builtins.print = real_print
    # the cache was last refreshed by the download at t0+61min, so three hours in it is 119 minutes old
    check("quota refused, cache ~2h old: serves cached rows", len(out3) == 2, str(out3))
    check("quota refused: status says how old", insiders.last_status == "cached 119 min old", str(insiders.last_status))
    check("quota refused: the API key is not printed", not any("SECRETKEY123" in line for line in printed), str(printed))

    set_clock(t0 + 26 * 3600)
    out4 = insiders.recent_trades(ENV, 30)
    check("quota refused, cache over a day old: nothing", out4 == [], str(out4))
    check("quota refused, cache too old: status unavailable", insiders.last_status == "unavailable", str(insiders.last_status))

    fresh_cache()
    set_clock(t0)
    out5 = insiders.recent_trades(ENV, 30)
    check("quota refused with no cache: nothing, unavailable", out5 == [] and insiders.last_status == "unavailable")

    calls = get.calls
    out6 = insiders.recent_trades({}, 30)
    check("no key: nothing, no request, no status", out6 == [] and get.calls == calls and insiders.last_status is None)

    fresh_cache()
    feeds_cache.FILE.write_text("[1, 2, 3]")
    get.mode = "ok"
    out7 = insiders.recent_trades(ENV, 30)
    check("a corrupt cache file is ignored, not fatal", len(out7) == 2 and insiders.last_status == "ok")


def test_politicians():
    fresh_cache()
    t0 = 1_800_000_000
    set_clock(t0)
    state = {"fmp": 0, "cw": 0}

    def fmp_refuses(key):
        state["fmp"] += 1
        raise RuntimeError("402 Client Error: Payment Required for url: https://financialmodelingprep.com/stable/senate-latest?apikey=SECRETKEY123")

    def cw(*a, **k):
        state["cw"] += 1
        return [{"who": "Rep A", "party": "D", "chamber": "House", "ticker": "NVDA", "type": "buy",
                 "amount": "$1,001 - $15,000", "transaction_date": TODAY, "disclosure_date": TODAY}]

    politicians._fmp = fmp_refuses
    politicians._congresswatch = cw
    import builtins
    real_print = builtins.print
    builtins.print = lambda *a, **k: None
    try:
        rows = politicians.recent_trades(ENV, 30)
        check("FMP refused: falls back to CongressWatch rows", len(rows) == 1 and politicians.last_source == "congresswatch", str(rows))
        check("FMP refused: one FMP attempt", state["fmp"] == 1, str(state))
        retry = int(feeds_cache.load().get("fmp_congress_retry_ts") or 0)
        check("FMP refused: retry scheduled 6 hours out", retry == t0 + 6 * 3600, str(retry))

        set_clock(t0 + 120)
        politicians.recent_trades(ENV, 30)
        check("two minutes later: FMP is not asked again", state["fmp"] == 1, str(state))
        check("two minutes later: CongressWatch still serves", state["cw"] == 2, str(state))

        set_clock(t0 + 6 * 3600 + 1)
        politicians.recent_trades(ENV, 30)
        check("after 6 hours: FMP is tried again", state["fmp"] == 2, str(state))

        fresh_cache()
        set_clock(t0)
        politicians.recent_trades({}, 30)
        check("no FMP key: FMP never called", state["fmp"] == 2, str(state))
    finally:
        builtins.print = real_print


def test_run_status_line():
    src = (ROOT / "agent" / "run.py").read_text()
    check("run.py reports the insider feed's own status", 'feed_status["insiders"] = insiders.last_status or' in src)


def main():
    test_insiders()
    test_politicians()
    test_run_status_line()
    print(f"\n{CHECKS - FAILS}/{CHECKS} checks passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
