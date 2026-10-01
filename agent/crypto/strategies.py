"""Per-coin strategies on DAILY bars. Each is a step function f(bars, i, state) -> (position, state):
looking only at bars[0..i] (closed days), should the book be long (1) or flat (0) from bar i+1?
Long only; flat is cash. The same functions drive the backtest and the live book, so what was
measured is what trades. Rules match the pre-registered research set (S0-S4):
    hold       buy and hold (the control every other strategy must beat)
    trend_ma   long while close > SMA50 and SMA20 > SMA50
    donchian   enter on a close above the prior 20-day high, exit on a close below the prior 10-day low
    tsm        weekly (Mondays): long if the 30-day return is positive, else flat
    rsi_rev    enter when RSI14 < 30, exit when RSI14 > 55 or after 10 days
"""
from datetime import datetime, timezone


def _sma(bars, i, n):
    return sum(b["c"] for b in bars[i - n + 1: i + 1]) / n if i + 1 >= n else None


def _rsi(bars, i, n=14):
    if i < n:
        return None
    gains = losses = 0.0
    for k in range(i - n + 1, i + 1):
        d = bars[k]["c"] - bars[k - 1]["c"]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    if losses == 0:
        return 100.0
    return 100 - 100 / (1 + gains / losses)


def hold(bars, i, st):
    return 1, st


def trend_ma(bars, i, st):
    s20, s50 = _sma(bars, i, 20), _sma(bars, i, 50)
    if s50 is None:
        return 0, st
    return (1 if bars[i]["c"] > s50 and s20 > s50 else 0), st


def donchian(bars, i, st):
    if i < 20:
        return 0, st
    pos = st.get("pos", 0)
    hi20 = max(b["h"] for b in bars[i - 20: i])
    lo10 = min(b["l"] for b in bars[i - 10: i])
    c = bars[i]["c"]
    if not pos and c > hi20:
        pos = 1
    elif pos and c < lo10:
        pos = 0
    return pos, {**st, "pos": pos}


def tsm(bars, i, st):
    if i < 30:
        return 0, st
    pos = st.get("pos")
    if pos is None or datetime.fromtimestamp(bars[i]["t"], timezone.utc).weekday() == 0:
        pos = 1 if bars[i]["c"] > bars[i - 30]["c"] else 0       # re-evaluated on Mondays
    return pos, {**st, "pos": pos}


def rsi_rev(bars, i, st):
    r = _rsi(bars, i)
    if r is None:
        return 0, st
    pos, age = st.get("pos", 0), st.get("age", 0)
    if not pos and r < 30:
        pos, age = 1, 0
    elif pos:
        age += 1
        if r > 55 or age >= 10:
            pos, age = 0, 0
    return pos, {**st, "pos": pos, "age": age}


STRATEGIES = {"hold": hold, "trend_ma": trend_ma, "donchian": donchian, "tsm": tsm, "rsi_rev": rsi_rev}
WARMUP = 60     # bars before any strategy is judged
