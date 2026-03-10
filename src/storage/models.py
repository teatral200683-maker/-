"""
Модели данных — Crypto Trader Bot

Dataclass-модели для сделок, входов и статистики.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, List


@dataclass
class Entry:
    """Один вход в позицию (усреднение)."""
    id: Optional[int] = None
    trade_id: Optional[int] = None
    entry_number: int = 1                       # 1–5
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    price: float = 0.0                          # Цена входа
    qty: float = 0.0                            # Объём в монетах
    order_id: str = ""                          # ID ордера на бирже


@dataclass
class Trade:
    """Один полный торговый цикл (от первого входа до закрытия)."""
    id: Optional[int] = None
    opened_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    closed_at: Optional[datetime] = None
    symbol: str = "ETHUSDT"
    side: str = "Buy"
    status: str = "open"                        # open / closed
    entries_count: int = 0
    avg_entry_price: float = 0.0                # Средняя цена входа
    exit_price: Optional[float] = None
    total_qty: float = 0.0                      # Общий объём позиции
    leverage: int = 4
    pnl: Optional[float] = None                 # Прибыль/убыток
    commission: float = 0.0
    net_pnl: Optional[float] = None             # Чистый PnL
    entries: List[Entry] = field(default_factory=list)

    def add_entry(self, price: float, qty: float, order_id: str = "") -> Entry:
        """
        Добавить вход (усреднение). Пересчитывает среднюю цену.

        Args:
            price: Цена входа
            qty: Объём в монетах
            order_id: ID ордера на бирже

        Returns:
            Созданный объект Entry
        """
        self.entries_count += 1
        entry = Entry(
            trade_id=self.id,
            entry_number=self.entries_count,
            price=price,
            qty=qty,
            order_id=order_id,
        )
        self.entries.append(entry)

        # Пересчёт средней цены (средневзвешенная)
        total_cost = sum(e.price * e.qty for e in self.entries)
        self.total_qty = sum(e.qty for e in self.entries)
        self.avg_entry_price = total_cost / self.total_qty if self.total_qty > 0 else 0

        return entry

    def calculate_take_profit_price(self, tp_pct: float = 1.0) -> float:
        """
        Рассчитать цену тейк-профита.

        Args:
            tp_pct: Процент прибыли (по умолчанию 1%)

        Returns:
            Цена тейк-профита
        """
        return self.avg_entry_price * (1 + tp_pct / 100)

    def close(self, exit_price: float, commission: float = 0.0):
        """
        Закрыть сделку.

        Args:
            exit_price: Цена выхода
            commission: Суммарная комиссия
        """
        self.closed_at = datetime.now(timezone.utc)
        self.exit_price = exit_price
        self.status = "closed"
        self.commission = commission

        # PnL = (exit - avg_entry) * qty * leverage
        self.pnl = (exit_price - self.avg_entry_price) * self.total_qty * self.leverage
        self.net_pnl = self.pnl - commission


@dataclass
class DailyStats:
    """Статистика за один день."""
    id: Optional[int] = None
    date: str = ""                              # YYYY-MM-DD
    trades_closed: int = 0
    total_pnl: float = 0.0
    total_commission: float = 0.0
    balance: float = 0.0
