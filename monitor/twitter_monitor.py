"""Social-post signal monitor - WATCH ONLY. It never trades and is not imported by the agent.

Polls posts from market-moving accounts, matches a fixed set of signal patterns, and for each match
logs a line, appends it to monitor/signals.jsonl and POSTs it to a webhook. Nothing listens on the
webhook by default, so today this is a logger: it answers "what would these rules have fired on".

Sources, verified 2026-09-16:
  * Nitter (nitter.net, nitter.it, nitter.poast.org, nitter.privacydev.net) - all dead or refusing.
    Kept as the first try for X accounts in case an instance comes back.
  * Truth Social mirror https://www.trumpstruth.org/feed - WORKS, ~100 most recent Trump posts. Trump
    posts to Truth Social first, so this is the primary Trump source.
  * No free working source for @elonmusk; it is enabled but logs that every source failed.

Polling: default 30 s per account, staggered, with conditional requests (ETag / Last-Modified). The
5 s asked for would be ~17,000 requests a day per account against a free volunteer mirror, which gets
an IP blocked quickly, and the mirror itself only refreshes about once a minute.

    python3 monitor/twitter_monitor.py --backfill          # score the posts already in the feeds, exit
    python3 monitor/twitter_monitor.py --minutes 10        # run live for 10 minutes
    python3 monitor/twitter_monitor.py                     # run until stopped
"""
import argparse, collections, html, json, os, re, sys, time, email.utils
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
SIGNALS_FILE = HERE / "signals.jsonl"
WEBHOOK = os.environ.get("SIGNAL_WEBHOOK", "http://localhost:8000/api/signals")
UA = {"User-Agent": "Mozilla/5.0 (stock-agent signal monitor; personal research)"}
NITTER = ["https://nitter.net", "https://nitter.it", "https://nitter.poast.org", "https://nitter.privacydev.net"]

# account -> which sources to try, in order. Comment an account out to disable it.
ACCOUNTS = {
    "realDonaldTrump": {"kind": "trump", "sources": ["https://www.trumpstruth.org/feed"] + [f"{n}/realDonaldTrump/rss" for n in NITTER]},
    "elonmusk": {"kind": "elon", "sources": [f"{n}/elonmusk/rss" for n in NITTER]},
    # "WarrenBuffett": {"kind": "buffett", "sources": [f"{n}/WarrenBuffett/rss" for n in NITTER]},
    # "chamath": {"kind": "other", "sources": [f"{n}/chamath/rss" for n in NITTER]},
    # "BillAckman": {"kind": "other", "sources": [f"{n}/BillAckman/rss" for n in NITTER]},
    # "AP": {"kind": "news", "sources": [f"{n}/AP/rss" for n in NITTER]},
    # "Bloomberg": {"kind": "news", "sources": [f"{n}/business/rss" for n in NITTER]},
    # "Reuters": {"kind": "news", "sources": [f"{n}/Reuters/rss" for n in NITTER]},
}
CONFIDENCE = {"buffett": 0.9, "trump": 0.9, "elon": 0.7, "news": 0.6, "other": 0.5}

# Plain-name mentions that reliably mean one ticker. Cashtags ($TSLA) are always accepted.
NAMES = {
    "tesla": "TSLA", "spacex": None, "apple": "AAPL", "microsoft": "MSFT", "nvidia": "NVDA", "amazon": "AMZN",
    "google": "GOOGL", "alphabet": "GOOGL", "meta": "META", "facebook": "META", "intel": "INTC", "boeing": "BA",
    "ford": "F", "general motors": "GM", "exxon": "XOM", "chevron": "CVX", "lockheed": "LMT", "palantir": "PLTR",
    "coinbase": "COIN", "microstrategy": "MSTR", "strategy inc": "MSTR", "u.s. steel": "X", "us steel": "X",
    "nippon steel": None, "pfizer": "PFE", "walmart": "WMT", "truth social": "DJT",
    "trump media": "DJT", "oracle": "ORCL", "amd": "AMD", "tiktok": None,
}
NOT_TICKERS = {"A", "I", "USA", "US", "CEO", "AI", "GDP", "FBI", "CIA", "DOJ", "EU", "UK", "NATO", "MAGA", "RSS", "THE"}

