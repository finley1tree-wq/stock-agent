"""Which build of the code made this decision.

Every trade the agent records is graded later, but until now nothing said WHICH VERSION of the
agent produced it. On 2026-09-11 alone the code changed thirteen times - exit sizing, the ratchet,
position count, size, cadence, the autopilot fallback - and by the end of the day it was no longer
possible to attribute a result to any of them without reconstructing the timeline by hand.

Stamping the commit on each decision and each fill turns "which change actually helped" from an
argument into a query. It is the cheapest possible experiment log: the code is already versioned,
so all that was missing was writing the version down next to the outcome.

Resolved once per process and cached - a decision must never pay for a subprocess.
"""
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_CACHE: dict = {}

def code_version() -> str:
    """Short commit SHA, with a '+dirty' suffix when the tree has uncommitted changes.

    On GitHub Actions the SHA is handed to us in the environment, so no subprocess is needed at
    all. Locally it falls back to git, and to "unknown" if this is not a checkout - a missing
    version must never be a reason a trade fails to record.
    """
    if "v" in _CACHE:
        return _CACHE["v"]
    v = ""
    sha = os.getenv("GITHUB_SHA") or ""
    if sha:
        v = sha[:7]
    else:
        try:
            v = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
                               capture_output=True, text=True, timeout=5).stdout.strip()
        except Exception:
            v = ""
        if v:
            try:
                dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=no",
                                        "--", "agent", "config.yaml"],
                                       capture_output=True, text=True, timeout=5).stdout.strip()
                if dirty:
                    v += "+dirty"      # the running code is not what is committed; say so
            except Exception:
                pass
    _CACHE["v"] = v or "unknown"
    return _CACHE["v"]
