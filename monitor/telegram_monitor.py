"""Telegram channel signal monitor - WATCH ONLY. It never trades and is not imported by the agent.

Watches public news channels, matches fixed keyword/ticker rules, and for each hit logs a line,
appends it to monitor/telegram_signals.jsonl and POSTs it to a webhook (nothing listens there yet).

Two ways to read channels:
  * live (instant push, needs keys): Telethon with api_id/api_hash from my.telegram.org in
    config/telegram_config.json. The first run asks for your phone number and a login code - type
    them yourself. It then keeps a .session file; that file IS your Telegram login, never share it.
  * preview (no keys): polls each channel's public web page https://t.me/s/<channel> every 15 s.
    Works tonight with no account; a few seconds to ~20 s slower than live.

Channels verified 2026-09-16 (public, active): WalterBloomberg, FinancialJuice, WatcherGuru,
disclosetv, News_Crypto. The originally requested ElonMuskNews, TrumpNewsFeed, BuffettUpdates and
DeItaoneFeed do not exist as public channels.

    python3 monitor/telegram_monitor.py --backfill            # score messages already on each channel page
    python3 monitor/telegram_monitor.py --mode preview        # poll public pages (no keys)
    python3 monitor/telegram_monitor.py --mode live           # Telethon push (needs keys)
"""
import argparse, asyncio, collections, html, json, re, sys, time
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "telegram_config.json"
EXAMPLE = ROOT / "config" / "telegram_config.example.json"
SIGNALS = ROOT / "monitor" / "telegram_signals.jsonl"
UA = {"User-Agent": "Mozilla/5.0 (stock-agent telegram monitor; personal research)"}
DEFAULTS = {"channels": ["FinancialJuice"], "webhook_url": "http://localhost:8000/api/signals",
            "session_name": "config/telegram_monitor", "poll_seconds": 15}

# (pattern, action, ticker, confidence) - word boundaries so "btc" never matches inside another word
RULES = [
    (r"\b(bitcoin|btc|crypto)\b", "BUY", "COIN", 0.7),
    (r"\b(dogecoin|doge)\b", "BUY", "DOGE", 0.6),
    (r"\b(war|iran|attacks?)\b", "BUY", "GLD", 0.8),
    (r"\b(tariffs?|tax increases?)\b", "SELL", "SPY", 0.7),
    (r"\b(deal|peace|agreement)\b", "BUY", "SPY", 0.75),
]
BUY_WORDS = r"\b(buying|bought|stake|bull(ish)?|long(?!-term))\b"
SELL_WORDS = r"\b(selling|sold|exit(s|ed|ing)?|bear(ish)?|short(s|ing)?)\b"
# channel tags and currencies written with a $ that are not tradeable tickers
NOT_TICKERS = {"MACRO", "USD", "EUR", "GBP", "JPY", "CNY", "FX", "NEWS", "CPI", "GDP", "FOMC"}
AUTHORS = [(r"\btrump\b", "trump"), (r"\b(elon|musk)\b", "elonmusk"), (r"\b(buffett|berkshire)\b", "buffett")]


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    for f in (CONFIG, EXAMPLE):
        if f.exists():
            try:
                cfg.update(json.loads(f.read_text())); break
            except Exception as e:
                print(f"(could not read {f.name}: {e})", flush=True)
    cfg["channels"] = [str(c).lstrip("@") for c in cfg.get("channels", [])]
    return cfg


def signals_for(text: str) -> list[tuple[str, str, float]]:
    low = text.lower()
    out = [(a, t, c) for pat, a, t, c in RULES if re.search(pat, low)]
    tickers = [m.upper() for m in re.findall(r"\$([A-Za-z]{1,5})\b", text) if m.upper() not in NOT_TICKERS]
    buy, sell = re.search(BUY_WORDS, low), re.search(SELL_WORDS, low)
    for t in tickers:
        if buy and not sell:
            out.append(("BUY", t, 0.9))
        elif sell and not buy:
            out.append(("SELL", t, 0.85))
    seen, uniq = set(), []
    for s in out:
        if s[:2] not in seen:
            seen.add(s[:2]); uniq.append(s)
    return uniq


def author_for(channel: str, text: str) -> str:
    low = text.lower()
    return next((name for pat, name in AUTHORS if re.search(pat, low)), channel)


