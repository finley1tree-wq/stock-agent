"""Is this ticker actually ordinary stock, or something that merely looks like it?

Congress and insider filings name tickers the watchlist never vetted. Some of those are not the
company's ordinary shares at all: GOOGN is Alphabet *preferred depositary shares*, not Alphabet.
Warrants, rights, units and preferreds trade thinly, move on their own terms, and are not what a
headline about "Alphabet stock" is describing — buying one because of that headline is buying the
wrong instrument for the right reason.

So anything that is not on the hand-written watchlist has to prove it is common stock or a normal
fund before the brain is allowed to see it. Verdicts are cached on disk forever, because what kind
of security a ticker is does not change.
"""
import json
import re
from pathlib import Path

import yfinance as yf

from .prices import yahoo_symbol

ROOT = Path(__file__).resolve().parent.parent
# Committed on purpose: what kind of security a ticker is never changes, and a fresh cloud runner
# would otherwise re-look-up every off-watchlist name on every single check.
CACHE = ROOT / "instruments.json"

GOOD_TYPES = {"EQUITY", "ETF", "MUTUALFUND"}
# name patterns that mean "not the ordinary shares"
BAD_NAME = re.compile(
    r"\b(preferred|depositary|depository|warrant|warrants|right|rights|unit|units|"
    r"convertible|debenture|note|notes|trust preferred|when[- ]issued|"
    r"series [a-z] (preferred|pfd)|pfd)\b", re.I)
# Raised from 100,000. At that floor the screen passed FLD (a $0.53 share) and ALP ($4.16), and
# those two produced most of a day's "profit" purely because the flat spread charge undercharged
# them by twenty times. The cost model is now per-name, so the economics would eventually teach
# the agent to avoid them - but there is no reason to spend real trades learning what a screen
# can settle for free.
MIN_AVG_VOLUME = 1_000_000
# A penny of spread is 0.2bp on a $500 share and 189bp on a $0.53 one. Below this price the
# spread dominates any edge a 30-minute trade could have, whatever the volume.
MIN_PRICE = 5.0

def _load() -> dict:
    try:
        return json.loads(CACHE.read_text())
    except Exception:
        return {}

def _save(d: dict) -> None:
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(d, indent=0, sort_keys=True))
    except Exception:
        pass

def _judge(t: str) -> dict:
    """Ask Yahoo what this actually is. Unknown -> rejected, because guessing is the failure mode."""
    try:
        info = yf.Ticker(yahoo_symbol(t)).info or {}
    except Exception as e:
        # "the lookup did not answer" is not "this is not ordinary shares". Tagged transient so it is
        # never written to the forever-cache: a feed hiccup was permanently blacklisting good names.
        return {"ok": False, "why": f"could not identify ({type(e).__name__})", "name": "", "transient": True}
    name = str(info.get("longName") or info.get("shortName") or "")
    qtype = str(info.get("quoteType") or "").upper()
    vol = info.get("averageVolume") or info.get("averageDailyVolume10Day") or 0
    if not name and not qtype:
        return {"ok": False, "why": "no security information", "name": "", "transient": True}
    if qtype and qtype not in GOOD_TYPES:
        return {"ok": False, "why": f"not ordinary shares ({qtype.lower()})", "name": name}
    m = BAD_NAME.search(name)
    if m:
        return {"ok": False, "why": f"not ordinary shares ({m.group(0).lower()})", "name": name}
    if qtype == "EQUITY" and vol and int(vol) < MIN_AVG_VOLUME:
        return {"ok": False, "why": f"too thinly traded ({int(vol):,}/day)", "name": name}
    price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose") or 0
    if qtype == "EQUITY" and price and float(price) < MIN_PRICE:
        return {"ok": False, "why": f"share price ${float(price):.2f} is below ${MIN_PRICE:.0f}: the spread eats the trade",
                "name": name}
    return {"ok": True, "why": "", "name": name}

def check(tickers, use_cache: bool = True) -> dict:
    """{ticker: {ok, why, name[, transient]}} for each. Settled verdicts are cached on disk forever;
    a lookup that did not answer is returned with transient=True and NOT cached, so the caller can
    decide to wait rather than act on a non-answer."""
    cache = _load() if use_cache else {}
    out, fresh = {}, False
    for t in sorted({str(x).upper() for x in tickers if x}):
        if t in cache:
            out[t] = cache[t]; continue
        v = _judge(t); out[t] = v
        if not v.get("transient"):               # settled verdicts cache forever; a failed lookup retries next run
            cache[t] = v; fresh = True
    if fresh and use_cache:
        _save(cache)
    return out

def filter_allowed(candidates, watchlist) -> tuple[set, list[str]]:
    """Keep watchlist tickers as-is; make everything else prove it is ordinary stock or a fund.

    Returns (allowed, rejection notes).
    """
    watch = {str(t).upper() for t in watchlist}
    extra = {str(t).upper() for t in candidates} - watch
    if not extra:
        return set(candidates), []
    verdicts = check(extra)
    ok = {t for t in extra if verdicts.get(t, {}).get("ok")}
    notes = [f"{t} excluded: {verdicts[t]['why']}" + (f" — {verdicts[t]['name'][:60]}" if verdicts[t].get("name") else "")
             for t in sorted(extra - ok)]
    return (watch & {str(t).upper() for t in candidates}) | ok, notes
