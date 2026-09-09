"""Watch what specific traders are actually buying, straight from the chain.

This is the part of FOMO that is worth having, without FOMO. Its app shows a feed of what the
traders you follow are buying; that feed is assembled from public on-chain activity, so the same
information is readable directly - free, no key, no login, no app in the middle. Reading the
chain is also strictly faster than reading someone else's rendering of it.

It needs the one thing that cannot be derived: WHICH wallets. A handle inside an app is not an
identity anyone outside it can resolve; an address is. They live in **wallets.txt**, one per
line, editable straight from github.com. The agent reads that file on its next check, so there
is nothing to connect and no key to add.

The list is unbounded. The public Solana RPC is shared and rate-limited, so each pass visits a
few wallets and remembers where it stopped, resuming there next time. A long list means each
wallet is visited less often - never that the list is cut off. With a check every few minutes,
a hundred wallets still come round roughly twice an hour.

It reports what moved, never why. A wallet buying something is evidence about that wallet, not
a reason to buy.
"""
import json
import re
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIST_FILE = ROOT / "wallets.txt"
CURSOR_FILE = ROOT / ".cache" / "wallet_cursor.json"

RPC = "https://api.mainnet-beta.solana.com"
TIMEOUT = 25
PER_PASS = 8                       # wallets visited per check; the rest wait their turn
MAX_TX_PER_WALLET = 8
SOL_MINT = "So11111111111111111111111111111111111111112"
STABLES = {"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",   # USDC
           "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"}   # USDT
# base58 has no 0, O, I or l - so a typo is caught here rather than wasting a request
ADDRESS = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")

def parse(text: str) -> list[dict]:
    """Read the wallet list. Tolerant on purpose: this file is edited by hand on a phone.

    Accepts `address`, `address, name` or `address, name, note`, ignores blank lines and
    anything after a #, and silently drops entries that are not valid base58 addresses so one
    bad paste cannot break a check.
    """
    out, seen = [], set()
    for raw in (text or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        addr = parts[0]
        if not ADDRESS.match(addr) or addr in seen:
            continue
        seen.add(addr)
        out.append({"address": addr,
                    "name": (parts[1] if len(parts) > 1 and parts[1] else addr[:4] + "…" + addr[-4:]),
                    "note": parts[2] if len(parts) > 2 else ""})
    return out

def followed() -> list[dict]:
    try:
        return parse(LIST_FILE.read_text())
    except Exception:
        return []

def _cursor() -> int:
    try:
        return int(json.loads(CURSOR_FILE.read_text()).get("i", 0))
    except Exception:
        return 0

def _save_cursor(i: int) -> None:
    try:
        CURSOR_FILE.parent.mkdir(parents=True, exist_ok=True)
        CURSOR_FILE.write_text(json.dumps({"i": int(i)}))
    except Exception:
        pass

def due(all_wallets: list[dict], per_pass: int = PER_PASS) -> tuple[list[dict], int, int]:
    """The slice to check now, resuming where the last pass stopped. (slice, start, total)."""
    n = len(all_wallets)
    if n == 0:
        return [], 0, 0
    start = _cursor() % n
    take = min(per_pass, n)
    rotated = [all_wallets[(start + k) % n] for k in range(take)]
    _save_cursor((start + take) % n)
    return rotated, start, n

def _rpc(method: str, params: list):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(RPC, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        return None if d.get("error") else d.get("result")
    except Exception:
        return None

def _decode(sig: str, wallet: str) -> list[dict]:
    """What this transaction did to THIS wallet's token balances."""
    r = _rpc("getTransaction", [sig, {"maxSupportedTransactionVersion": 0, "encoding": "jsonParsed"}])
    if not r:
        return []
    meta = r.get("meta") or {}
    if meta.get("err"):
        return []
    pre, post = {}, {}
    for src, dst in ((meta.get("preTokenBalances") or [], pre), (meta.get("postTokenBalances") or [], post)):
        for b in src:
            if b.get("owner") == wallet:
                dst[b["mint"]] = float((b.get("uiTokenAmount") or {}).get("uiAmount") or 0)
    when = r.get("blockTime")
    out = []
    for mint in set(pre) | set(post):
        delta = post.get(mint, 0) - pre.get(mint, 0)
        if abs(delta) < 1e-9 or mint in STABLES or mint == SOL_MINT:
            continue                                   # the cash leg, not the position
        out.append({"mint": mint, "side": "buy" if delta > 0 else "sell", "qty": abs(delta),
                    "ts": when, "sig": sig,
                    "when": datetime.fromtimestamp(when, timezone.utc).isoformat(timespec="minutes") if when else None})
    return out

def recent(wallets: list[dict], per_wallet: int = MAX_TX_PER_WALLET, pause: float = 0.25) -> list[dict]:
    """Recent token moves for the wallets given, newest first."""
    out = []
    for w in wallets or []:
        addr = (w.get("address") or "").strip() if isinstance(w, dict) else str(w).strip()
        if not ADDRESS.match(addr):
            continue
        name = (w.get("name") if isinstance(w, dict) else None) or addr[:6] + "…"
        for s in _rpc("getSignaturesForAddress", [addr, {"limit": per_wallet}]) or []:
            for mv in _decode(s["signature"], addr):
                out.append({**mv, "who": name, "wallet": addr})
            time.sleep(pause)                          # the public endpoint is shared; be a good citizen
    return sorted(out, key=lambda r: -(r["ts"] or 0))

def check_due(per_pass: int = PER_PASS) -> tuple[list[dict], dict]:
    """One pass: take the next slice of the list and read it. Returns (moves, status)."""
    all_w = followed()
    slice_, start, total = due(all_w, per_pass)
    moves = recent(slice_) if slice_ else []
    return moves, {"followed_total": total, "checked_this_pass": len(slice_),
                   "starting_at": start, "names": [w["name"] for w in slice_]}

def pressure(moves: list[dict], hours: int = 24) -> dict:
    """{mint: net followed-wallet buying} over the window, so it ranks like the other feeds."""
    cutoff = time.time() - hours * 3600
    score: dict[str, float] = {}
    for m in moves:
        if m.get("ts") and m["ts"] >= cutoff:
            score[m["mint"]] = score.get(m["mint"], 0) + (1 if m["side"] == "buy" else -1)
    return dict(sorted(score.items(), key=lambda kv: -kv[1]))

def summary(moves: list[dict], limit: int = 20) -> list[dict]:
    """Readable feed for the brain and the dashboard: who bought what, when."""
    return [{"who": m["who"], "side": m["side"], "mint": m["mint"], "qty": round(m["qty"], 4),
             "when": m["when"]} for m in moves[:limit]]
