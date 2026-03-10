"""
Общие фикстуры для тестов — Crypto Trader Bot
"""

import sys
import os
import pytest
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock

# Добавляем src/ в путь для импорта модулей
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from storage.models import Trade, Entry, DailyStats
from storage.database import Database


@pytest.fixture
def tmp_db(tmp_path):
    """In-memory SQLite база данных для тестов."""
    db = Database(db_path=":memory:")
    yield db
    db.close()


@pytest.fixture
def sample_trade():
    """Готовый объект Trade для тестов."""
    return Trade(
        opened_at=datetime(2026, 3, 10, 12, 0, 0),
        symbol="ETHUSDT",
        side="Buy",
        status="open",
        entries_count=1,
        avg_entry_price=2000.0,
        total_qty=0.20,
        leverage=4,
    )


@pytest.fixture
def sample_entry():
    """Готовый объект Entry для тестов."""
    return Entry(
        trade_id=1,
        entry_number=1,
        timestamp=datetime(2026, 3, 10, 12, 0, 0),
        price=2000.0,
        qty=0.20,
        order_id="test-order-001",
    )


@pytest.fixture
def mock_client():
    """Замоканный BybitClient."""
    client = MagicMock()
    client.get_wallet_balance.return_value = {
        "totalEquity": 1000.0,
        "totalAvailableBalance": 950.0,
        "coins": [],
    }
    client.check_api_permissions.return_value = {
        "can_trade": True,
        "has_withdraw": False,
        "is_safe": True,
    }
    client.set_leverage.return_value = True
    client.get_ticker.return_value = 2000.0
    client.place_order.return_value = "order-123"
    client.get_execution_details.return_value = {
        "avg_price": 2000.0,
        "commission": 0.12,
        "qty": 0.20,
    }
    return client


@pytest.fixture
def mock_notifier():
    """Замоканный TelegramNotifier."""
    notifier = MagicMock()
    notifier._enabled = True
    notifier.notify_bot_started = AsyncMock()
    notifier.notify_entry = AsyncMock()
    notifier.notify_exit = AsyncMock()
    notifier.notify_error = AsyncMock()
    notifier.notify_max_entries = AsyncMock()
    notifier.notify_daily_summary = AsyncMock()
    notifier.notify_bot_stopped = AsyncMock()
    return notifier
