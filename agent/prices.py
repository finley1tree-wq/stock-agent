"""Price snapshot for the watchlist. Uses yfinance (free, no key)."""
import yfinance as yf


# How much the spread actually costs, per name.
#
# A flat charge is wrong by more than an order of magnitude across a watchlist. Measured on real
# 2026-09-14 trades: AAPL at 54M shares/day costs ~4bp a round trip, while FLD at $0.53 and 446k
# shares/day costs ~80bp - twenty times what a flat 0.02%/side charges. The agent found that out
# before we did: on 2026-09-14 thin names were 34% of turnover and 86% of the "profit", and the
# best-looking signal in the whole record (t = 2.87) was manufactured entirely by the undercharge.
#
# Cost is driven by liquidity and by price level - a one-cent spread is 0.2bp on a $500 stock and
# 189bp on a $0.53 one - so both go into the estimate.
SPREAD_TIERS = ((20_000_000, 0.02), (5_000_000, 0.04), (1_000_000, 0.10), (0, 0.40))

def spread_pct(ticker: str, px: dict | None, default: float = 0.02) -> float:
    """One-way spread cost in percent for this name. Falls back to `default` when unknown."""
    q = (px or {}).get(ticker) or {}
    vol = q.get("avg_volume") or q.get("volume") or 0
    price = q.get("price") or 0
    if not vol:
        return default
    est = next(c for floor, c in SPREAD_TIERS if vol >= floor)
    if price and price < 5:
        # a penny of spread is a large fraction of a cheap share, whatever the volume
        est = max(est, min(2.0, 0.5 / price))
    return round(max(est, default), 4)

def yahoo_symbol(t: str) -> str:
    """Yahoo writes share classes with a dash: BRK.B -> BRK-B. Filings use the dot form."""
    return t.replace(".", "-") if "." in t and not t.endswith(".TO") else t

def _atr_pct(f, n: int = 14):
    """14-day ATR as a percent of price - how far this stock moves on an ordinary day.

    A flat 2% stop means completely different things on DIA (1.9x its daily range, basically
    unreachable) and OKLO (0.3x, hit by noise before lunch). Measured across the watchlist that
    is an 8x inconsistency, which is why every level is sized in these units instead.
    """
    try:
        hi, lo, cl = f["High"].dropna(), f["Low"].dropna(), f["Close"].dropna()
        prev = cl.shift(1)
        tr = (hi - lo).combine((hi - prev).abs(), max).combine((lo - prev).abs(), max).dropna()
        if len(tr) < n:
            return None
        atr = tr.tail(n).mean()
        last = float(cl.iloc[-1])
        return round(float(atr) / last * 100, 3) if last else None
    except Exception:
        return None

def _frame_for(data, t: str):
    cols = data.columns
    if getattr(cols, "nlevels", 1) > 1:
        if t in cols.get_level_values(0):
            return data[t]
        if "Close" in cols.get_level_values(0):
            return data.xs(t, axis=1, level=1)
        return None
    return data

def _hl(data, t: str):
    """Today's high and low, so the agent can tell where in the day's range it is buying."""
    cols = data.columns
    if getattr(cols, "nlevels", 1) > 1:
        if t in cols.get_level_values(0):
            f = data[t]
        elif "Close" in cols.get_level_values(0):
            f = data.xs(t, axis=1, level=1)
        else:
            return None, None
    else:
        f = data
    try:
        hi = f["High"].dropna(); lo = f["Low"].dropna()
        return float(hi.iloc[-1]), float(lo.iloc[-1])
    except Exception:
        return None, None

def _closes(data, t: str, n: int):
    """Handle every column shape yfinance/pandas produce: MultiIndex (ticker, field) or flat."""
    cols = data.columns
    if getattr(cols, "nlevels", 1) > 1:
        if t in cols.get_level_values(0):
            return data[t]["Close"].dropna()
        if "Close" in cols.get_level_values(0):       # (field, ticker) ordering
            return data["Close"][t].dropna()
        raise KeyError(t)
    return data["Close"].dropna()                      # flat single-ticker frame

