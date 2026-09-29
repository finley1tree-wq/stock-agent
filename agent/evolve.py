"""Natural selection over entry strategies, rescored from journal.json at every check.

The same idea as the crypto trader's evolve step: every entry strategy is an organism, the journal
is its fitness record, and money follows the evidence. Two lenses, each a set of organisms:

    hour     the New York hour the entry was taken in ("09".."15")
    signals  the entry's real reasons, mechanism tags stripped (selection.MECHANICS), e.g.
             "congress+momentum"

Fitness is net realised P/L per closed round trip, after costs, with t = mean / (sd / sqrt(n)).
Fills the dashboard flags as simulator errors (a single sell booking 50% or more) never count.

    SURVIVOR   n >= min_trips and t >= survive_t    full size
    CULLED     n >= min_trips and t <= cull_t       no new entries
    PROBATION  everything else                      probation_size of the order, so an unproven
                                                    strategy keeps earning evidence cheaply

An entry is blocked if ANY lens culls it. Otherwise its size is the BEST weight any lens gives it:
a 09:00 entry is a survivor whatever its signal mix happens to be.

Culling asks for less evidence than surviving on purpose. A trade that shows no edge still pays the
spread twice, so not taking a losing-looking one saves money even if the loss was partly luck;
paying full size for a winning-looking one needs the stronger case.

Measured at the time of writing (843 round trips, 2026-09-08..09-29, after costs):
    09h +$469 n=161 t=+2.55 -> SURVIVOR      14h -$308 n=107 t=-2.20 -> CULLED
    15h  -$91 n=38  t=-1.44 -> CULLED        10h..13h, every signal mix -> PROBATION (|t| < 1.4)
Stages are recomputed from the journal every check, so organisms graduate and die on their own.

Pure standard library: no network, no broker, no model.
"""
import json
from datetime import date
import math
from pathlib import Path

from .selection import MECHANICS

ROOT = Path(__file__).resolve().parent.parent
JOURNAL = ROOT / "journal.json"
OUT = ROOT / "site" / "data" / "evolve.json"

SURVIVOR, PROBATION, CULLED = "SURVIVOR", "PROBATION", "CULLED"
FLAG_PCT = 50.0            # same rule the dashboard uses for a simulator-error fill

DEFAULTS = {"min_trips": 30, "survive_t": 2.0, "cull_t": -1.0, "probation_size": 0.25}


def settings(g: dict) -> dict | None:
    """guardrails.evolve merged over the defaults, or None when switched off."""
    cfg = g.get("evolve")
    if cfg is None or cfg is False or (isinstance(cfg, dict) and cfg.get("enabled") is False):
        return None
    return {**DEFAULTS, **(cfg if isinstance(cfg, dict) else {})}


def signal_key(signals) -> str:
    real = sorted({s for s in (signals or []) if isinstance(s, str)} - MECHANICS - {"unspecified"})
    return "+".join(real) or "none"


def hour_key(hour) -> str:
    return f"{int(hour):02d}"


def round_trips(rows: list[dict]) -> list[dict]:
    """One row per filled sell, carrying the signals and hour of the buy that OPENED the position."""
    held: dict[str, dict] = {}
    out = []
    for r in rows:
        if r.get("status") != "filled":
            continue
        sym, side, qty = r.get("symbol"), r.get("side", "buy"), float(r.get("qty") or 0)
        if side == "buy":
            pos = held.get(sym)
            if pos is None:
                held[sym] = {"entry": r, "qty": qty}
            else:
                pos["qty"] += qty
            continue
        pos = held.get(sym)
        if pos is None:
            continue
        e = pos["entry"]
        pct = r.get("realized_pct")
        hour = e.get("hour_et")
        if hour is None and str(e.get("time_et", ""))[:2].isdigit():
            hour = int(str(e["time_et"])[:2])
        out.append({"symbol": sym, "date": e.get("date"), "hour": hour, "signals": e.get("signals") or [],
                    "pnl": float(r.get("realized_pnl") or 0), "trigger": r.get("trigger"),
                    "flagged": pct is not None and abs(float(pct)) >= FLAG_PCT})
        pos["qty"] -= qty
        if pos["qty"] <= max(1e-6, 0.001 * qty):
            held.pop(sym, None)
    return out


def _stats(pnls: list[float]) -> dict:
    n = len(pnls)
    total = sum(pnls)
    mean = total / n if n else 0.0
    sd = math.sqrt(sum((p - mean) ** 2 for p in pnls) / (n - 1)) if n > 1 else 0.0
    t = mean / (sd / math.sqrt(n)) if sd > 0 else 0.0
    return {"n": n, "net": round(total, 2), "mean": round(mean, 3), "t": round(t, 2),
            "win_rate": round(sum(p > 0 for p in pnls) / n, 3) if n else None}