BUY_WORDS = r"\b(buy(?:ing)?|bought|acquir(?:e|ed|ing)|stake|invest(?:ed|ing)?)\b"
SELL_WORDS = r"\b(short(?:ing)?|sell(?:ing)?|sold|exit(?:ed|ing)?|dump(?:ed|ing)?)\b"


def clean(s: str) -> str:
    s = re.sub(r"<!\[CDATA\[|\]\]>", "", s or "")
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def tickers_in(text: str) -> list[str]:
    found = [t.upper() for t in re.findall(r"\$([A-Za-z]{1,5})\b", text)]
    low = text.lower()
    for name, t in NAMES.items():
        if t and re.search(rf"\b{re.escape(name)}\b", low):
            found.append(t)
    out = []
    for t in found:
        if t not in NOT_TICKERS and t not in out:
            out.append(t)
    return out


def match(kind: str, text: str) -> list[tuple[str, str, float]]:
    """(action, ticker, confidence) for every pattern this post triggers. Exact combinations only."""
    low = text.lower()
    conf = CONFIDENCE.get(kind, 0.5)
    sig: list[tuple[str, str, float]] = []
    tks = tickers_in(text)
    buy, sell = re.search(BUY_WORDS, low), re.search(SELL_WORDS, low)
    for t in tks:
        if kind == "buffett" and buy:
            sig.append(("BUY", t, 0.9))
        elif buy and not sell:
            sig.append(("BUY", t, conf))
        elif sell and not buy:
            sig.append(("SELL", t, conf))
    if kind == "trump" and re.search(r"\b(tariffs?|war|sanctions?)\b", low):
        sig += [("BUY", "GLD", conf), ("SELL", "SPY", conf)]
    if kind == "trump" and re.search(r"\b(deal|peace|agreement)\b", low):
        sig.append(("BUY", "SPY", conf))
    if kind == "elon" and re.search(r"\b(bitcoin|crypto|dogecoin|doge)\b", low):
        sig += [("BUY", "COIN", conf), ("BUY", "MSTR", conf)]
    if kind == "news" and re.search(r"\bbreaking\b", low) and re.search(r"\b(merger|acquisition|acquire[sd]?)\b", low):
        sig += [("BUY", t, conf) for t in tks]
    seen, out = set(), []
    for s in sig:                                   # one signal per (action, ticker)
        if s[:2] not in seen:
            seen.add(s[:2]); out.append(s)
    return out


