"""
Тесты BotEngine — _on_price, _pre_flight_checks.

Все зависимости замоканы. API-ключи НЕ нужны.
"""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from storage.models import Trade, Entry
from config import Config


class TestOnPrice:
    """BotEngine._on_price() — обработка ценовых сигналов."""

    def _make_engine(self, mock_client, mock_notifier):
        """Создать мини-BotEngine с замоканными зависимостями."""
        # Вместо реального BotEngine создаём облегчённый объект
        # который содержит ту же логику _on_price
        from bot_engine import BotEngine

        with patch.object(BotEngine, '__init__', lambda self, cfg: None):
            engine = BotEngine.__new__(BotEngine)
            engine.config = Config()
            engine.client = mock_client
            engine.notifier = mock_notifier
            engine.strategy = MagicMock()
            engine.strategy.on_price_update = AsyncMock(return_value=None)
            engine.position_manager = MagicMock()
            engine.risk_manager = MagicMock()
            engine.risk_manager.max_entries = 5
            engine._running = True
            engine._session_trades = 0
            engine._session_pnl = 0.0
            # Периодическая сводка
            engine._period_trades_opened = 0
            engine._period_trades_closed = 0
            engine._period_winning_pnl = 0.0
            engine._period_losing_pnl = 0.0
            engine._period_errors = 0
            engine._period_error_types = []
            return engine

    def test_no_action(self, mock_client, mock_notifier):
        """Нет сигнала → нет уведомлений."""
        engine = self._make_engine(mock_client, mock_notifier)
        asyncio.run(engine._on_price(2000.0, {}))
        mock_notifier.notify_entry.assert_not_called()
        mock_notifier.notify_exit.assert_not_called()

    def test_not_running(self, mock_client, mock_notifier):
        """_running=False → ничего не делает."""
        engine = self._make_engine(mock_client, mock_notifier)
        engine._running = False
        asyncio.run(engine._on_price(2000.0, {}))
        engine.strategy.on_price_update.assert_not_called()

    def test_new_trade_notify_entry(self, mock_client, mock_notifier):
        """Новая открытая сделка → notify_entry."""
        engine = self._make_engine(mock_client, mock_notifier)
        new_trade = Trade(
            status="open",
            entries_count=1,
            avg_entry_price=2000.0,
            total_qty=0.20,
            symbol="ETHUSDT",
        )
        engine.strategy.on_price_update = AsyncMock(return_value=new_trade)
        asyncio.run(engine._on_price(2000.0, {}))
        assert engine._period_trades_opened == 1

    def test_closed_trade_notify_exit(self, mock_client, mock_notifier):
        """Закрытая сделка → notify_exit + инкремент session_trades."""
        engine = self._make_engine(mock_client, mock_notifier)
        closed_trade = Trade(
            status="closed",
            entries_count=2,
            avg_entry_price=1980.0,
            exit_price=2000.0,
            total_qty=0.40,
            pnl=32.0,
            commission=0.50,
            net_pnl=31.50,
            symbol="ETHUSDT",
        )
        from datetime import datetime
        closed_trade.opened_at = datetime(2026, 3, 10, 10, 0, 0)
        closed_trade.closed_at = datetime(2026, 3, 10, 12, 30, 0)
        engine.strategy.on_price_update = AsyncMock(return_value=closed_trade)
        asyncio.run(engine._on_price(2000.0, {}))
        assert engine._period_trades_closed == 1
        assert engine._session_trades == 1
        assert engine._session_pnl == 31.50
        assert engine._period_winning_pnl == 31.50

    def test_dca_entry_no_notify(self, mock_client, mock_notifier):
        """Усреднение (Entry) → НЕ уведомляет (сводка каждые 3 часа)."""
        engine = self._make_engine(mock_client, mock_notifier)
        # Настраиваем current_trade
        current_trade = Trade(
            entries_count=2,
            avg_entry_price=1980.0,
            total_qty=0.40,
            symbol="ETHUSDT",
        )
        engine.position_manager.current_trade = current_trade
        new_entry = Entry(
            entry_number=2,
            price=1960.0,
            qty=0.20,
        )
        engine.strategy.on_price_update = AsyncMock(return_value=new_entry)
        asyncio.run(engine._on_price(1960.0, {}))
        mock_notifier.notify_entry.assert_not_called()

    def test_max_entries_no_notify(self, mock_client, mock_notifier):
        """5/5 входов → НЕ уведомляет (сводка каждые 3 часа)."""
        engine = self._make_engine(mock_client, mock_notifier)
        current_trade = Trade(
            entries_count=5,
            avg_entry_price=1920.0,
            total_qty=1.00,
            symbol="ETHUSDT",
        )
        engine.position_manager.current_trade = current_trade
        engine.risk_manager.max_entries = 5
        new_entry = Entry(entry_number=5, price=1840.0, qty=0.20)
        engine.strategy.on_price_update = AsyncMock(return_value=new_entry)
        asyncio.run(engine._on_price(1840.0, {}))
        mock_notifier.notify_max_entries.assert_not_called()


class TestPreFlightChecks:
    """BotEngine._pre_flight_checks()."""

    def _make_engine(self, mock_client, mock_notifier):
        from bot_engine import BotEngine

        with patch.object(BotEngine, '__init__', lambda self, cfg: None):
            engine = BotEngine.__new__(BotEngine)
            engine.config = Config()
            engine.config.trading.symbol = "ETHUSDT"
            engine.config.trading.leverage = 4
            engine.config.trading.working_deposit = 1000.0
            engine.client = mock_client
            engine.notifier = mock_notifier
            return engine

    def test_all_checks_pass(self, mock_client, mock_notifier):
        """Все проверки ОК → True."""
        engine = self._make_engine(mock_client, mock_notifier)
        result = asyncio.run(engine._pre_flight_checks())
        assert result is True

    def test_no_trade_permission(self, mock_client, mock_notifier):
        """Нет торговых прав → False."""
        mock_client.check_api_permissions.return_value = {
            "can_trade": False,
            "has_withdraw": False,
        }
        engine = self._make_engine(mock_client, mock_notifier)
        result = asyncio.run(engine._pre_flight_checks())
        assert result is False

    def test_no_balance(self, mock_client, mock_notifier):
        """Не удалось получить баланс → False."""
        mock_client.get_wallet_balance.return_value = None
        engine = self._make_engine(mock_client, mock_notifier)
        result = asyncio.run(engine._pre_flight_checks())
        assert result is False

    def test_leverage_fail(self, mock_client, mock_notifier):
        """Не удалось установить плечо → False."""
        mock_client.set_leverage.return_value = False
        engine = self._make_engine(mock_client, mock_notifier)
        result = asyncio.run(engine._pre_flight_checks())
        assert result is False
