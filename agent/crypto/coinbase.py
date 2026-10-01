"""Coinbase Exchange public market data: products, candles, tickers. No account, no key.

Rate limit on the public REST API is about 10 requests a second; everything here is sequential with
a small pause. Candle rows come back newest first as [time, low, high, open, close, volume].
"""
import json
import time
import urllib.request
from datetime import datetime, timedelta, timezone

API = "https://api.exchange.coinbase.com"
UA = {"User-Agent": "stock-agent-crypto/1.0", "Accept": "application/json"}
PAUSE = 0.15

# Not coins to trade: dollar stablecoins, wrapped or pegged copies of another asset.
EXCLUDE = {"USDT", "USDC", "DAI", "PYUSD", "EURC", "GUSD", "PAX", "PAXG", "USDS", "FDUSD", "TUSD", "WBTC",
           "CBETH", "WETH", "STETH", "RETH", "MSOL", "JITOSOL", "CBBTC", "LSETH", "XAUT", "EUROC", "USD1", "RLUSD"}


def _get(path: str, tries: int = 3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(API + path, headers=UA)
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode())
        except Exception as e:          # 429s and timeouts: back off and retry
            last = e
            time.sleep(1.0 + i)
    raise RuntimeError(f"coinbase {path}: {last}")


def usd_products() -> list[str]:
    """Base symbols with an online, tradeable -USD market, stablecoins and wrapped assets left out."""
    out = []
    for p in _get("/products"):
        if p.get("quote_currency") != "USD" or p.get("status") != "online" or p.get("trading_disabled"):
            continue
        base = str(p.get("base_currency", "")).upper()
        if base in EXCLUDE or base.startswith("USD") or base.endswith("USD"):
            continue
        out.append(base)
    return sorted(set(out))


def candles(coin: str, granularity: int = 86400, days: int = 1100) -> list[dict]:
    """Bars oldest first: {"t": unix, "o","h","l","c","v"}. Pages backwards 300 bars at a time."""
    end = datetime.now(timezone.utc)
    start_all = end - timedelta(seconds=granularity * int(days * 86400 / granularity))
    bars: dict[int, dict] = {}
    cur_end = end
    while cur_end > start_all:
        cur_start = max(start_all, cur_end - timedelta(seconds=granularity * 300))
        rows = _get(f"/products/{coin}-USD/candles?granularity={granularity}"
                    f"&start={cur_start.isoformat()}&end={cur_end.isoformat()}")
        time.sleep(PAUSE)
        if not isinstance(rows, list) or not rows:
            break
        for t, lo, hi, op, cl, vol in rows:
            bars[int(t)] = {"t": int(t), "o": float(op), "h": float(hi), "l": float(lo), "c": float(cl), "v": float(vol)}
        cur_end = cur_start
    return [bars[k] for k in sorted(bars)]


def tickers(coins: list[str]) -> dict[str, float]:
    """Last trade price per coin."""
    out = {}
    for c in coins:
        try:
            out[c] = float(_get(f"/products/{c}-USD/ticker")["price"])
        except Exception:
            pass
        time.sleep(PAUSE)
    return out
