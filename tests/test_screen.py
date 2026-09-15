"""Unit tests for the instrument screen (agent/instruments.py) and its on-disk verdict cache.

Plain python3, no network: yfinance is replaced by a fake whose .info dicts are controlled here, and
agent.instruments.CACHE is pointed at a temp file, so the committed instruments.json is never written.

    python3 tests/test_screen.py      # prints PASS/FAIL per check, exits 1 on any failure
"""
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import instruments  # noqa: E402

RESULTS = []

def ok(name, cond, detail=""):
    RESULTS.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond or not detail else f"  -> {detail}"))


# ---------------------------------------------------------------- fake yfinance
def eq(name, price, vol):
    return {"quoteType": "EQUITY", "longName": name, "currentPrice": price, "averageVolume": vol}

INFO = {
    "THIN":  eq("Thin Corp", 10.0, 1_000_000),               # $10M a day
    "EDGE":  eq("Edge Corp", 20.0, 1_000_000),               # exactly $20M a day
    "ABOVE": eq("Above Corp", 50.0, 1_000_000),              # $50M a day
    "PENNY": eq("Penny Corp", 4.99, 10_000_000),             # $49.9M a day but under $5
    # HLI: 876k shares is under any 1M share floor, but ~$120M a day
    "HLI":   eq("Houlihan Lokey, Inc.", 137.0, 876_000),
    "TPL":   eq("Texas Pacific Land Corporation", 365.0, 372_000),
    # names the old share floor let through
    "FLD":   eq("Fold Holdings, Inc.", 0.52, 400_000),       # $0.2M
    "ALP":   eq("Alpha Compute Corp", 4.16, 2_000_000),      # $8.3M, and under $5
    "MAIA":  eq("MAIA Biotechnology, Inc.", 1.39, 500_000),  # $0.7M
    "GRNT":  eq("Granite Ridge Resources, Inc.", 5.12, 1_500_000),  # $7.7M, price passes
    "DGICA": eq("Donegal Group Inc.", 15.0, 150_000),        # $2.25M, price passes
    "ETFTINY": {"quoteType": "ETF", "longName": "Tiny Thematic ETF", "regularMarketPrice": 3.0, "averageVolume": 1_000},
    "FUNDNOVOL": {"quoteType": "MUTUALFUND", "longName": "Some Index Fund"},
    "GOOGN": {"quoteType": "EQUITY", "longName": "Alphabet Inc. Preferred Depositary Shares",
              "currentPrice": 180.0, "averageVolume": 5_000_000},
    "XYZW":  {"quoteType": "EQUITY", "longName": "XYZ Acquisition Corp Warrants", "currentPrice": 20.0,
              "averageVolume": 5_000_000},
    "WTYPE": {"quoteType": "WARRANT", "shortName": "Something WT", "currentPrice": 20.0, "averageVolume": 5_000_000},
    "NOPRICE": {"quoteType": "EQUITY", "longName": "No Price Corp", "averageVolume": 100},
    "NOVOL": {"quoteType": "EQUITY", "longName": "No Volume Corp", "currentPrice": 50.0},
    "EMPTY": {},
    "NONEINFO": None,
    "BRK-B": eq("Berkshire Hathaway Inc.", 480.0, 4_000_000),
    "GENERIC": eq("Generic Big Corp", 100.0, 5_000_000),
}
RAISE = {"BOOM", "BOOMCTOR"}

CALLS = []

class FakeTicker:
    def __init__(self, sym):
        CALLS.append(sym)
        if sym == "BOOMCTOR":
            raise ConnectionError("feed down")
        self._sym = sym

    @property
    def info(self):
        if self._sym in RAISE:
            raise TimeoutError("yahoo timed out")
        if self._sym in INFO:
            return INFO[self._sym]
        return INFO["GENERIC"]


TMP = Path(tempfile.mkdtemp(prefix="screen-test-"))
REAL_CACHE = instruments.CACHE
REAL_TICKER = instruments.yf.Ticker

def fresh_cache(content=None, name="cache.json"):
    """Point instruments.CACHE at a new temp file (optionally pre-filled) and reset the call log."""
    p = TMP / name
    if p.exists():
        p.unlink()
    if content is not None:
        p.write_text(content if isinstance(content, str) else json.dumps(content))
    instruments.CACHE = p
    CALLS.clear()
    return p

def disk(p):
    return json.loads(p.read_text()) if p.exists() else None

