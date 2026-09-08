"""Memecoin market data and safety screening. Free, keyless, and deliberately paranoid.

Three public APIs, none of which need a key:

  DexScreener      price, liquidity, 24h volume, buy/sell counts, pool age    (by MINT ADDRESS)
  GeckoTerminal    5-minute candles, so standing orders can fill at their level between checks
  GoPlus + RugCheck  can it be minted, frozen, taxed; who holds it; is the LP locked

Two things make this different from stocks and both are handled here.

**A symbol is not an identity.** Searching "BONK" returns thirty pairs across several chains whose
prices differ by more than 20%. Anyone trading on a symbol is trading a coin flip about which token
they meant. Everything here is keyed on the mint address, and resolution from a name follows real
trading activity rather than parked liquidity, because faking depth is cheap and faking sustained
two-sided volume is not.

**Most of these tokens are designed to take your money.** A stock that clears the exchange listing
process cannot usually be minted at will, frozen in your wallet, or taxed on exit. A memecoin can be
all three. `screen()` refuses anything it cannot positively verify, and "no data" is a rejection, not
a pass.
"""
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache" / "memecoin_screen.json"
SCREEN_TTL_S = 6 * 3600            # authorities can be revoked; re-verify a pass a few times a day
UA = {"User-Agent": "stock-agent/1.0 (paper trading; contact via github)"}
TIMEOUT = 20

DEXSCREENER = "https://api.dexscreener.com/latest/dex"
GECKOTERMINAL = "https://api.geckoterminal.com/api/v2"
GOPLUS = "https://api.gopluslabs.io/api/v1"
RUGCHECK = "https://api.rugcheck.xyz/v1"

# GoPlus uses a different path per chain; these are the ones we support.
CHAIN_IDS = {"solana": "solana", "ethereum": "1", "base": "8453", "bsc": "56"}

def _get(url: str, timeout: int = TIMEOUT):
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return None

# ---------------------------------------------------------------- market data

def _best_pair(pairs: list) -> dict | None:
    """The pool people are actually trading in.

    Ranking by liquidity alone is a trap: searching "BONK" surfaces an impostor with $50M of
    liquidity and zero trades in 24 hours, which outranks the real token's $300k pool. Parked
    liquidity is cheap to fake; sustained two-sided volume is not. So volume leads and depth
    only breaks ties.
    """
    usable = [p for p in (pairs or []) if (p.get("liquidity") or {}).get("usd") and p.get("priceUsd")]
    if not usable:
        return None
    def score(p):
        vol = float((p.get("volume") or {}).get("h24") or 0)
        liq = float((p.get("liquidity") or {}).get("usd") or 0)
        tx = (p.get("txns") or {}).get("h24") or {}
        trades = int(tx.get("buys") or 0) + int(tx.get("sells") or 0)
        return (vol, trades, liq)
    return max(usable, key=score)

def _shape(p: dict) -> dict:
    liq = (p.get("liquidity") or {}).get("usd") or 0
    vol = (p.get("volume") or {}).get("h24") or 0
    tx = (p.get("txns") or {}).get("h24") or {}
    created = p.get("pairCreatedAt")
    age_h = round((time.time() * 1000 - created) / 3600000, 1) if created else None
    ch = p.get("priceChange") or {}
    return {
        "mint": p["baseToken"]["address"], "symbol": p["baseToken"].get("symbol") or "?",
        "name": p["baseToken"].get("name") or "", "chain": p.get("chainId"), "dex": p.get("dexId"),
        "pool": p.get("pairAddress"), "price": float(p["priceUsd"]),
        "liquidity_usd": round(float(liq)), "volume24_usd": round(float(vol)),
        "fdv": p.get("fdv"), "market_cap": p.get("marketCap"),
        "buys24": tx.get("buys"), "sells24": tx.get("sells"),
        "change_5m_pct": ch.get("m5"), "change_1h_pct": ch.get("h1"),
        "change_6h_pct": ch.get("h6"), "change_24h_pct": ch.get("h24"),
        "pair_age_hours": age_h, "url": p.get("url"),
    }

def by_mint(mints: list[str]) -> dict:
    """{mint: quote} for exact mint addresses. The only trustworthy way to ask."""
    out = {}
    mints = [m for m in dict.fromkeys(mints) if m]
    for i in range(0, len(mints), 30):                     # the endpoint accepts a comma list
        chunk = mints[i:i + 30]
        d = _get(f"{DEXSCREENER}/tokens/{','.join(chunk)}")
        pairs = (d or {}).get("pairs") or []
        for m in chunk:
            mine = [p for p in pairs if (p.get("baseToken") or {}).get("address", "").lower() == m.lower()]
            best = _best_pair(mine)
            if best:
                out[m] = _shape(best)
    return out