def _frame(data, y: str):
    """One ticker's OHLC frame out of whatever shape yfinance returned."""
    cols = data.columns
    if getattr(cols, "nlevels", 1) > 1:
        if y in cols.get_level_values(0):
            return data[y]
        if "Close" in cols.get_level_values(0):        # (field, ticker) ordering
            return data.xs(y, axis=1, level=1)
        raise KeyError(y)
    return data

def intraday(tickers: list[str], since_ts: int = 0, interval: str = "5m") -> dict:
    """Bars for today so a standing order can be filled at the moment its level was reached.

    Returns {ticker: [{"t": epoch_seconds, "h": high, "l": low, "c": close}, ...]} oldest first,
    keeping only bars at or after since_ts. Empty dict on any failure — callers fall back to the
    current quote, which simply means a level is only seen at check time.
    """
    out = {}
    tickers = sorted({t for t in tickers if t})
    if not tickers:
        return out
    ymap = {yahoo_symbol(t): t for t in tickers}
    ysyms = sorted(ymap)
    try:
        data = yf.download(ysyms, period="2d", interval=interval, progress=False,
                           auto_adjust=False, group_by="ticker", threads=True)
    except Exception:
        return out
    if data is None or len(data) == 0:
        return out
    for y in ysyms:
        try:
            f = _frame(data, y)[["High", "Low", "Close"]].dropna()
            rows = []
            for idx, r in f.iterrows():
                ts = int(idx.timestamp())
                if ts < since_ts:
                    continue
                rows.append({"t": ts, "h": round(float(r["High"]), 4),
                             "l": round(float(r["Low"]), 4), "c": round(float(r["Close"]), 4)})
            if rows:
                out[ymap[y]] = rows
        except Exception:
            continue
    return out

def snapshot(tickers: list[str]) -> dict:
    """Return {ticker: {price, change_1d_pct, change_5d_pct, change_1m_pct}}."""
    out = {}
    tickers = sorted({t for t in tickers if t})
    if not tickers:
        return out
    ymap = {yahoo_symbol(t): t for t in tickers}          # yahoo symbol -> our symbol
    ysyms = sorted(ymap)
    try:
        data = yf.download(ysyms, period="2mo", interval="1d", progress=False, auto_adjust=False, group_by="ticker", threads=True)
    except Exception:
        return out
    for y in ysyms:
        t = ymap[y]
        try:
            closes = _closes(data, y, len(ysyms))
            if len(closes) < 2:
                continue
            last = float(closes.iloc[-1])
            def pct(n):
                return round((last / float(closes.iloc[-1 - n]) - 1) * 100, 2) if len(closes) > n else None
            row = {"price": round(last, 2), "change_1d_pct": pct(1), "change_5d_pct": pct(5), "change_1m_pct": pct(21)}
            f = _frame_for(data, y)
            if f is not None:
                a = _atr_pct(f)
                if a:
                    row["atr_pct"] = a
                # Average daily volume, so the spread can be charged per name instead of flat.
                # Without this every stock was billed as if it were AAPL, and the agent learned to
                # farm the undercharge: on 2026-09-14 thin names were 34% of turnover and 86% of
                # the reported profit.
                try:
                    v = f["Volume"].dropna()
                    if len(v):
                        row["avg_volume"] = int(v.tail(20).mean())
                except Exception:
                    pass
            hi, lo = _hl(data, y)
            if hi and lo and hi > lo:
                # Where in today's range this price sits. 0 = at the low, 100 = at the high.
                # Buying near 100 is buying after the move, which is what the agent did all of
                # its first day: an average entry at the 76th percentile, six of seven closing red.
                row.update(day_high=round(hi, 4), day_low=round(lo, 4),
                           pct_of_day_range=round((last - lo) / (hi - lo) * 100, 1))
            out[t] = row
        except Exception:
            continue
    return out
