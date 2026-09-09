"""Watch what specific traders are actually buying, straight from the chain.

This is the part of FOMO that is worth having, without FOMO. Its app shows you a feed of what
the traders you follow are buying; that feed is assembled from public on-chain activity, so the
same information is readable directly — free, with no key, no login, and no app in the middle.
Reading the chain is also strictly faster than reading someone's rendering of it.

What this needs from you is the one thing that cannot be derived: WHICH wallets to watch. A
handle inside an app is not an identity anyone else can resolve; a wallet address is. Put the
addresses in config.yaml under `followed_wallets` and the agent watches them every check.

    followed_wallets:
      - { name: "jake",  address: "7xKX...", note: "found via fomo" }

Deliberate limits. The public RPC is rate-limited and shared, so this looks at a handful of
wallets and their most recent transactions, not a full history. It reports what moved, never
why, and a wallet buying something is evidence about that wallet — not a reason to buy.
"""
import json
import time
import urllib.request
from datetime import datetime, timezone

RPC = "https://api.mainnet-beta.solana.com"
TIMEOUT = 25
MAX_WALLETS = 8                    # the shared public endpoint is not a firehose
MAX_TX_PER_WALLET = 8
SOL_MINT = "So11111111111111111111111111111111111111112"
STABLES = {"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",   # USDC
           "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"}   # USDT

def _rpc(method: str, params: list):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(RPC, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        return None if d.get("error") else d.get("result")
    except Exception:
        return None

def _signatures(wallet: str, limit: int) -> list[dict]:
    return _rpc("getSignaturesForAddress", [wallet, {"limit": limit}]) or []

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
            if b.get("owner") != wallet:
                continue
            dst[b["mint"]] = float((b.get("uiTokenAmount") or {}).get("uiAmount") or 0)
    when = r.get("blockTime")
    out = []
    for mint in set(pre) | set(post):
        delta = post.get(mint, 0) - pre.get(mint, 0)
        if abs(delta) < 1e-9 or mint in STABLES or mint == SOL_MINT:
            continue                                   # the cash leg, not the position
        out.append({"mint": mint, "side": "buy" if delta > 0 else "sell", "qty": abs(delta),
                    "ts": when, "when": datetime.fromtimestamp(when, timezone.utc).isoformat(timespec="minutes") if when else None,
                    "sig": sig})
    return out

def recent(wallets: list[dict], per_wallet: int = MAX_TX_PER_WALLET, pause: float = 0.25) -> list[dict]:
    """Recent token moves for each followed wallet, newest first."""
    out = []
    for w in (wallets or [])[:MAX_WALLETS]:
        addr = (w.get("address") or "").strip() if isinstance(w, dict) else str(w).strip()
        name = (w.get("name") if isinstance(w, dict) else None) or (addr[:6] + "…" if addr else "?")
        if len(addr) < 32:
            continue
        for s in _signatures(addr, per_wallet):
            for mv in _decode(s["signature"], addr):
                out.append({**mv, "who": name, "wallet": addr})
            time.sleep(pause)                          # the public endpoint is shared; be a good citizen
    return sorted(out, key=lambda r: -(r["ts"] or 0))

def pressure(moves: list[dict], hours: int = 24) -> dict:
    """{mint: net followed-wallet buying} over the window, so it can rank like the other feeds."""
    cutoff = time.time() - hours * 3600
    score: dict[str, float] = {}
    for m in moves:
        if not m.get("ts") or m["ts"] < cutoff:
            continue
        score[m["mint"]] = score.get(m["mint"], 0) + (1 if m["side"] == "buy" else -1)
    return dict(sorted(score.items(), key=lambda kv: -kv[1]))

def summary(moves: list[dict], limit: int = 20) -> list[dict]:
    """Readable feed for the brain and the dashboard: who bought what, when."""
    return [{"who": m["who"], "side": m["side"], "mint": m["mint"], "qty": round(m["qty"], 4),
             "when": m["when"]} for m in moves[:limit]]