def resolve(query: str, chains=("solana", "base", "ethereum")) -> dict | None:
    """Turn a name or symbol into ONE canonical token, or nothing.

    Ambiguity here is how people buy the wrong coin, so this is deliberately strict: it takes the
    deepest pool on a supported chain and records how many other candidates shared the symbol.
    """
    q = (query or "").strip()
    if not q:
        return None
    if len(q) >= 32 and " " not in q:                       # already an address
        got = by_mint([q])
        return got.get(q)
    d = _get(f"{DEXSCREENER}/search?q={urllib.parse.quote(q)}")
    pairs = [p for p in ((d or {}).get("pairs") or []) if p.get("chainId") in chains]
    exact = [p for p in pairs if (p.get("baseToken") or {}).get("symbol", "").lower() == q.lower()]
    best = _best_pair(exact or pairs)
    if not best:
        return None
    shaped = _shape(best)
    others = {(p.get("baseToken") or {}).get("address") for p in (exact or pairs)}
    shaped["symbol_collisions"] = max(0, len(others) - 1)
    return shaped

def trending(chain: str = "solana", limit: int = 40) -> list[dict]:
    """Candidate discovery: tokens the boosted/profile feeds are surfacing right now.

    This is an attention feed, not a recommendation feed - it is where the noise is loudest. Every
    name it returns still has to survive screen() before the agent may even consider it.
    """
    out, seen = [], set()
    for path in ("/token-boosts/top/v1", "/token-boosts/latest/v1", "/token-profiles/latest/v1"):
        d = _get(f"https://api.dexscreener.com{path}")
        for row in (d or [])[:120]:
            if row.get("chainId") != chain:
                continue
            a = row.get("tokenAddress")
            if a and a not in seen:
                seen.add(a); out.append(a)
    quotes = by_mint(out[:limit])
    return sorted(quotes.values(), key=lambda q: -q["liquidity_usd"])

def candles(chain: str, pool: str, since_ts: int = 0, aggregate: int = 5, limit: int = 60) -> list[dict]:
    """5-minute OHLC for one pool, oldest first, in the shape prices.intraday returns."""
    d = _get(f"{GECKOTERMINAL}/networks/{chain}/pools/{pool}/ohlcv/minute?aggregate={aggregate}&limit={limit}")
    rows = ((d or {}).get("data") or {}).get("attributes", {}).get("ohlcv_list") or []
    out = []
    for c in rows:
        try:
            t, o, h, l, cl, v = c
            if int(t) >= since_ts:
                out.append({"t": int(t), "h": float(h), "l": float(l), "c": float(cl), "v": float(v)})
        except Exception:
            continue
    return sorted(out, key=lambda b: b["t"])

def intraday(tokens: dict, since_ts: int = 0) -> dict:
    """{mint: bars} for the tokens given as {mint: quote}, so standing orders can fill on a level."""
    out = {}
    for mint, q in (tokens or {}).items():
        if not q.get("pool") or not q.get("chain"):
            continue
        bars = candles(q["chain"], q["pool"], since_ts)
        if bars:
            out[mint] = bars
    return out

# ---------------------------------------------------------------- safety screen

def _cache() -> dict:
    try:
        return json.loads(CACHE.read_text())
    except Exception:
        return {}

def _cache_save(d: dict) -> None:
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(d, indent=0, sort_keys=True))
    except Exception:
        pass

def _goplus(chain: str, mint: str) -> dict | None:
    cid = CHAIN_IDS.get(chain)
    if not cid:
        return None
    path = "solana/token_security" if chain == "solana" else f"token_security/{cid}"
    d = _get(f"{GOPLUS}/{path}?contract_addresses={mint}")
    if not d or str(d.get("code")) != "1":
        return None
    res = d.get("result") or {}
    for k, v in res.items():
        if k.lower() == mint.lower() or len(res) == 1:
            return v
    return None

def _rugcheck(mint: str) -> dict | None:
    return _get(f"{RUGCHECK}/tokens/{mint}/report/summary")

def _flag(v) -> bool:
    """GoPlus reports authorities as {'status': '1'} or plain '1'."""
    if isinstance(v, dict):
        return str(v.get("status", "0")) == "1"
    return str(v) == "1"

