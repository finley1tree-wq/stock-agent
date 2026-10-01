"""python -m agent.crypto [--decide]   one hourly pass: mark the book, decide once per UTC day."""
import sys

from .engine import run

if __name__ == "__main__":
    b = run(force_decide="--decide" in sys.argv)
    held = ", ".join(f"{c} {h['strategy']} ${h.get('value_usd', 0):,.0f}" for c, h in b["holdings"].items()) or "nothing"
    print(f"crypto book ${b['equity']:,.2f} (cash ${b['cash']:,.2f}) holding: {held}")