def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def main():
    real_digest = digest(REAL_CACHE)
    instruments.yf.Ticker = FakeTicker
    try:
        run_checks()
    finally:
        instruments.yf.Ticker = REAL_TICKER
        instruments.CACHE = REAL_CACHE
    ok("repo instruments.json untouched by the test run", digest(REAL_CACHE) == real_digest)
    shutil.rmtree(TMP, ignore_errors=True)
    failed = RESULTS.count(False)
    print(f"\n{len(RESULTS) - failed}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


def run_checks():
    R = instruments.RULES
    ok("constants: MIN_DOLLAR_VOLUME 20M, MIN_PRICE 5, no share floor left",
       instruments.MIN_DOLLAR_VOLUME == 20_000_000 and instruments.MIN_PRICE == 5.0
       and not hasattr(instruments, "MIN_AVG_VOLUME"), f"RULES={R}")
    ok("RULES names both floors", "20" in R and "5" in R, R)

    # ------------------------------------------------ verdicts
    p = fresh_cache()
    v = instruments.check(["THIN"])["THIN"]
    ok("equity under $20M/day rejected", v["ok"] is False, v)
    ok("  ...with a clear dollar why", "too thinly traded" in v["why"] and "$10.0M" in v["why"], v["why"])

    v = instruments.check(["EDGE", "ABOVE"])
    ok("equity at exactly $20M/day passes", v["EDGE"]["ok"] is True, v["EDGE"])
    ok("equity above $20M/day passes", v["ABOVE"]["ok"] is True, v["ABOVE"])

    v = instruments.check(["PENNY"])["PENNY"]
    ok("price < $5 rejected even with $49.9M/day", v["ok"] is False and "below $5" in v["why"], v)

    v = instruments.check(["HLI", "TPL"])
    ok("HLI-like (876k shares x $137 = $120M) passes", v["HLI"]["ok"] is True, v["HLI"])
    ok("  ...and the old 1M-share floor would have rejected it", INFO["HLI"]["averageVolume"] < 1_000_000)
    ok("TPL-like (372k shares x $365) passes", v["TPL"]["ok"] is True, v["TPL"])

    v = instruments.check(["FLD", "ALP", "MAIA", "GRNT", "DGICA"])
    for t in ("FLD", "ALP", "MAIA", "GRNT", "DGICA"):
        ok(f"{t}-like rejected", v[t]["ok"] is False and not v[t].get("transient"), v[t])
    ok("GRNT (price $5.12 passes) rejected on dollar volume", "too thinly traded" in v["GRNT"]["why"], v["GRNT"]["why"])
    ok("DGICA ($15) rejected on dollar volume", "too thinly traded" in v["DGICA"]["why"], v["DGICA"]["why"])

    v = instruments.check(["ETFTINY", "FUNDNOVOL"])
    ok("ETF passes regardless of volume/price", v["ETFTINY"]["ok"] is True, v["ETFTINY"])
    ok("mutual fund with no volume passes", v["FUNDNOVOL"]["ok"] is True, v["FUNDNOVOL"])

    v = instruments.check(["GOOGN", "XYZW", "WTYPE"])
    ok("preferred depositary name rejected", v["GOOGN"]["ok"] is False and "not ordinary shares" in v["GOOGN"]["why"], v["GOOGN"])
    ok("warrant name rejected", v["XYZW"]["ok"] is False and "warrant" in v["XYZW"]["why"], v["XYZW"])
    ok("WARRANT quoteType rejected", v["WTYPE"]["ok"] is False and "warrant" in v["WTYPE"]["why"], v["WTYPE"])

    v = instruments.check(["NOPRICE", "NOVOL"])
    ok("missing price with volume present: not rejected on volume",
       "thinly" not in v["NOPRICE"]["why"] and v["NOPRICE"]["ok"] is True, v["NOPRICE"])
    ok("missing volume with price present: not rejected on volume",
       "thinly" not in v["NOVOL"]["why"] and v["NOVOL"]["ok"] is True, v["NOVOL"])

    CALLS.clear()
    instruments.check(["brk.b"])
    ok("dot share class looked up as Yahoo dash symbol", CALLS == ["BRK-B"], CALLS)

    # every settled verdict above is on disk and stamped
    d = disk(p) or {}
    settled = ["THIN", "EDGE", "ABOVE", "PENNY", "HLI", "TPL", "FLD", "ALP", "MAIA", "GRNT", "DGICA",
               "ETFTINY", "FUNDNOVOL", "GOOGN", "XYZW", "WTYPE", "NOPRICE", "NOVOL", "BRK.B"]
    ok("settled verdicts (ok and rejected) all written to cache", all(t in d for t in settled),
       sorted(set(settled) - set(d)))
    ok("settled verdicts stamped rules == RULES", all(d.get(t, {}).get("rules") == R for t in settled),
       {t: d.get(t, {}).get("rules") for t in settled if d.get(t, {}).get("rules") != R})
    ok("returned verdict also carries rules", instruments.check(["HLI"])["HLI"].get("rules") == R)

    # ------------------------------------------------ transient lookups
    p = fresh_cache()
    v = instruments.check(["BOOM", "BOOMCTOR", "EMPTY", "NONEINFO"])
    ok(".info raising -> transient, not ok", v["BOOM"]["ok"] is False and v["BOOM"].get("transient") is True, v["BOOM"])
    ok("  ...why names the error", "TimeoutError" in v["BOOM"]["why"], v["BOOM"]["why"])
    ok("Ticker() raising -> transient", v["BOOMCTOR"].get("transient") is True, v["BOOMCTOR"])
    ok("empty info -> transient", v["EMPTY"]["ok"] is False and v["EMPTY"].get("transient") is True, v["EMPTY"])
    ok("None info -> transient", v["NONEINFO"].get("transient") is True, v["NONEINFO"])
    ok("transient-only batch writes no cache file", not p.exists(), disk(p))
    ok("transient verdicts not stamped with rules", all("rules" not in x for x in v.values()), v)

    p = fresh_cache()
    instruments.check(["BOOM", "HLI"])
    d = disk(p) or {}
    ok("mixed batch: settled written, transient not", "HLI" in d and "BOOM" not in d, d)
    CALLS.clear()
    v = instruments.check(["BOOM"])["BOOM"]
    ok("transient retried on the next call", CALLS == ["BOOM"] and v.get("transient") is True, CALLS)

    legacy = {"BOOM": {"ok": True, "why": "", "name": "Boom Inc"}}
    p = fresh_cache(legacy)
    before = p.read_text()
    v = instruments.check(["BOOM"])["BOOM"]
    ok("legacy entry + failed lookup: transient returned, legacy entry left as is",
       v.get("transient") is True and p.read_text() == before, (v, p.read_text()))

    # ------------------------------------------------ cache reuse and invalidation
    p = fresh_cache({"THIN": {"ok": True, "why": "", "name": "Cached Thin", "rules": R}})
    v = instruments.check(["THIN"])["THIN"]
    ok("cached verdict with current RULES reused, yfinance not called",
       CALLS == [] and v["ok"] is True and v["name"] == "Cached Thin", (CALLS, v))

    p = fresh_cache({"FLD": {"ok": True, "why": "", "name": "Fold Holdings, Inc."},
                     "OTHER": {"ok": True, "why": "", "name": "Untouched"}})
    v = instruments.check(["FLD"])["FLD"]
    d = disk(p)
    ok("legacy ok verdict without rules is re-judged (FLD now rejected)",
       CALLS == ["FLD"] and v["ok"] is False and "thinly" in v["why"], (CALLS, v))
    ok("  ...and the new verdict replaces it on disk with rules", d["FLD"]["ok"] is False and d["FLD"]["rules"] == R, d["FLD"])
    ok("  ...other cache entries preserved", d.get("OTHER") == {"ok": True, "why": "", "name": "Untouched"}, d.get("OTHER"))
    CALLS.clear()
    instruments.check(["FLD"])
    ok("  ...re-judged verdict then reused without a lookup", CALLS == [], CALLS)

    p = fresh_cache({"HLI": {"ok": False, "why": "too thinly traded (876,000/day)", "name": "Houlihan Lokey, Inc."}})
    v = instruments.check(["HLI"])["HLI"]
    ok("legacy REJECTED verdict (HLI on share floor) is re-judged and now passes", CALLS == ["HLI"] and v["ok"] is True, (CALLS, v))

    p = fresh_cache({"MAIA": {"ok": True, "why": "", "name": "MAIA", "rules": "usd10m-px5"},
                     "HLI": {"ok": True, "why": "", "name": "HLI", "rules": R + "-old"}})
    v = instruments.check(["MAIA", "HLI"])
    ok("cached verdict with a different rules string is re-judged",
       sorted(CALLS) == ["HLI", "MAIA"] and v["MAIA"]["ok"] is False, (CALLS, v["MAIA"]))
    ok("  ...rewritten with current RULES", all(disk(p)[t]["rules"] == R for t in ("MAIA", "HLI")), disk(p))

    p = fresh_cache({"J1": "yes", "J2": 5, "J3": None, "J4": [1, 2], "J5": {"rules": R}})
    try:
        v = instruments.check(["J1", "J2", "J3", "J4"])
        crashed = None
    except Exception as e:  # noqa: BLE001
        v, crashed = {}, e
    ok("non-dict junk cache entries do not crash", crashed is None, repr(crashed))
    ok("  ...junk entries are re-judged and replaced", sorted(CALLS) == ["J1", "J2", "J3", "J4"]
       and all(isinstance(disk(p)[t], dict) and disk(p)[t]["rules"] == R for t in ("J1", "J2", "J3", "J4")), (CALLS, disk(p)))

    p = fresh_cache("{ this is not json")
    try:
        v = instruments.check(["HLI"])["HLI"]
        crashed = None
    except Exception as e:  # noqa: BLE001
        v, crashed = {}, e
    ok("corrupt cache file does not crash and is re-judged", crashed is None and CALLS == ["HLI"] and v.get("ok") is True,
       (crashed, CALLS))

    # ------------------------------------------------ use_cache=False
    stored = {"THIN": {"ok": True, "why": "", "name": "Cached Thin", "rules": R}}
    p = fresh_cache(stored)
    before = digest(p)
    v = instruments.check(["THIN", "HLI"], use_cache=False)
    ok("use_cache=False does not read the cache (THIN looked up and rejected)",
       sorted(CALLS) == ["HLI", "THIN"] and v["THIN"]["ok"] is False, (CALLS, v["THIN"]))
    ok("use_cache=False does not write the cache", digest(p) == before, disk(p))
    p = fresh_cache()
    instruments.check(["HLI", "FLD"], use_cache=False)
    ok("use_cache=False does not create a cache file", not p.exists())

    # ------------------------------------------------ filter_allowed
    p = fresh_cache()
    allowed, notes = instruments.filter_allowed({"AAPL", "hli", "FLD", "PENNY", "GOOGN", "BOOM"}, ["aapl", "msft"])
    ok("filter_allowed returns only allowed names", allowed == {"AAPL", "HLI"}, allowed)
    ok("watchlist ticker not screened (no yfinance call for AAPL)", "AAPL" not in CALLS, CALLS)
    ok("watchlist names not in candidates are not added", "MSFT" not in allowed, allowed)
    ok("failing extras produce notes", len(notes) == 4 and all(" excluded: " in n for n in notes), notes)
    note = {n.split(" ")[0]: n for n in notes}
    ok("  ...FLD note carries why and name", "too thinly traded" in note.get("FLD", "") and "Fold Holdings" in note.get("FLD", ""), note.get("FLD"))
    ok("  ...PENNY note carries price why", "below $5" in note.get("PENNY", ""), note.get("PENNY"))
    ok("  ...GOOGN note says not ordinary shares", "not ordinary shares" in note.get("GOOGN", ""), note.get("GOOGN"))
    ok("  ...transient lookup is excluded with a note", "could not identify" in note.get("BOOM", ""), note.get("BOOM"))

    CALLS.clear()
    allowed, notes = instruments.filter_allowed({"AAPL", "MSFT"}, ["AAPL", "MSFT", "NVDA"])
    ok("all-watchlist candidates: returned unscreened with no notes",
       allowed == {"AAPL", "MSFT"} and notes == [] and CALLS == [], (allowed, notes, CALLS))

    p = fresh_cache({"FLD": {"ok": True, "why": "", "name": "Fold Holdings, Inc."}})
    allowed, notes = instruments.filter_allowed({"FLD", "SPY"}, ["SPY"])
    ok("legacy-approved FLD no longer passes filter_allowed", allowed == {"SPY"} and any(n.startswith("FLD") for n in notes),
       (allowed, notes))

    # ------------------------------------------------ the committed cache
    if REAL_CACHE.exists():
        committed = json.loads(REAL_CACHE.read_text())
        stale = {t for t, c in committed.items() if not (isinstance(c, dict) and c.get("rules") == R)}
        p = fresh_cache(REAL_CACHE.read_text(), name="committed-copy.json")
        instruments.check(list(committed))
        ok(f"committed instruments.json: all {len(stale)} of {len(committed)} entries without current RULES are re-judged",
           sorted(CALLS) == sorted(instruments.yahoo_symbol(t) for t in stale), (len(CALLS), len(stale)))
        stamped = disk(p)
        ok("  ...and the copy is fully re-stamped afterwards",
           all(isinstance(c, dict) and c.get("rules") == R for c in stamped.values()), len(stamped))
        CALLS.clear()
        instruments.check(list(committed))
        ok("  ...second pass makes no lookups", CALLS == [], len(CALLS))


if __name__ == "__main__":
    sys.exit(main())
