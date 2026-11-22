from datetime import datetime, timezone
from app.schemas.market import Asset, PriceQuote
from app.market_data.binance_provider import get_live_quotes
from app.core.config import settings

ASSETS = [
    Asset(symbol="BTCUSDT", name="Bitcoin", market="crypto", quote_currency="USDT"),
    Asset(symbol="ETHUSDT", name="Ethereum", market="crypto", quote_currency="USDT"),
    Asset(symbol="SOLUSDT", name="Solana", market="crypto", quote_currency="USDT"),
    Asset(symbol="XAUUSD", name="Gold Spot", market="metals", quote_currency="USD"),
    Asset(symbol="XAGUSD", name="Silver Spot", market="metals", quote_currency="USD"),
]

DEMO_QUOTES = [
    PriceQuote(symbol="BTCUSDT", price=65000.00, change_percent_24h=1.25, source="demo-fixture", data_status="DEMO", timestamp=""),
    PriceQuote(symbol="ETHUSDT", price=3200.00, change_percent_24h=-0.45, source="demo-fixture", data_status="DEMO", timestamp=""),
    PriceQuote(symbol="SOLUSDT", price=145.00, change_percent_24h=2.10, source="demo-fixture", data_status="DEMO", timestamp=""),
    PriceQuote(symbol="XAUUSD", price=2350.00, change_percent_24h=0.32, source="demo-fixture", data_status="DEMO", timestamp=""),
    PriceQuote(symbol="XAGUSD", price=29.50, change_percent_24h=-0.18, source="demo-fixture", data_status="DEMO", timestamp=""),
]


def get_assets():
    return ASSETS


def get_quotes():
    now = datetime.now(timezone.utc).isoformat()
    if settings.data_mode.lower() == "binance":
        live = get_live_quotes()
        live_by_symbol = {q["symbol"]: q for q in live}
        result = []
        for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
            if symbol in live_by_symbol:
                result.append(PriceQuote(**live_by_symbol[symbol]))
            else:
                result.append(PriceQuote(symbol=symbol, price=0, change_percent_24h=0, source="Binance Spot WebSocket", data_status="CONNECTING", timestamp=now))
        # Binance Spot does not provide XAUUSD/XAGUSD spot-metal prices.
        for symbol in ("XAUUSD", "XAGUSD"):
            result.append(PriceQuote(symbol=symbol, price=0, change_percent_24h=0, source="No metals provider configured", data_status="UNAVAILABLE", timestamp=now))
        return result
    return [quote.model_copy(update={"timestamp": now}) for quote in DEMO_QUOTES]
