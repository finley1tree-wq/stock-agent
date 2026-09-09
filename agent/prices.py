"""Price snapshot for the watchlist. Uses yfinance (free, no key)."""
import yfinance as yf

def yahoo_symbol(t: str) -> str:
    """Yahoo writes share classes with a dash: BRK.B -> BRK-B. Filings use the dot form."""
    return t.replace(".", "-") if "." in t and not t.endswith(".TO") else t

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
