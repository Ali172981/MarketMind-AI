from pydantic import BaseModel


class Asset(BaseModel):
    symbol: str
    name: str
    market: str
    quote_currency: str
    data_status: str = "DEMO"


class PriceQuote(BaseModel):
    symbol: str
    price: float
    change_percent_24h: float
    source: str
    data_status: str
    timestamp: str
