"""Find what to trade by reading other people's portfolios, instead of guessing.

The original watchlist was hand-written - five sectors somebody thought sounded good. That is
the one input to this whole system with no evidence behind it at all. Congress members have to
disclose what they hold, so the names held most widely across those portfolios are a far better
starting universe than anyone's intuition, and they are free to read.

A name has to be bought by several DIFFERENT members to qualify. One member buying a stock ten
times is one opinion repeated; three members buying it independently is three opinions. It then
has to clear the same instrument and liquidity screen as anything else.

    python -m agent.discover              # show what the portfolios hold that we do not
    python -m agent.discover --min 3      # how many distinct members must hold it
"""
import sys
from collections import Counter
from datetime import date, timedelta

from . import config, instruments, politicians, prices

def candidates(min_members: int = 3, days: int = 365, limit: int = 40) -> list[dict]:
    cfg = config.load_config()
    mine = {t for v in cfg["watchlist"].values() for t in v}
    rows = politicians._congresswatch()
    cut = (date.today() - timedelta(days=days)).isoformat()
    buys = [r for r in rows
            if r["type"] == "buy" and (r.get("transaction_date") or "") >= cut and r["ticker"] not in mine]
    n_buys = Counter(r["ticker"] for r in buys)
    members = {t: len({r["who"] for r in buys if r["ticker"] == t}) for t in n_buys}
    shortlist = [t for t, _ in n_buys.most_common(limit * 2) if members.get(t, 0) >= min_members][:limit]
    if not shortlist:
        return []
    ok, _ = instruments.filter_allowed(set(shortlist), set())
    px = prices.snapshot(sorted(ok))
    out = []
    for t in ok:
        q = px.get(t) or {}
        if q.get("price"):
            out.append({"ticker": t, "disclosed_buys": n_buys[t], "distinct_members": members[t],
                        "change_1m_pct": q.get("change_1m_pct"), "atr_pct": q.get("atr_pct")})
    return sorted(out, key=lambda r: -r["disclosed_buys"])

if __name__ == "__main__":
    m = int(sys.argv[sys.argv.index("--min") + 1]) if "--min" in sys.argv else 3
    rows = candidates(m)
    if not rows:
        raise SystemExit("nothing qualified")
    print(f"{'ticker':8}{'buys':>6}{'members':>9}{'1m':>9}{'ATR%':>8}")
    for r in rows[:20]:
        print(f"{r['ticker']:8}{r['disclosed_buys']:6}{r['distinct_members']:9}"
              f"{(r['change_1m_pct'] or 0):+8.1f}%{(r['atr_pct'] or 0):7.2f}%")
    print(f"\n{len(rows)} names held by {m}+ different members that are not on the watchlist.")
