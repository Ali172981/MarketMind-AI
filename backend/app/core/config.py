from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "MarketMind AI"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"
    cors_origins: str = "http://localhost:3000"
    data_mode: str = "demo"  # demo | binance | alltick
    alltick_api_key: str = ""
    alltick_poll_seconds: int = 90
    alltick_ws_enabled: bool = False
    alltick_ws_subscription: str = "trade"  # trade | depth; AllTick allows one active subscription per connection
    alltick_ws_symbols: str = "BTCUSDT,XAUUSD,XAGUSD"
    alltick_ws_heartbeat_seconds: int = 10
    alltick_ws_stale_seconds: int = 45
    alltick_ws_reconnect_max_seconds: int = 60
    data_quality_enabled: bool = True
    tick_storage_enabled: bool = True
    tick_storage_min_interval_seconds: float = 1.0
    tick_storage_retention_days: int = 14
    data_quality_poll_seconds: int = 30
    data_quality_max_quote_age_seconds: int = 90
    paper_recorder_enabled: bool = False
    paper_recorder_symbols: str = "BTCUSDT,ETHUSDT,SOLUSDT"
    paper_recorder_intervals: str = "1h"
    paper_recorder_poll_seconds: int = 60
    paper_recorder_candle_limit: int = 500
    paper_exec_fee_bps_per_side: float = 10.0
    paper_exec_full_spread_bps: float = 4.0
    paper_exec_slippage_bps_per_side: float = 2.0
    paper_exec_entry_delay_bars: int = 0
    paper_exec_position_notional_quote: float = 1000.0
    paper_exec_entry_rejection_rate_pct: float = 0.0
    paper_exec_rejection_seed: str = "marketmind-paper-v1"
    paper_portfolio_initial_capital_quote: float = 10000.0
    paper_portfolio_risk_per_trade_pct: float = 1.0
    paper_portfolio_max_open_risk_pct: float = 3.0
    paper_portfolio_max_gross_exposure_pct: float = 100.0
    paper_portfolio_max_position_exposure_pct: float = 25.0
    paper_portfolio_max_concurrent_positions: int = 3
    api_access_key: str = ""
    write_rate_limit_per_minute: int = 30
    monitor_interval_seconds: int = 60
    alert_cooldown_seconds: int = 900
    news_enabled: bool = True
    news_poll_seconds: int = 300
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_to: str = ""
    smtp_starttls: bool = True

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