def screen(quote: dict, rules: dict) -> tuple[bool, list[str], dict]:
    """Would a careful person be willing to hold this at all? Returns (ok, reasons_to_refuse, facts).

    Anything unverifiable is refused. On these chains the absence of evidence really is evidence of
    absence: a token whose security data cannot be read is one whose rules cannot be checked.
    """
    mint, chain = quote.get("mint"), quote.get("chain")
    bad, facts = [], {}

    liq = quote.get("liquidity_usd") or 0
    vol = quote.get("volume24_usd") or 0
    age = quote.get("pair_age_hours")
    if liq < float(rules.get("min_liquidity_usd", 50000)):
        bad.append(f"liquidity ${liq:,.0f} below ${float(rules.get('min_liquidity_usd', 50000)):,.0f}")
    if vol < float(rules.get("min_volume24_usd", 25000)):
        bad.append(f"24h volume ${vol:,.0f} below ${float(rules.get('min_volume24_usd', 25000)):,.0f}")
    if age is None:
        bad.append("pool age unknown")
    elif age < float(rules.get("min_pair_age_hours", 24)):
        bad.append(f"pool only {age:.0f}h old, minimum {rules.get('min_pair_age_hours', 24)}h")
    if liq and vol / max(liq, 1) > float(rules.get("max_volume_to_liquidity", 30)):
        bad.append(f"volume is {vol / liq:.0f}x liquidity, which is what wash trading looks like")
    buys, sells = quote.get("buys24") or 0, quote.get("sells24") or 0
    if buys + sells < int(rules.get("min_txns24", 300)):
        bad.append(f"only {buys + sells} trades in 24h")
    if sells == 0 and buys > 20:
        bad.append("nobody has sold it: possible honeypot")

    sec = _goplus(chain, mint) if mint and chain else None
    facts["goplus"] = bool(sec)
    if not sec:
        bad.append("no security data available, so its rules cannot be verified")
    else:
        if _flag(sec.get("mintable")):
            bad.append("supply can still be minted")
        if _flag(sec.get("freezable")):
            bad.append("your balance can be frozen")
        if _flag(sec.get("closable")):
            bad.append("your account can be closed by the authority")
        if str(sec.get("non_transferable", "0")) == "1":
            bad.append("token is non-transferable")
        if sec.get("transfer_hook") or _flag(sec.get("transfer_hook_upgradable")):
            bad.append("has a transfer hook (arbitrary code on every transfer)")
        fee = sec.get("transfer_fee")
        if isinstance(fee, dict) and fee:
            bad.append("charges a transfer fee")
        holders = sec.get("holders") or []
        top = max((float(h.get("percent") or 0) for h in holders), default=0) * 100
        facts["top_holder_pct"] = round(top, 2)
        if top > float(rules.get("max_top_holder_pct", 25)):
            bad.append(f"one wallet holds {top:.1f}%")
        hc = sec.get("holder_count")
        facts["holder_count"] = hc
        if hc is not None and int(hc) < int(rules.get("min_holder_count", 500)):
            bad.append(f"only {hc} holders")

    rc = _rugcheck(mint) if mint else None
    facts["rugcheck"] = bool(rc)
    if rc:
        lp = rc.get("lpLockedPct")
        facts["lp_locked_pct"] = lp
        if lp is not None and float(lp) < float(rules.get("min_lp_locked_pct", 0)):
            bad.append(f"only {float(lp):.0f}% of the LP is locked")
        danger = [r.get("name") for r in (rc.get("risks") or []) if str(r.get("level", "")).lower() == "danger"]
        facts["rugcheck_risks"] = [r.get("name") for r in (rc.get("risks") or [])]
        if danger:
            bad.append("RugCheck flags: " + ", ".join(danger[:3]))
    return (not bad), bad, facts

def screen_cached(quote: dict, rules: dict) -> tuple[bool, list[str], dict]:
    mint = quote.get("mint") or ""
    c = _cache()
    row = c.get(mint)
    now = int(time.time())
    if row and now - int(row.get("ts", 0)) < SCREEN_TTL_S:
        return bool(row["ok"]), list(row["why"]), dict(row.get("facts") or {})
    ok, why, facts = screen(quote, rules)
    c[mint] = {"ok": ok, "why": why, "facts": facts, "ts": now,
               "symbol": quote.get("symbol"), "checked": datetime.now(timezone.utc).isoformat(timespec="minutes")}
    _cache_save(c)
    return ok, why, facts

def allowed_universe(rules: dict, extra_mints=(), chain: str = "solana", limit: int = 25) -> tuple[dict, list[str]]:
    """Candidates that survived every check, plus a note for each one that did not."""
    cands = {q["mint"]: q for q in trending(chain, limit)}
    for m in extra_mints or ():
        if m not in cands:
            got = by_mint([m])
            if m in got:
                cands[m] = got[m]
    ok, notes = {}, []
    for mint, q in cands.items():
        passed, why, facts = screen_cached(q, rules)
        if passed:
            q["screen"] = facts
            ok[mint] = q
        else:
            notes.append(f"{q.get('symbol', mint[:6])}: " + "; ".join(why[:2]))
    return ok, notes
