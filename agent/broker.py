"""Alpaca broker wrapper. Paper by default. DRY_RUN never sends orders."""
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

class Broker:
    name = "alpaca"

    def __init__(self, env: dict):
        self.dry = env["dry_run"]
        self.client = None
        if env["alpaca_key"] and env["alpaca_secret"]:
            self.client = TradingClient(env["alpaca_key"], env["alpaca_secret"], paper=env["alpaca_paper"])

    def market_open(self) -> bool:
        if not self.client:
            return True
        return bool(self.client.get_clock().is_open)

    def positions(self) -> dict:
        if not self.client:
            return {}
        return {p.symbol: {"qty": float(p.qty), "avg_cost": float(p.avg_entry_price), "market_value": float(p.market_value),
                           "unrealized_plpc": round(float(p.unrealized_plpc) * 100, 2)}
                for p in self.client.get_all_positions()}

    def held_tickers(self) -> list[str]:
        return sorted(self.positions())

    def cash(self) -> float | None:
        if not self.client:
            return None
        return float(self.client.get_account().cash)

    def buy_notional(self, symbol: str, usd: float) -> dict:
        """Buy $usd of symbol (fractional). Returns an order record."""
        rec = {"symbol": symbol, "notional": round(usd, 2), "side": "buy"}
        if self.dry or not self.client:
            rec["status"] = "dry_run"
            return rec
        req = MarketOrderRequest(symbol=symbol, notional=round(usd, 2), side=OrderSide.BUY, time_in_force=TimeInForce.DAY)
        order = self.client.submit_order(order_data=req)
        rec.update({"status": str(order.status), "order_id": str(order.id)})
        return rec

    def sell_qty(self, symbol: str, qty: float) -> dict:
        """Sell qty shares of symbol at market. Returns an order record."""
        rec = {"symbol": symbol, "qty": round(qty, 6), "side": "sell"}
        if self.dry or not self.client:
            rec["status"] = "dry_run"
            return rec
        req = MarketOrderRequest(symbol=symbol, qty=round(qty, 6), side=OrderSide.SELL, time_in_force=TimeInForce.DAY)
        order = self.client.submit_order(order_data=req)
        rec.update({"status": str(order.status), "order_id": str(order.id)})
        return rec
