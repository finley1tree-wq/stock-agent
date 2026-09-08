"""Interactive Brokers adapter — the Canadian path to real money.

Needs IB Gateway or Trader Workstation running on the same machine with API access
enabled (Configure → API → Settings → Enable ActiveX and Socket Clients; paper port 4002,
live port 4001). Same interface as broker.Broker so run.py doesn't care which one it has.
Fractional shares: enable in Account Settings → Trading Permissions → US Stock Fractional Shares.
"""
from ib_async import IB, Stock, MarketOrder

class IBKRBroker:
    def __init__(self, env: dict):
        self.dry = env["dry_run"]
        self.ib = IB()
        port = int(env.get("ibkr_port") or (4002 if env.get("ibkr_paper", True) else 4001))
        self.ib.connect(env.get("ibkr_host") or "127.0.0.1", port, clientId=int(env.get("ibkr_client_id") or 7), timeout=20)

    def market_open(self) -> bool:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("America/New_York"))
        return now.weekday() < 5 and (9, 30) <= (now.hour, now.minute) < (16, 0)

    def positions(self) -> dict:
        out = {}
        for p in self.ib.portfolio():
            out[p.contract.symbol] = {"qty": float(p.position), "market_value": round(float(p.marketValue), 2),
                                      "unrealized_plpc": round(float(p.unrealizedPNL) / max(abs(float(p.marketValue) - float(p.unrealizedPNL)), 1e-9) * 100, 2)}
        return out

    def cash(self) -> float | None:
        for v in self.ib.accountValues():
            if v.tag == "TotalCashValue" and v.currency == "USD":
                return float(v.value)
        return None

    def buy_notional(self, symbol: str, usd: float) -> dict:
        rec = {"symbol": symbol, "notional": round(usd, 2), "side": "buy"}
        if self.dry:
            rec["status"] = "dry_run"; return rec
        contract = Stock(symbol, "SMART", "USD")
        self.ib.qualifyContracts(contract)
        order = MarketOrder("BUY", 0)
        order.cashQty = round(usd, 2)          # dollar-amount (fractional) order
        trade = self.ib.placeOrder(contract, order)
        self.ib.sleep(2)
        rec.update({"status": trade.orderStatus.status, "order_id": str(trade.order.orderId)})
        return rec
