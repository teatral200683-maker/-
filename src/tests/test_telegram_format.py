"""
Тесты TelegramNotifier — форматирование сообщений.

Мокаем _send(), проверяем текст. API-ключи НЕ нужны.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from notifications.telegram import TelegramNotifier


class TestTelegramEnabled:
    """Инициализация — _enabled флаг."""

    def test_enabled_with_credentials(self):
        n = TelegramNotifier("123456:ABC", "987654")
        assert n._enabled is True

    def test_disabled_empty_token(self):
        n = TelegramNotifier("", "987654")
        assert n._enabled is False

    def test_disabled_empty_chat_id(self):
        n = TelegramNotifier("123456:ABC", "")
        assert n._enabled is False

    def test_disabled_both_empty(self):
        n = TelegramNotifier("", "")
        assert n._enabled is False


class TestTelegramFormatting:
    """Форматирование шаблонов уведомлений."""

    @pytest.fixture
    def notifier(self):
        n = TelegramNotifier("test-token", "test-chat")
        n._send = AsyncMock()
        return n

    def test_notify_bot_started_format(self, notifier):
        asyncio.run(notifier.notify_bot_started(
            balance=1000.0, symbol="ETHUSDT", leverage=4,
            tp_pct=1.0, testnet=True,
        ))
        notifier._send.assert_called_once()
        text = notifier._send.call_args[0][0]
        assert "ЗАПУЩЕН" in text
        assert "TESTNET" in text
        assert "ETHUSDT" in text
        assert "1,000.00" in text
        assert "4x" in text

    def test_notify_entry_format(self, notifier):
        asyncio.run(notifier.notify_entry(
            entry_num=2, max_entries=5, symbol="ETHUSDT",
            price=1960.0, qty=0.20, avg_price=1980.0,
            tp_price=1999.80, total_value=396.0,
        ))
        text = notifier._send.call_args[0][0]
        assert "ВХОД" in text
        assert "2/5" in text
        assert "1,960.00" in text

    def test_notify_exit_format(self, notifier):
        asyncio.run(notifier.notify_exit(
            symbol="ETHUSDT", exit_price=2020.0, entries=3,
            pnl=16.0, commission=0.24, net_pnl=15.76,
            balance=1015.76, duration="2ч 30мин",
        ))
        text = notifier._send.call_args[0][0]
        assert "ЗАКРЫТА" in text
        assert "+15.76" in text
        assert "2ч 30мин" in text

    def test_notify_error_format(self, notifier):
        asyncio.run(notifier.notify_error(
            error_type="WebSocket", message="Connection lost", attempt=3,
        ))
        text = notifier._send.call_args[0][0]
        assert "ОШИБКА" in text
        assert "WebSocket" in text
        assert "Connection lost" in text

    def test_notify_daily_summary_format(self, notifier):
        asyncio.run(notifier.notify_daily_summary(
            date_str="10.03.2026", trades_closed=5,
            total_pnl=42.50, commission=1.20, net_pnl=41.30,
            open_entries=2, max_entries=5, balance=1041.30,
            monthly_pnl=120.0, total_trades=25,
        ))
        text = notifier._send.call_args[0][0]
        assert "СВОДКА" in text
        assert "10.03.2026" in text
        assert "25" in text

    def test_notify_max_entries_format(self, notifier):
        asyncio.run(notifier.notify_max_entries(
            symbol="ETHUSDT", entries=5, max_entries=5,
            avg_price=1960.0, tp_price=1979.60, total_value=980.0,
        ))
        text = notifier._send.call_args[0][0]
        assert "МАКСИМУМ" in text
        assert "5/5" in text

    def test_notify_bot_stopped_format(self, notifier):
        asyncio.run(notifier.notify_bot_stopped(
            reason="Ручная остановка", balance=1050.0,
            session_trades=10, session_pnl=50.0, uptime="12ч 30мин",
        ))
        text = notifier._send.call_args[0][0]
        assert "ОСТАНОВЛЕН" in text
        assert "Ручная остановка" in text
        assert "12ч 30мин" in text