def _stage(s: dict, cfg: dict) -> str:
    if s["n"] >= cfg["min_trips"] and s["t"] >= cfg["survive_t"] and s["mean"] > 0:
        return SURVIVOR
    if s["n"] >= cfg["min_trips"] and s["t"] <= cfg["cull_t"] and s["mean"] < 0:
        return CULLED
    return PROBATION


def score(rows: list[dict], cfg: dict) -> dict:
    trips = [t for t in round_trips(rows) if not t["flagged"]]
    lenses = {"hour": lambda t: hour_key(t["hour"]) if t["hour"] is not None else None,
              "signals": lambda t: signal_key(t["signals"])}
    out = {"settings": cfg, "trips": len(trips), "lenses": {}}
    for name, key in lenses.items():
        groups: dict[str, list[dict]] = {}
        for t in trips:
            k = key(t)
            if k is not None:
                groups.setdefault(k, []).append(t)
        orgs = {}
        for k, ts in groups.items():
            s = _stats([t["pnl"] for t in ts])
            weeks: dict[str, float] = {}
            for t in ts:
                if t["date"]:
                    y, w, _ = date.fromisoformat(t["date"]).isocalendar()
                    wk = f"{y}-W{w:02d}"
                    weeks[wk] = round(weeks.get(wk, 0.0) + t["pnl"], 2)
            orgs[k] = {**s, "stage": _stage(s, cfg), "weeks": dict(sorted(weeks.items()))}
        out["lenses"][name] = dict(sorted(orgs.items()))
    return out


def _weight(stage: str, cfg: dict) -> float:
    return {SURVIVOR: 1.0, CULLED: 0.0}.get(stage, float(cfg["probation_size"]))


def verdict(scores: dict, signals, hour) -> tuple[float, str]:
    """(size multiplier, why) for a NEW entry. A multiplier of 0 means blocked."""
    cfg = scores["settings"]
    keys = {"hour": hour_key(hour) if hour is not None else None, "signals": signal_key(signals)}
    found = []
    for lens, k in keys.items():
        org = scores["lenses"].get(lens, {}).get(k) if k is not None else None
        found.append((lens, k, org["stage"] if org else PROBATION, org))
    for lens, k, stage, org in found:
        if stage == CULLED:
            return 0.0, f"culled strategy ({lens} {k}: {org['net']:+.0f} over {org['n']} trips, t {org['t']:+.2f})"
    lens, k, stage, org = max(found, key=lambda f: _weight(f[2], cfg))
    w = _weight(stage, cfg)
    if stage == SURVIVOR:
        return w, f"survivor ({lens} {k}: {org['net']:+.0f} over {org['n']} trips, t {org['t']:+.2f})"
    return w, f"probation at {w:.0%} size (no {lens} or signal lens has proven itself yet)"


_CACHE: dict = {}


def load(g: dict, rows: list[dict] | None = None) -> dict | None:
    """Scores for this check, or None when guardrails.evolve is off. Cached on the journal's mtime."""
    cfg = settings(g)
    if cfg is None:
        return None
    if rows is None:
        try:
            stamp = JOURNAL.stat().st_mtime_ns
        except OSError:
            return None
        key = (stamp, json.dumps(cfg, sort_keys=True))
        if _CACHE.get("key") == key:
            return _CACHE["scores"]
        try:
            rows = json.loads(JOURNAL.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        _CACHE.update(key=key, scores=score(rows, cfg))
        return _CACHE["scores"]
    return score(rows, cfg)


def summary(scores: dict | None) -> dict:
    """Compact stage map for the model's context: {"hour": {"09": "SURVIVOR", ...}, "signals": {...}}."""
    if not scores:
        return {}
    return {lens: {k: o["stage"] for k, o in orgs.items() if o["n"] >= 5}
            for lens, orgs in scores["lenses"].items()}


def write(scores: dict | None, generated_at: str) -> None:
    if not scores:
        return
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"generated_at": generated_at, **scores}, indent=1), encoding="utf-8")


if __name__ == "__main__":
    from datetime import datetime, timezone
    s = load({"evolve": {}})
    for lens, orgs in s["lenses"].items():
        print(f"== {lens}")
        for k, o in orgs.items():
            print(f"  {k:32} {o['stage']:9} n={o['n']:4} net={o['net']:+9.2f} t={o['t']:+.2f}")
    write(s, datetime.now(timezone.utc).isoformat(timespec="seconds"))