class Sink:
    def __init__(self, webhook: str):
        self.webhook = webhook
        self.seen = collections.deque(maxlen=2000); self.seen_set = set()

    def new(self, key: str) -> bool:
        if key in self.seen_set:
            return False
        if len(self.seen) == self.seen.maxlen:
            self.seen_set.discard(self.seen[0])
        self.seen.append(key); self.seen_set.add(key)
        return True

    def handle(self, channel: str, text: str, ts_ms: int, send: bool = True) -> list[dict]:
        out = []
        for action, ticker, conf in signals_for(text):
            payload = {"source": "telegram", "channel": channel, "author_inferred": author_for(channel, text),
                       "action": action, "ticker": ticker, "confidence": conf,
                       "text_snippet": text[:100], "timestamp_ms": ts_ms}
            print(f"Signal from {channel}: {action} {ticker} @ {conf} | {text[:90]}", flush=True)
            try:
                with SIGNALS.open("a") as f:
                    f.write(json.dumps({**payload, "logged_ms": int(time.time() * 1000)}) + "\n")
            except Exception as e:
                print(f"(could not write {SIGNALS.name}: {e})", flush=True)
            if send:
                try:
                    r = requests.post(self.webhook, json=payload, timeout=5)
                    print(f"Webhook sent: {r.status_code}", flush=True)
                except Exception as e:
                    print(f"Webhook sent: failed ({type(e).__name__}) - continuing", flush=True)
            out.append(payload)
        return out


def clean(s: str) -> str:
    s = re.sub(r"<br\s*/?>", " ", s or "")
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def preview_messages(channel: str) -> list[tuple[str, str, int]] | None:
    """(message_id, text, timestamp_ms) from the public web preview, oldest first. None if unreadable."""
    try:
        r = requests.get(f"https://t.me/s/{channel}", headers=UA, timeout=15)
        if r.status_code != 200 or "tgme_channel_info" not in r.text:
            return None
    except Exception:
        return None
    msgs = []
    for block in re.split(r'(?=<div class="tgme_widget_message_wrap)', r.text)[1:]:
        mid = re.search(r'data-post="([^"]+)"', block)
        txt = re.search(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', block, re.S)
        tm = re.search(r'<time datetime="([^"]+)"', block)
        if not (mid and txt):
            continue
        try:
            ts = int(datetime.fromisoformat(tm.group(1)).timestamp() * 1000) if tm else int(time.time() * 1000)
        except Exception:
            ts = int(time.time() * 1000)
        msgs.append((mid.group(1), clean(txt.group(1)), ts))
    return msgs


def run_preview(cfg: dict, backfill: bool, minutes: float) -> int:
    sink = Sink(cfg["webhook_url"])
    chans = cfg["channels"]
    ok = [c for c in chans if preview_messages(c) is not None]
    for c in set(chans) - set(ok):
        print(f"(channel @{c} not accessible - skipped)", flush=True)
    print(f"Connected to Telegram (public preview, no keys)", flush=True)
    print(f"Monitoring {len(ok)} channels: {', '.join(ok)}", flush=True)
    if backfill:
        n = 0
        for c in ok:
            for mid, text, ts in preview_messages(c) or []:
                n += len(sink.handle(c, text, ts, send=False))
        print(f"backfill: {n} signal(s)", flush=True)
        return 0
    for c in ok:                                   # messages already on the page are history
        for mid, _, _ in preview_messages(c) or []:
            sink.new(mid)
    stop = time.time() + minutes * 60 if minutes else None
    while stop is None or time.time() < stop:
        for c in ok:
            try:
                for mid, text, ts in preview_messages(c) or []:
                    if sink.new(mid):
                        sink.handle(c, text, ts)
            except Exception as e:
                print(f"(check failed for @{c}: {type(e).__name__}: {e})", flush=True)
            time.sleep(max(1.0, cfg.get("poll_seconds", 15) / max(1, len(ok))))
    return 0


async def run_live(cfg: dict) -> int:
    try:
        from telethon import TelegramClient, events
    except ImportError:
        print("Telethon is not installed: run  py -m pip install telethon", flush=True); return 1
    if not cfg.get("api_id") or str(cfg.get("api_hash", "")).startswith("your_"):
        print("config/telegram_config.json needs your api_id and api_hash from my.telegram.org", flush=True); return 1
    sink = Sink(cfg["webhook_url"])
    client = TelegramClient(str(ROOT / cfg["session_name"]), int(cfg["api_id"]), cfg["api_hash"])
    await client.start()
    print("Connected to Telegram", flush=True)
    entities = []
    for c in cfg["channels"]:
        try:
            entities.append(await client.get_entity(c))
        except Exception as e:
            print(f"(channel @{c} not accessible - skipped: {type(e).__name__})", flush=True)
    print(f"Monitoring {len(entities)} channels", flush=True)
    if not entities:
        return 1

    @client.on(events.NewMessage(chats=entities))
    async def on_message(event):
        try:
            chat = await event.get_chat()
            name = getattr(chat, "username", None) or str(event.chat_id)
            text = event.raw_text or ""
            if text and sink.new(f"{name}/{event.id}"):
                await asyncio.to_thread(sink.handle, name, text, int(event.date.timestamp() * 1000))
        except Exception as e:                     # never let one message stop the monitor
            print(f"(message handling failed: {type(e).__name__}: {e})", flush=True)

    await client.run_until_disconnected()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["preview", "live"], default="preview")
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument("--minutes", type=float, default=0)
    a = ap.parse_args()
    cfg = load_config()
    if a.mode == "live" and not a.backfill:
        return asyncio.run(run_live(cfg))
    return run_preview(cfg, a.backfill, a.minutes)


if __name__ == "__main__":
    sys.exit(main())
