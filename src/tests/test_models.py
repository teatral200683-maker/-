"""
Тесты Models — Trade, Entry, расчёты PnL, TP, усреднение.

Чистая логика, API-ключи НЕ нужны.
"""

import pytest
from datetime import datetime

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from storage.models import Trade, Entry, DailyStats


class TestTradeDefaults:
    """Дефолтные значения Trade."""

    def test_defaults(self):
        t = Trade()
        assert t.id is None
        assert t.symbol == "ETHUSDT"
        assert t.side == "Buy"
        assert t.status == "open"
        assert t.entries_count == 0
        assert t.leverage == 4
        assert t.entries == []


class TestTradeAddEntry:
    """Trade.add_entry() — усреднение."""

    def test_single_entry(self):
        t = Trade()
        entry = t.add_entry(price=2000.0, qty=0.20)
        assert t.entries_count == 1
        assert t.total_qty == 0.20
        assert t.avg_entry_price == 2000.0
        assert entry.entry_number == 1

    def test_two_entries_avg_price(self):
        """Средневзвешенная: (2000*0.20 + 1960*0.20) / 0.40 = 1980."""
        t = Trade()
        t.add_entry(price=2000.0, qty=0.20)
        t.add_entry(price=1960.0, qty=0.20)
        assert t.entries_count == 2
        assert t.total_qty == pytest.approx(0.40)
        assert t.avg_entry_price == pytest.approx(1980.0)

    def test_three_entries_different_qty(self):
        """Средневзвешенная с разными объёмами."""
        t = Trade()
        t.add_entry(price=2000.0, qty=0.10)   # 200
        t.add_entry(price=1900.0, qty=0.20)   # 380
        t.add_entry(price=1800.0, qty=0.10)   # 180
        # total_cost = 760, total_qty = 0.40 → avg = 1900.0
        assert t.total_qty == pytest.approx(0.40)
        assert t.avg_entry_price == pytest.approx(1900.0)

    def test_entry_numbers_sequential(self):
        t = Trade()
        e1 = t.add_entry(price=2000.0, qty=0.10)
        e2 = t.add_entry(price=1960.0, qty=0.10)
        e3 = t.add_entry(price=1920.0, qty=0.10)
        assert e1.entry_number == 1
        assert e2.entry_number == 2
        assert e3.entry_number == 3


class TestTradeTakeProfit:
    """Trade.calculate_take_profit_price()."""

    def test_tp_1_percent(self):
        t = Trade()
        t.add_entry(price=2000.0, qty=0.20)
        tp = t.calculate_take_profit_price(tp_pct=1.0)
        assert tp == pytest.approx(2020.0)

    def test_tp_custom_percent(self):
        t = Trade()
        t.add_entry(price=1000.0, qty=0.50)
        tp = t.calculate_take_profit_price(tp_pct=2.5)
        assert tp == pytest.approx(1025.0)


class TestTradeClose:
    """Trade.close() — расчёт PnL."""

    def test_close_profitable(self):
        t = Trade()
        t.add_entry(price=2000.0, qty=0.20)
        t.close(exit_price=2020.0, commission=0.24)

        assert t.status == "closed"
        assert t.exit_price == 2020.0
        assert t.closed_at is not None
        # PnL = (2020 - 2000) * 0.20 * 4 = 16.0
        assert t.pnl == pytest.approx(16.0)
        # net = 16.0 - 0.24 = 15.76
        assert t.net_pnl == pytest.approx(15.76)

    def test_close_at_loss(self):
        t = Trade()
        t.add_entry(price=2000.0, qty=0.20)
        t.close(exit_price=1950.0, commission=0.20)

        # PnL = (1950 - 2000) * 0.20 * 4 = -40.0
        assert t.pnl == pytest.approx(-40.0)
        assert t.net_pnl == pytest.approx(-40.20)

    def test_close_with_dca(self):
        """Закрытие после усреднения."""
        t = Trade()
        t.add_entry(price=2000.0, qty=0.20)
        t.add_entry(price=1960.0, qty=0.20)
        # avg = 1980, qty = 0.40
        t.close(exit_price=2000.0, commission=0.50)

        # PnL = (2000 - 1980) * 0.40 * 4 = 32.0
        assert t.pnl == pytest.approx(32.0)
        assert t.net_pnl == pytest.approx(31.50)


class TestEntryDefaults:
    """Дефолтные значения Entry."""

    def test_defaults(self):
        e = Entry()
        assert e.id is None
        assert e.entry_number == 1
        assert e.price == 0.0
        assert e.qty == 0.0
        assert e.order_id == ""


class TestDailyStatsDefaults:
    """Дефолтные значения DailyStats."""

    def test_defaults(self):
        ds = DailyStats()
        assert ds.trades_closed == 0
        assert ds.total_pnl == 0.0
        assert ds.balance == 0.0
