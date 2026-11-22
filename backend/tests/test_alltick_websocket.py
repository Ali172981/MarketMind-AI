import json

from app.market_data import alltick_websocket as ws


def setup_function():
    ws._quotes.clear()
    ws._orderbooks.clear()
    ws._last_seq.clear()
    ws._state.update({
        "status": "DISABLED", "connected": False, "connected_at": None,
        "last_message_at": None, "last_tick_at": None, "last_error": None,
        "reconnect_count": 0, "messages_received": 0, "invalid_messages": 0,
        "out_of_order_messages": 0, "subscription": "trade", "symbols": [],
        "subscription_acknowledged": False, "subscription_ack_at": None,
        "stale_after_seconds": 45,
    })


def test_trade_subscription_uses_documented_protocol_and_symbol_codes():
    payload = ws._build_subscription(["BTCUSDT", "XAUUSD", "XAGUSD"], "trade", 123)
    assert payload["cmd_id"] == 22004
    assert payload["seq_id"] == 123
    assert payload["data"]["symbol_list"] == [
        {"code": "BTCUSDT"}, {"code": "GOLD"}, {"code": "Silver"}
    ]


def test_depth_subscription_uses_documented_protocol():
    payload = ws._build_subscription(["BTCUSDT", "XAUUSD"], "depth", 9)
    assert payload["cmd_id"] == 22002
    assert payload["data"]["symbol_list"] == [
        {"code": "BTCUSDT", "depth_level": 5},
        {"code": "GOLD", "depth_level": 1},
    ]


def test_normalizes_trade_tick_with_millisecond_timestamp():
    item = ws.process_message(json.dumps({
        "cmd_id": 22998,
        "data": {"code": "BTCUSDT", "seq": 10, "tick_time": 1795255200000,
                 "price": "90000.5", "volume": "0.2", "turnover": "18000.1", "trade_direction": 1},
    }))
    assert item["symbol"] == "BTCUSDT"
    assert item["price"] == 90000.5
    assert item["timestamp"].startswith("2026-")
    assert item["trade_direction"] == 1
    assert ws.get_quotes()[0]["source"] == "AllTick WebSocket trade tick"


def test_normalizes_legacy_seconds_timestamp():
    item = ws.process_message(json.dumps({
        "cmd_id": 22998, "data": {"code": "GOLD", "tick_time": 1795255200, "price": "4100"}
    }))
    assert item["symbol"] == "XAUUSD"
    assert item["timestamp"].startswith("2026-")


def test_rejects_out_of_order_trade_sequence():
    base = {"cmd_id": 22998, "data": {"code": "BTCUSDT", "tick_time": 1795255200000, "price": "1"}}
    first = dict(base, data=dict(base["data"], seq=2))
    second = dict(base, data=dict(base["data"], seq=1))
    assert ws.process_message(json.dumps(first)) is not None
    assert ws.process_message(json.dumps(second)) is None
    assert ws._state["out_of_order_messages"] == 1


def test_normalizes_orderbook_and_spread():
    item = ws.process_message(json.dumps({
        "cmd_id": 22999,
        "data": {"code": "Silver", "tick_time": 1795255200,
                 "bids": [{"price": "50", "volume": "10"}],
                 "asks": [{"price": "50.1", "volume": "8"}]},
    }))
    assert item["symbol"] == "XAGUSD"
    assert item["best_bid"] == 50
    assert item["best_ask"] == 50.1
    assert round(item["spread_bps"], 4) == round(0.1 / 50.05 * 10000, 4)


def test_provider_error_is_counted_and_not_exposed_as_quote():
    assert ws.process_message(json.dumps({"ret": 401, "msg": "bad token", "data": {}})) is None
    assert ws._state["invalid_messages"] == 1
    assert "401" in ws._state["last_error"]


def test_malformed_payload_is_safe():
    assert ws.process_message("not-json") is None
    assert ws._state["invalid_messages"] == 1


def test_status_discloses_disabled_stream(monkeypatch):
    monkeypatch.setattr(ws.settings, "alltick_ws_enabled", False)
    assert ws.get_status()["status"] == "DISABLED"


def test_subscription_acknowledgement_is_recorded():
    assert ws.process_message(json.dumps({"ret": 200, "cmd_id": 22005, "data": {}})) is None
    assert ws._state["subscription_acknowledged"] is True
    assert ws._state["subscription_ack_at"] is not None
