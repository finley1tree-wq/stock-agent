"""A queue of A/B experiments on how a position is managed, run one at a time; each winner is kept.

Owner's instruction, 2026-10-01: "keep trying different methods and see which ones stick." The
30- vs 90-minute hold trial (2026-09-29) was the first; it decided on 10-01 for 90 minutes
(t 2.22). This generalises it: guardrails.experiments lists two-arm experiments, each changing one
per-position setting. They run in order. While one is running, every NEW position gets one of its
two arms by a fair coin, and every setting decided by an earlier experiment is applied as decided.
When it decides (evolve.trial: both arms >= min_trips_per_arm and Welch t >= decide_t, or the higher
mean at max_trips_per_arm each), its winner becomes the setting and the next experiment starts.
Decisions are recomputed from the journal in trade order and are final.

Settings an experiment may vary (per position, so both arms run side by side in the same market):
    hold_minutes   the hold clock (time_stops)
    ratchet        "on" = config's ratchet; "off" = the stop never climbs (auto_bracket override)

The arm a position was given is stored in state exp_arm and written on its journal buy row as
experiments: {name: arm} (and hold_minutes, which the first trial read). Pure stdlib.
"""
import random

from . import evolve

DEFAULT_RULES = {"min_trips_per_arm": 40, "decide_t": 2.0, "max_trips_per_arm": 150}
CAST = {"hold_minutes": int, "ratchet": lambda v: "on" if str(v).lower() in ("on", "true", "1", "yes") else "off"}


def queue(g: dict) -> list[dict]:
    """guardrails.experiments as a list of {name, param, arms, rules...}; the legacy hold_trial
    block counts as a one-item queue."""
    ex = g.get("experiments")
    if ex is None:
        t = evolve.trial_settings(g)
        return [] if t is None else [{**t, "name": "hold", "param": "hold_minutes"}]
    if not ex:
        return []
    rules = {**DEFAULT_RULES, **(g.get("experiment_rules") or {})}
    out = []
    for e in ex:
        if not isinstance(e, dict) or e.get("enabled") is False or e.get("param") not in CAST:
            continue
        arms = [CAST[e["param"]](a) for a in (e.get("arms") or [])][:2]
        if len(arms) == 2 and arms[0] != arms[1]:
            out.append({**rules, **e, "arms": arms})
    return out


def _arm_of(name: str):
    def f(trip):
        x = trip.get("exp")
        if isinstance(x, dict):
            return x.get(name)
        return trip.get("hold") if name == "hold" else None     # the first trial predates the tag
    return f


def standings(g: dict, rows: list[dict] | None = None) -> list[dict]:
    """Every experiment's standing, in order: decided, the one running, then the queued ones."""
    q = queue(g)
    if not q:
        return []
    rows = rows if rows is not None else (evolve._rows() or [])
    out, running = [], False
    for e in q:
        r = evolve.trial(rows, e, _arm_of(e["name"]))
        r.update(name=e["name"], param=e["param"], note=e.get("note", ""))
        if running:
            r["status"] = "queued"
        elif r["winner"] is not None:
            r["status"] = "decided"
        else:
            r["status"] = "running"
            running = True
        out.append(r)
    return out


def current(g: dict, rows: list[dict] | None = None) -> tuple[dict | None, dict]:
    """(the running experiment or None, {param: value} fixed by decided ones, later ones winning)."""
    fixed, active = {}, None
    for r in standings(g, rows):
        if r["status"] == "decided":
            fixed[r["param"]] = r["winner"]
        elif r["status"] == "running":
            active = r
            break
    return active, fixed


def assign(st: dict, g: dict, ticker: str, held: set, rows: list[dict] | None = None,
           rng=random.random) -> dict | None:
    """Settings for a buy of `ticker`: {"params": {param: value}, "tags": {experiment: arm}}, or
    None when no experiments are configured. An add to a held position keeps that position's."""
    if not queue(g):
        return None
    store = st.setdefault("exp_arm", {})
    for t in [t for t in store if t not in held]:
        store.pop(t, None)                       # positions that have closed since
    if ticker in held and ticker in store:
        return store[ticker]
    active, fixed = current(g, rows)
    rec = {"params": dict(fixed), "tags": {}}
    if active:
        arm = active["settings"]["arms"][0 if rng() < 0.5 else 1]
        rec["params"][active["param"]] = arm
        rec["tags"][active["name"]] = arm
    store[ticker] = rec
    return rec


def hold_for(st: dict, g: dict, ticker: str, default: int) -> int:
    """The hold clock a held position runs on."""
    rec = (st.get("exp_arm") or {}).get(ticker)
    if rec and rec.get("params", {}).get("hold_minutes"):
        return int(rec["params"]["hold_minutes"])
    legacy = (st.get("hold_arm") or {}).get(ticker)       # positions opened under the first trial
    return int(legacy) if legacy and queue(g) else default


def bracket_overrides(st: dict, ratchet_off: dict | None = None) -> dict:
    """{ticker: auto_bracket overrides} for held positions whose experiment arm changes the bracket."""
    out = {}
    for t, rec in (st.get("exp_arm") or {}).items():
        if (rec.get("params") or {}).get("ratchet") == "off":
            out[t] = {"ratchet_after_pct_of_target": 0, **(ratchet_off or {})}
    return out


def journal_tags(rec: dict | None) -> dict:
    """Fields to write on the journal buy row."""
    if not rec:
        return {}
    out = {"experiments": dict(rec.get("tags") or {})}
    if rec.get("params", {}).get("hold_minutes"):
        out["hold_minutes"] = int(rec["params"]["hold_minutes"])
    return out