def parse_feed(body: str) -> list[dict]:
    posts = []
    for it in re.findall(r"<item>(.*?)</item>", body or "", re.S):
        g = lambda tag: (re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", it, re.S) or [None, ""])[1]
        pid = clean(g("guid")) or clean(g("link"))
        text = clean(g("description")) or clean(g("title"))
        try:
            ts = int(email.utils.parsedate_to_datetime(clean(g("pubDate"))).timestamp() * 1000)
        except Exception:
            ts = int(time.time() * 1000)
        if pid and text:
            posts.append({"id": pid, "text": text, "ts": ts, "link": clean(g("link"))})
    return posts


class Monitor:
    def __init__(self, accounts: dict):
        self.accounts = accounts
        self.seen: collections.deque = collections.deque(maxlen=500)
        self.seen_set: set = set()
        self.cache: dict = {}            # url -> (etag, last_modified, posts)
        self.working: dict = {}          # account -> index of the source that last worked

    def fetch(self, account: str) -> list[dict] | None:
        srcs = self.accounts[account]["sources"]
        start = self.working.get(account, 0)
        for i in list(range(start, len(srcs))) + list(range(0, start)):
            url = srcs[i]
            etag, lm, cached = self.cache.get(url, (None, None, None))
            h = dict(UA)
            if etag: h["If-None-Match"] = etag
            if lm: h["If-Modified-Since"] = lm
            try:
                r = requests.get(url, headers=h, timeout=10, allow_redirects=True)
                if r.status_code == 304 and cached is not None:
                    self.working[account] = i
                    return cached
                if r.status_code != 200:
                    continue
                posts = parse_feed(r.text)
                if not posts:
                    continue
                self.cache[url] = (r.headers.get("ETag"), r.headers.get("Last-Modified"), posts)
                self.working[account] = i
                return posts
            except Exception:
                continue
        return None

    def remember(self, pid: str) -> bool:
        if pid in self.seen_set:
            return False
        if len(self.seen) == self.seen.maxlen:
            self.seen_set.discard(self.seen[0])
        self.seen.append(pid); self.seen_set.add(pid)
        return True

    def emit(self, author: str, action: str, ticker: str, conf: float, post: dict, send: bool = True) -> dict:
        snippet = post["text"][:240]
        payload = {"source": "twitter", "author": author, "ticker": ticker, "action": action,
                   "confidence": round(conf, 2), "text_snippet": snippet, "timestamp_ms": post["ts"], "link": post.get("link")}
        print(f"SIGNAL: {action} {ticker} @ {conf:.1f} from @{author}: {snippet[:140]}", flush=True)
        try:
            with SIGNALS_FILE.open("a") as f:
                f.write(json.dumps({**payload, "logged_ms": int(time.time() * 1000)}) + "\n")
        except Exception as e:
            print(f"(could not write signals.jsonl: {e})", flush=True)
        if send:
            for attempt in (1, 2):
                try:
                    r = requests.post(WEBHOOK, json=payload, timeout=5)
                    print(f"Webhook: {r.status_code}", flush=True); break
                except Exception as e:
                    print(f"Webhook: failed ({type(e).__name__}){' - retrying' if attempt == 1 else ''}", flush=True)
        return payload

    def check(self, account: str, prime: bool = False, send: bool = True) -> list[dict]:
        print(f"Checking {account}...", flush=True)
        posts = self.fetch(account)
        if posts is None:
            print(f"  (no working source for @{account} right now)", flush=True)
            return []
        out = []
        for post in sorted(posts, key=lambda p: p["ts"]):
            if not self.remember(post["id"]) or prime:
                continue
            for action, ticker, conf in match(self.accounts[account]["kind"], post["text"]):
                out.append(self.emit(account, action, ticker, conf, post, send))
        return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true", help="score the posts already in each feed, then exit")
    ap.add_argument("--minutes", type=float, default=0, help="stop after this many minutes (0 = run until stopped)")
    ap.add_argument("--interval", type=float, default=float(os.environ.get("MONITOR_INTERVAL", 30)))
    a = ap.parse_args()
    m = Monitor(ACCOUNTS)
    names = list(ACCOUNTS)
    if a.backfill:
        total = 0
        for acct in names:
            total += len(m.check(acct, send=False))
        print(f"backfill: {total} signal(s) across {len(names)} account(s)", flush=True)
        return 0
    for acct in names:                       # posts already in the feed at start-up are history, not news
        try: m.check(acct, prime=True)
        except Exception as e: print(f"(start-up check failed for {acct}: {e})", flush=True)
    stop_at = time.time() + a.minutes * 60 if a.minutes else None
    gap = max(1.0, a.interval / max(1, len(names)))
    while stop_at is None or time.time() < stop_at:
        for acct in names:
            try:
                m.check(acct)
            except Exception as e:           # never let one bad post or feed stop the monitor
                print(f"(check failed for {acct}: {type(e).__name__}: {e})", flush=True)
            time.sleep(gap)
    print("monitor stopped", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
