"""
Тесты Database — CRUD, статистика, состояние бота.

Используется in-memory SQLite — API-ключи НЕ нужны.
"""

import pytest
from datetime import datetime

from storage.models import Trade, Entry, DailyStats


class TestDatabaseTrades:
    """Тесты CRUD для таблицы trades."""

    def test_create_tables(self, tmp_db):
        """Таблицы создаются при инициализации."""
        cursor = tmp_db.conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row["name"] for row in cursor.fetchall()}
        assert "trades" in tables
        assert "entries" in tables
        assert "daily_stats" in tables
        assert "bot_state" in tables

    def test_create_trade(self, tmp_db, sample_trade):
        """CREATE: trade получает ID."""
        trade_id = tmp_db.create_trade(sample_trade)
        assert trade_id == 1
        assert isinstance(trade_id, int)

    def test_get_trade_by_id(self, tmp_db, sample_trade):
        """READ: получение сделки по ID."""
        trade_id = tmp_db.create_trade(sample_trade)
        loaded = tmp_db.get_trade_by_id(trade_id)
        assert loaded is not None
        assert loaded.symbol == "ETHUSDT"
        assert loaded.avg_entry_price == 2000.0
        assert loaded.leverage == 4

    def test_get_trade_by_id_not_found(self, tmp_db):
        """READ: несуществующий ID → None."""
        loaded = tmp_db.get_trade_by_id(999)
        assert loaded is None

    def test_get_open_trade(self, tmp_db, sample_trade):
        """READ: получение открытой сделки."""
        tmp_db.create_trade(sample_trade)
        open_trade = tmp_db.get_open_trade()
        assert open_trade is not None
        assert open_trade.status == "open"

    def test_get_open_trade_none(self, tmp_db):
        """READ: нет открытых → None."""
        result = tmp_db.get_open_trade()
        assert result is None

    def test_update_trade(self, tmp_db, sample_trade):
        """UPDATE: обновление полей сделки."""
        trade_id = tmp_db.create_trade(sample_trade)
        sample_trade.id = trade_id
        sample_trade.status = "closed"
        sample_trade.exit_price = 2020.0
        sample_trade.closed_at = datetime(2026, 3, 10, 14, 0, 0)
        sample_trade.pnl = 16.0
        sample_trade.commission = 0.24
        sample_trade.net_pnl = 15.76

        tmp_db.update_trade(sample_trade)

        loaded = tmp_db.get_trade_by_id(trade_id)
        assert loaded.status == "closed"
        assert loaded.exit_price == 2020.0
        assert loaded.net_pnl == 15.76

    def test_get_closed_trades(self, tmp_db):
        """READ: список закрытых сделок."""
        # Создаём 2 закрытые и 1 открытую
        for i, status in enumerate(["closed", "closed", "open"]):
            trade = Trade(
                opened_at=datetime(2026, 3, 10, i, 0, 0),
                avg_entry_price=2000.0 + i * 10,
                total_qty=0.20,
                status=status,
            )
            tid = tmp_db.create_trade(trade)
            if status == "closed":
                trade.id = tid
                trade.closed_at = datetime(2026, 3, 10, i + 1, 0, 0)
                trade.exit_price = 2020.0
                trade.net_pnl = 10.0
                tmp_db.update_trade(trade)

        closed = tmp_db.get_closed_trades()
        assert len(closed) == 2
        for t in closed:
            assert t.status == "closed"


class TestDatabaseEntries:
    """Тесты CRUD для таблицы entries."""

    def test_create_entry(self, tmp_db, sample_trade, sample_entry):
        """CREATE: запись входа."""
        trade_id = tmp_db.create_trade(sample_trade)
        sample_entry.trade_id = trade_id
        entry_id = tmp_db.create_entry(sample_entry)
        assert entry_id == 1

    def test_get_entries(self, tmp_db, sample_trade):
        """READ: все входы для сделки."""
        trade_id = tmp_db.create_trade(sample_trade)

        for i in range(3):
            entry = Entry(
                trade_id=trade_id,
                entry_number=i + 1,
                price=2000.0 - i * 40,
                qty=0.20,
                order_id=f"order-{i}",
            )
            tmp_db.create_entry(entry)

        entries = tmp_db.get_entries(trade_id)
        assert len(entries) == 3
        assert entries[0].entry_number == 1
        assert entries[2].entry_number == 3


class TestDatabaseStats:
    """Тесты статистики и состояния."""

    def test_save_daily_stats(self, tmp_db):
        """INSERT OR REPLACE для дневной статистики."""
        stats = DailyStats(
            date="2026-03-10",
            trades_closed=5,
            total_pnl=42.50,
            total_commission=1.20,
            balance=1042.50,
        )
        tmp_db.save_daily_stats(stats)

        loaded = tmp_db.get_daily_stats(days=1)
        assert len(loaded) == 1
        assert loaded[0].trades_closed == 5
        assert loaded[0].total_pnl == 42.50

    def test_get_total_stats_empty(self, tmp_db):
        """Пустая БД → нулевая статистика."""
        stats = tmp_db.get_total_stats()
        assert stats["total_trades"] == 0
        assert stats["win_rate"] == 0
        assert stats["total_profit"] == 0

    def test_get_total_stats_with_data(self, tmp_db):
        """Агрегация по закрытым сделкам."""
        for pnl in [10.0, -5.0, 15.0]:
            trade = Trade(
                opened_at=datetime(2026, 3, 10, 0, 0, 0),
                avg_entry_price=2000.0,
                total_qty=0.20,
                status="closed",
            )
            tid = tmp_db.create_trade(trade)
            trade.id = tid
            trade.closed_at = datetime(2026, 3, 10, 1, 0, 0)
            trade.exit_price = 2010.0
            trade.net_pnl = pnl
            tmp_db.update_trade(trade)

        stats = tmp_db.get_total_stats()
        assert stats["total_trades"] == 3
        assert stats["winning_trades"] == 2
        assert abs(stats["win_rate"] - 66.67) < 0.1
        assert stats["total_profit"] == 20.0

    def test_save_get_state(self, tmp_db):
        """Key-value хранилище состояния."""
        tmp_db.save_state("last_price", "2050.50")
        value = tmp_db.get_state("last_price")
        assert value == "2050.50"

    def test_get_state_not_found(self, tmp_db):
        """Несуществующий ключ → None."""
        value = tmp_db.get_state("nonexistent")
        assert value is None
