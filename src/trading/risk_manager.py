"""
Риск-менеджмент — Crypto Trader Bot

Все проверки безопасности перед входом в позицию.
"""

from utils.logger import get_logger

logger = get_logger("risk")


class RiskManager:
    """
    Контроль рисков перед каждым входом в позицию.

    Проверяет:
    - Количество входов < max_entries
    - Общий объём позиций ≤ баланс
    - Отсутствие цены ликвидации
    - Запрет шорта
    """

    def __init__(
        self,
        max_entries: int = 5,
        max_position_pct: float = 95.0,
        check_liquidation: bool = True,
        allow_short: bool = False,
        liq_safety_pct: float = 30.0,
    ):
        self.max_entries = max_entries
        self.max_position_pct = max_position_pct
        self.check_liquidation = check_liquidation
        self.allow_short = False  # ВСЕГДА False — жёстко в коде
        self.liq_safety_pct = liq_safety_pct  # Запас до ликвидации (%)

        logger.info(
            f"Риск-менеджер: max_entries={max_entries}, "
            f"max_position={max_position_pct}%, check_liq={check_liquidation}, "
            f"anti_liq={liq_safety_pct}%"
        )

    def can_open_entry(
        self,
        current_entries: int,
        current_position_value: float,
        new_entry_value: float,
        balance: float,
        liq_price: float = None,
        side: str = "Buy",
    ) -> tuple[bool, str]:
        """
        Проверить, можно ли открыть новый вход.

        Args:
            current_entries: Текущее количество входов
            current_position_value: Текущий объём позиции ($)
            new_entry_value: Объём нового входа ($)
            balance: Баланс аккаунта ($)
            liq_price: Цена ликвидации (None = нет)
            side: Направление сделки

        Returns:
            (разрешено: bool, причина: str)
        """
        # ── Проверка 1: Запрет шорта ──
        if side != "Buy":
            reason = "🛑 ЗАПРЕТ: только LONG-сделки (Buy). Шорт запрещён."
            logger.error(reason)
            return False, reason

        # ── Проверка 2: Максимум входов ──
        if current_entries >= self.max_entries:
            reason = (
                f"⚠️ Максимум входов достигнут: {current_entries}/{self.max_entries}. "
                f"Ожидание выхода в прибыль."
            )
            logger.warning(reason)
            return False, reason

        # ── Проверка 3: Объём позиции ≤ баланс ──
        total_after = current_position_value + new_entry_value
        max_allowed = balance * (self.max_position_pct / 100)

        if total_after > max_allowed:
            reason = (
                f"⚠️ Превышение объёма: ${total_after:,.2f} > "
                f"${max_allowed:,.2f} ({self.max_position_pct}% от ${balance:,.2f})"
            )
            logger.warning(reason)
            return False, reason

        # ── Проверка 4: Цена ликвидации ──
        if self.check_liquidation and liq_price is not None:
            reason = (
                f"🛑 ОПАСНО: есть цена ликвидации ${liq_price:,.2f}! "
                f"Позиция превышает баланс."
            )
            logger.error(reason)
            return False, reason

        # ── Все проверки пройдены ──
        logger.info(
            f"✅ Проверки пройдены: вход {current_entries + 1}/{self.max_entries}, "
            f"объём ${total_after:,.2f}/${max_allowed:,.2f}"
        )
        return True, "OK"

    def calculate_entry_size(
        self,
        balance: float,
        position_size_pct: float,
        current_price: float,
        leverage: int = 4,
        volatility_factor: float = 1.0,
    ) -> float:
        """
        Рассчитать объём входа в монетах.

        Args:
            balance: Баланс аккаунта ($)
            position_size_pct: Процент от депозита на один вход
            current_price: Текущая цена актива ($)
            leverage: Кредитное плечо
            volatility_factor: Множитель волатильности (0.3–1.5, от ATR)

        Returns:
            Объём в монетах (напр. 0.20 ETH)
        """
        # Сумма в USDT на один вход
        entry_usd = balance * (position_size_pct / 100)

        # Объём в монетах (с учётом плеча)
        qty = (entry_usd * leverage) / current_price

        # Адаптация к волатильности
        if volatility_factor != 1.0:
            original_qty = qty
            qty = qty * volatility_factor
            logger.debug(
                f"Адаптивный размер: {original_qty:.4f} × {volatility_factor:.3f} = {qty:.4f}"
            )

        # Округляем до 2 знаков (минимальный шаг ETH на Bybit)
        qty = round(qty, 2)

        logger.debug(
            f"Расчёт размера: ${entry_usd:,.2f} × {leverage}x / ${current_price:,.2f} "
            f"× vol={volatility_factor:.3f} = {qty} монет"
        )
        return qty

    def should_enter(
        self,
        current_price: float,
        avg_entry_price: float,
        entry_step_pct: float,
        entries_count: int,
    ) -> bool:
        """
        Проверить, нужно ли усредняться (цена упала на entry_step_pct%).

        Args:
            current_price: Текущая цена
            avg_entry_price: Средняя цена текущей позиции
            entry_step_pct: Шаг усреднения в %
            entries_count: Текущее кол-во входов

        Returns:
            True если нужно добавить вход
        """
        if entries_count == 0:
            return False  # Для первого входа используется strategy.py

        # Цена должна упасть на entry_step_pct% от средней цены входа
        threshold = avg_entry_price * (1 - entry_step_pct / 100)

        if current_price <= threshold:
            logger.info(
                f"📉 Сигнал на усреднение: цена ${current_price:,.2f} "
                f"≤ порог ${threshold:,.2f} (-{entry_step_pct}%)"
            )
            return True

        return False

    def should_emergency_close(
        self,
        current_price: float,
        liq_price: float,
        side: str = "Buy",
    ) -> tuple[bool, str]:
        """
        Anti-liquidation guard — проверить, нужно ли экстренно закрыть позицию.

        Если расстояние до ликвидации меньше liq_safety_pct% от текущей цены,
        закрываем позицию с убытком, но СПАСАЕМ депозит.

        Args:
            current_price: Текущая цена
            liq_price: Цена ликвидации (от биржи)
            side: Направление позиции

        Returns:
            (нужно_закрыть: bool, причина: str)
        """
        if liq_price <= 0:
            return False, ""

        if side == "Buy":
            # Long: ликвидация НИЖЕ текущей цены
            if current_price <= liq_price:
                return True, (
                    f"🛑 ANTI-LIQUIDATION: цена ${current_price:,.2f} "
                    f"НИЖЕ ликвидации ${liq_price:,.2f}! ЭКСТРЕННОЕ ЗАКРЫТИЕ!"
                )

            distance_pct = ((current_price - liq_price) / current_price) * 100

            if distance_pct < self.liq_safety_pct:
                return True, (
                    f"🛑 ANTI-LIQUIDATION: цена ${current_price:,.2f} слишком близко "
                    f"к ликвидации ${liq_price:,.2f} (запас {distance_pct:.1f}% < {self.liq_safety_pct}%). "
                    f"ЭКСТРЕННОЕ ЗАКРЫТИЕ!"
                )

        return False, ""
