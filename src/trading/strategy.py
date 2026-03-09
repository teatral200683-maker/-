"""
Торговая стратегия — Crypto Trader Bot

Лонговая стратегия с усреднением (DCA).
Анализ цены, генерация сигналов на вход и выход.
"""

import time
from typing import Optional

from trading.position_manager import PositionManager
from trading.risk_manager import RiskManager
from utils.logger import get_logger

logger = get_logger("strategy")


class TradingStrategy:
    """
    Лонговая DCA-стратегия на ETH/USDT.

    Логика:
    1. Цена падает → сигнал на первый вход
    2. Цена падает дальше → усреднение (до 5 входов)
    3. Цена растёт → тейк-профит +1% от средней цены
    """

    # Минимальный интервал между сделками (секунды)
    MIN_TRADE_INTERVAL = 300  # 5 минут

    def __init__(
        self,
        position_manager: PositionManager,
        risk_manager: RiskManager,
        entry_step_pct: float = 2.0,
        take_profit_pct: float = 1.0,
    ):
        self.pm = position_manager
        self.risk = risk_manager
        self.entry_step_pct = entry_step_pct
        self.take_profit_pct = take_profit_pct

        # Отслеживание состояния
        self._last_price: float = 0.0
        self._highest_price: float = 0.0    # Максимум за текущий цикл
        self._last_trade_time: float = 0.0  # Время последней сделки (Unix)
        self._initialized: bool = False

        logger.info(
            f"Стратегия инициализирована: "
            f"entry_step={entry_step_pct}%, TP={take_profit_pct}%, "
            f"cooldown={self.MIN_TRADE_INTERVAL}с"
        )

    def _is_cooldown_active(self) -> bool:
        """Проверить, активен ли cooldown между сделками."""
        if self._last_trade_time == 0:
            return False
        elapsed = time.time() - self._last_trade_time
        if elapsed < self.MIN_TRADE_INTERVAL:
            return True
        return False

    async def on_price_update(self, price: float, ticker_data: dict = None):
        """
        Основной обработчик обновления цены.

        Вызывается WebSocket-клиентом при каждом тике.

        Args:
            price: Текущая цена ETH/USDT
            ticker_data: Необработанные данные тикера
        """
        # Инициализация при первом тике
        if not self._initialized:
            self._last_price = price
            self._highest_price = price
            self._initialized = True
            logger.info(f"Стратегия запущена. Начальная цена: ${price:,.2f}")
            return

        self._last_price = price

        # Обновляем максимум
        if price > self._highest_price:
            self._highest_price = price

        # Cooldown между сделками (по времени, а не по тикам)
        if self._is_cooldown_active():
            return

        # ── Логика тейк-профита ──
        if self.pm.has_position:
            if self.pm.should_take_profit(price):
                logger.info(f"🎯 Тейк-профит! Цена ${price:,.2f} достигла цели")
                trade = await self.pm.close_position(price)
                if trade:
                    self._highest_price = price  # Сброс максимума
                    self._last_trade_time = time.time()
                    return trade
                return

            # ── Логика стоп-лосса ──
            if self.pm.should_stop_loss(price):
                sl_price = self.pm.current_trade.avg_entry_price * (1 - self.pm.stop_loss_pct / 100)
                logger.warning(
                    f"🛑 СТОП-ЛОСС! Цена ${price:,.2f} ≤ ${sl_price:,.2f} "
                    f"(-{self.pm.stop_loss_pct}% от средней ${self.pm.current_trade.avg_entry_price:,.2f})"
                )
                trade = await self.pm.close_position(price)
                if trade:
                    self._highest_price = price  # Сброс максимума
                    self._last_trade_time = time.time()
                    return trade
                return

        # ── Логика входа / усреднения ──
        if self.pm.has_position:
            # Усреднение: цена упала на entry_step_pct%
            should_avg = self.risk.should_enter(
                current_price=price,
                avg_entry_price=self.pm.current_trade.avg_entry_price,
                entry_step_pct=self.entry_step_pct,
                entries_count=self.pm.entries_count,
            )
            if should_avg:
                entry = await self.pm.add_entry(price)
                if entry:
                    self._last_trade_time = time.time()
                    return entry
        else:
            # Первый вход: цена упала от максимума на entry_step_pct%
            if self._should_first_entry(price):
                trade = await self.pm.open_position(price)
                if trade:
                    self._last_trade_time = time.time()
                    return trade

    def _should_first_entry(self, current_price: float) -> bool:
        """
        Определить, нужно ли открывать первую позицию.

        Сигнал: цена упала на entry_step_pct% от локального максимума.

        Args:
            current_price: Текущая цена

        Returns:
            True если нужно входить
        """
        if self._highest_price <= 0:
            return False

        drop_pct = (self._highest_price - current_price) / self._highest_price * 100

        if drop_pct >= self.entry_step_pct:
            logger.info(
                f"📉 Сигнал на первый вход: "
                f"цена ${current_price:,.2f} упала на {drop_pct:.1f}% "
                f"от максимума ${self._highest_price:,.2f}"
            )
            return True

        return False

    def get_status(self) -> dict:
        """Получить текущий статус стратегии."""
        status = {
            "last_price": self._last_price,
            "highest_price": self._highest_price,
            "has_position": self.pm.has_position,
            "entries": self.pm.entries_count,
            "max_entries": self.risk.max_entries,
        }

        if self.pm.has_position and self.pm.current_trade:
            trade = self.pm.current_trade
            tp_price = trade.calculate_take_profit_price(self.take_profit_pct)
            status.update({
                "avg_entry_price": trade.avg_entry_price,
                "take_profit_price": tp_price,
                "total_qty": trade.total_qty,
                "unrealized_pnl": (self._last_price - trade.avg_entry_price) * trade.total_qty * trade.leverage,
            })

        return status
