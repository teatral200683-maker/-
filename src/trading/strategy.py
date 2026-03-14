"""
Торговая стратегия — Crypto Trader Bot v1.4

Лонговая стратегия с усреднением (DCA).
+ Trailing Take Profit
+ Фильтр тренда (RSI)
+ Адаптивный размер позиции (ATR)
"""

import time
from typing import Optional

from trading.position_manager import PositionManager
from trading.risk_manager import RiskManager
from trading.indicators import Indicators
from utils.logger import get_logger

logger = get_logger("strategy")


class TradingStrategy:
    """
    Лонговая DCA-стратегия на ETH/USDT.

    Логика:
    1. Цена падает → сигнал на первый вход
    2. Цена падает дальше → усреднение (до 5 входов)
    3. Цена растёт → тейк-профит +1% от средней цены
       (или Trailing TP при включении)
    """

    # Минимальный интервал между сделками (секунды)
    MIN_TRADE_INTERVAL = 300  # 5 минут

    def __init__(
        self,
        position_manager: PositionManager,
        risk_manager: RiskManager,
        entry_step_pct: float = 2.0,
        take_profit_pct: float = 1.0,
        # Trailing Take Profit
        trailing_tp_enabled: bool = False,
        trailing_tp_activation_pct: float = 0.5,
        trailing_tp_callback_pct: float = 0.3,
        # Фильтр тренда
        trend_filter_enabled: bool = False,
        trend_rsi_min: int = 25,
        # Адаптивный размер
        adaptive_sizing_enabled: bool = False,
    ):
        self.pm = position_manager
        self.risk = risk_manager
        self.entry_step_pct = entry_step_pct
        self.take_profit_pct = take_profit_pct

        # Trailing TP
        self.trailing_tp_enabled = trailing_tp_enabled
        self.trailing_tp_activation_pct = trailing_tp_activation_pct
        self.trailing_tp_callback_pct = trailing_tp_callback_pct
        self._trailing_active = False
        self._trailing_high: float = 0.0

        # Фильтр тренда
        self.trend_filter_enabled = trend_filter_enabled
        self.trend_rsi_min = trend_rsi_min

        # Адаптивный размер
        self.adaptive_sizing_enabled = adaptive_sizing_enabled

        # Индикаторы
        self.indicators = Indicators()

        # Отслеживание состояния
        self._last_price: float = 0.0
        self._highest_price: float = 0.0
        self._last_trade_time: float = 0.0
        self._last_liq_check_time: float = 0.0  # Anti-liquidation: проверка каждые 10с
        self._initialized: bool = False

        trailing_status = "ВКЛ" if trailing_tp_enabled else "ВЫКЛ"
        trend_status = "ВКЛ" if trend_filter_enabled else "ВЫКЛ"
        adaptive_status = "ВКЛ" if adaptive_sizing_enabled else "ВЫКЛ"

        logger.info(
            f"Стратегия инициализирована: "
            f"entry_step={entry_step_pct}%, TP={take_profit_pct}%, "
            f"cooldown={self.MIN_TRADE_INTERVAL}с"
        )
        logger.info(
            f"  Trailing TP: {trailing_status} "
            f"(активация +{trailing_tp_activation_pct}%, откат {trailing_tp_callback_pct}%)"
        )
        logger.info(f"  Фильтр тренда: {trend_status} (RSI min={trend_rsi_min})")
        logger.info(f"  Адаптивный размер: {adaptive_status}")

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
        """
        # Инициализация при первом тике
        if not self._initialized:
            self._last_price = price
            self._highest_price = price
            self._initialized = True
            logger.info(f"Стратегия запущена. Начальная цена: ${price:,.2f}")
            return

        self._last_price = price

        # Обновляем индикаторы
        self.indicators.update(price)

        # Обновляем максимум
        if price > self._highest_price:
            self._highest_price = price

        # Cooldown между сделками
        if self._is_cooldown_active():
            return

        # ── Логика выхода ──
        if self.pm.has_position:
            # 0. Anti-liquidation guard (проверка каждые 10 секунд)
            now = time.time()
            if now - self._last_liq_check_time >= 10:
                self._last_liq_check_time = now
                try:
                    position = self.pm.client.get_position(self.pm.symbol)
                    liq_price = position.get("liqPrice") if position else None
                    if liq_price:
                        should_close, reason = self.risk.should_emergency_close(
                            current_price=price, liq_price=liq_price
                        )
                        if should_close:
                            logger.critical(reason)
                            trade = await self.pm.close_position(
                                price, close_reason="anti_liquidation"
                            )
                            if trade:
                                self._reset_trailing()
                                self._highest_price = price
                                self._last_trade_time = now
                                return trade
                except Exception as e:
                    logger.error(f"Ошибка проверки ликвидации: {e}")

            # 1. Trailing Take Profit (если включён)
            if self.trailing_tp_enabled:
                result = await self._check_trailing_tp(price)
                if result:
                    return result

            # 2. Обычный Take Profit (если trailing выключен или не активирован)
            if not self.trailing_tp_enabled or not self._trailing_active:
                if self.pm.should_take_profit(price):
                    logger.info(f"🎯 Тейк-профит! Цена ${price:,.2f} достигла цели")
                    trade = await self.pm.close_position(price, close_reason="take_profit")
                    if trade:
                        self._reset_trailing()
                        self._highest_price = price
                        self._last_trade_time = time.time()
                        return trade
                    return

            # 3. Стоп-лосс (всегда работает)
            if self.pm.should_stop_loss(price):
                sl_price = self.pm.current_trade.avg_entry_price * (1 - self.pm.stop_loss_pct / 100)
                logger.warning(
                    f"🛑 СТОП-ЛОСС! Цена ${price:,.2f} ≤ ${sl_price:,.2f} "
                    f"(-{self.pm.stop_loss_pct}% от средней ${self.pm.current_trade.avg_entry_price:,.2f})"
                )
                trade = await self.pm.close_position(price, close_reason="stop_loss")
                if trade:
                    self._reset_trailing()
                    self._highest_price = price
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

    # ── Trailing Take Profit ──

    async def _check_trailing_tp(self, price: float):
        """
        Trailing Take Profit.

        1. Цена ≥ avg + activation% → активируем trailing
        2. Отслеживаем максимум (_trailing_high)
        3. Цена откатилась от максимума на callback% → закрываем
        """
        if not self.pm.current_trade:
            return None

        avg = self.pm.current_trade.avg_entry_price
        activation_price = avg * (1 + self.trailing_tp_activation_pct / 100)

        # Активация
        if not self._trailing_active:
            if price >= activation_price:
                self._trailing_active = True
                self._trailing_high = price
                logger.info(
                    f"📈 Trailing TP АКТИВИРОВАН: цена ${price:,.2f} ≥ "
                    f"${activation_price:,.2f} (+{self.trailing_tp_activation_pct}%)"
                )
            return None

        # Обновляем максимум
        if price > self._trailing_high:
            self._trailing_high = price

        # Проверяем откат
        callback_price = self._trailing_high * (1 - self.trailing_tp_callback_pct / 100)

        if price <= callback_price:
            profit_pct = ((price - avg) / avg) * 100
            logger.info(
                f"🎯 Trailing TP ЗАКРЫТИЕ: цена ${price:,.2f} откатилась от "
                f"максимума ${self._trailing_high:,.2f} "
                f"(callback {self.trailing_tp_callback_pct}%). "
                f"Прибыль: +{profit_pct:.2f}%"
            )
            trade = await self.pm.close_position(price, close_reason="trailing_tp")
            if trade:
                self._reset_trailing()
                self._highest_price = price
                self._last_trade_time = time.time()
                return trade

        return None

    def _reset_trailing(self):
        """Сброс Trailing TP."""
        self._trailing_active = False
        self._trailing_high = 0.0

    # ── Фильтр тренда ──

    def _should_first_entry(self, current_price: float) -> bool:
        """
        Определить, нужно ли открывать первую позицию.

        Сигнал: цена упала на entry_step_pct% от максимума.
        + Фильтр: RSI не ниже trend_rsi_min (если включён)
        """
        if self._highest_price <= 0:
            return False

        drop_pct = (self._highest_price - current_price) / self._highest_price * 100

        if drop_pct >= self.entry_step_pct:
            # RSI фильтр
            if self.trend_filter_enabled and self.indicators.is_ready():
                rsi = self.indicators.get_rsi()
                if rsi is not None and rsi < self.trend_rsi_min:
                    logger.info(
                        f"🚫 Фильтр тренда: RSI={rsi:.1f} < {self.trend_rsi_min} — "
                        f"пропуск входа (рынок ещё падает)"
                    )
                    return False

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
            "trailing_tp_active": self._trailing_active,
            "trailing_high": self._trailing_high,
        }

        # Индикаторы
        if self.indicators.is_ready():
            ind = self.indicators.get_summary()
            status["rsi"] = ind["rsi"]
            status["atr"] = ind["atr"]
            status["ema"] = ind["ema"]
            status["volatility_factor"] = ind["volatility_factor"]

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
