import os
from pathlib import Path
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

def load_config() -> dict:
    with open(ROOT / "config.yaml") as f:
        cfg = yaml.safe_load(f)
    cfg["env"] = {
        "alpaca_key": os.getenv("ALPACA_API_KEY", ""),
        "alpaca_secret": os.getenv("ALPACA_SECRET_KEY", ""),
        "alpaca_paper": os.getenv("ALPACA_PAPER", "true").lower() != "false",
        "anthropic_key": os.getenv("ANTHROPIC_API_KEY", ""),
        "anthropic_model": os.getenv("ANTHROPIC_MODEL") or "claude-sonnet-5",
        "effort": (os.getenv("ANTHROPIC_EFFORT") or "medium").lower(),   # low | medium | high — thinking depth per check
        "quiver_key": os.getenv("QUIVER_API_KEY", ""),
        "fmp_key": os.getenv("FMP_API_KEY", ""),
        "dry_run": os.getenv("DRY_RUN", "true").lower() != "false",
        "broker": (os.getenv("BROKER") or "sim").lower(),   # sim = built-in pretend money (default)
        "ibkr_host": os.getenv("IBKR_HOST", "127.0.0.1"),
        "ibkr_port": os.getenv("IBKR_PORT", ""),
        "ibkr_paper": os.getenv("IBKR_PAPER", "true").lower() != "false",
        "ibkr_client_id": os.getenv("IBKR_CLIENT_ID") or "7",
    }
    cfg.setdefault("sim", {"starting_cash": 400, "weekly_deposit": 400})
    return cfg

def all_watchlist_tickers(cfg: dict) -> list[str]:
    out = []
    for group in cfg["watchlist"].values():
        out.extend(group)
    return sorted(set(out))
