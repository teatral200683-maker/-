"""
Тесты BybitClient — retry-логика, защита от шорта, обработка ошибок.

Мокаем self.session (pybit HTTP). API-ключи НЕ нужны.
"""

import pytest
import time
from unittest.mock import MagicMock, patch

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestPlaceOrder:
    """BybitClient.place_order() — ордера, retry, защита."""

    def _make_client(self):
        """Создать BybitClient с замоканной сессией."""
        from exchange.client import BybitClient

        with patch.object(BybitClient, '__init__', lambda self, *a, **kw: None):
            client = BybitClient.__new__(BybitClient)
            client.testnet = True
            client.session = MagicMock()
            return client

    def test_success(self):
        """retCode=0 → возвращает orderId."""
        client = self._make_client()
        client.session.place_order.return_value = {
            "retCode": 0,
            "result": {"orderId": "order-abc-123"},
        }
        result = client.place_order("ETHUSDT", "Buy", "0.20")
        assert result == "order-abc-123"

    def test_short_blocked(self):
        """side='Sell' без reduce_only → ValueError."""
        client = self._make_client()
        with pytest.raises(ValueError, match="[Шш]орт"):
            client.place_order("ETHUSDT", "Sell", "0.20", reduce_only=False)

    def test_sell_reduce_only_ok(self):
        """side='Sell' с reduce_only=True → ОК (закрытие позиции)."""
        client = self._make_client()
        client.session.place_order.return_value = {
            "retCode": 0,
            "result": {"orderId": "close-order-456"},
        }
        result = client.place_order("ETHUSDT", "Sell", "0.20", reduce_only=True)
        assert result == "close-order-456"

    def test_retry_30208_then_success(self):
        """2 ошибки 30208, затем успех → orderId."""
        client = self._make_client()

        call_count = 0

        def side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise Exception("30208 maxTradePrice error")
            return {
                "retCode": 0,
                "result": {"orderId": "retry-order-789"},
            }

        client.session.place_order.side_effect = side_effect

        with patch("time.sleep"):  # Не ждём реальную секунду
            result = client.place_order("ETHUSDT", "Buy", "0.20")

        assert result == "retry-order-789"
        assert call_count == 3

    def test_retry_30208_exhausted(self):
        """3 ошибки 30208 подряд → None."""
        client = self._make_client()
        client.session.place_order.side_effect = Exception("30208 maxTradePrice")

        with patch("time.sleep"):
            result = client.place_order("ETHUSDT", "Buy", "0.20")

        assert result is None

    def test_api_error_returns_none(self):
        """retCode != 0 → None."""
        client = self._make_client()
        client.session.place_order.return_value = {
            "retCode": 10001,
            "retMsg": "Invalid parameter",
        }
        result = client.place_order("ETHUSDT", "Buy", "0.20")
        assert result is None


class TestSetLeverage:
    """BybitClient.set_leverage()."""

    def _make_client(self):
        from exchange.client import BybitClient

        with patch.object(BybitClient, '__init__', lambda self, *a, **kw: None):
            client = BybitClient.__new__(BybitClient)
            client.testnet = True
            client.session = MagicMock()
            return client

    def test_success(self):
        """retCode=0 → True."""
        client = self._make_client()
        client.session.set_leverage.return_value = {"retCode": 0}
        assert client.set_leverage("ETHUSDT", 4) is True

    def test_already_set_110043(self):
        """retCode=110043 (уже установлено) → True."""
        client = self._make_client()
        client.session.set_leverage.return_value = {"retCode": 110043}
        assert client.set_leverage("ETHUSDT", 4) is True

    def test_already_set_exception(self):
        """pybit v5.8+ бросает исключение с 110043 → True."""
        client = self._make_client()
        client.session.set_leverage.side_effect = Exception("110043 leverage not modified")
        assert client.set_leverage("ETHUSDT", 4) is True

    def test_failure(self):
        """Другая ошибка → False."""
        client = self._make_client()
        client.session.set_leverage.side_effect = Exception("Network error")
        assert client.set_leverage("ETHUSDT", 4) is False


class TestGetWalletBalance:
    """BybitClient.get_wallet_balance()."""

    def _make_client(self):
        from exchange.client import BybitClient

        with patch.object(BybitClient, '__init__', lambda self, *a, **kw: None):
            client = BybitClient.__new__(BybitClient)
            client.testnet = True
            client.session = MagicMock()
            return client

    def test_success(self):
        """retCode=0 → dict с балансом."""
        client = self._make_client()
        client.session.get_wallet_balance.return_value = {
            "retCode": 0,
            "result": {
                "list": [{
                    "totalEquity": "1234.56",
                    "totalAvailableBalance": "1200.00",
                    "coin": [],
                }]
            },
        }
        result = client.get_wallet_balance()
        assert result["totalEquity"] == 1234.56
        assert result["totalAvailableBalance"] == 1200.00

    def test_error_returns_empty(self):
        """Exception → пустой dict."""
        client = self._make_client()
        client.session.get_wallet_balance.side_effect = Exception("Timeout")
        result = client.get_wallet_balance()
        assert result == {}

    def test_api_error_returns_empty(self):
        """retCode != 0 → пустой dict."""
        client = self._make_client()
        client.session.get_wallet_balance.return_value = {
            "retCode": 10002,
            "retMsg": "Invalid timestamp",
        }
        result = client.get_wallet_balance()
        assert result == {}
