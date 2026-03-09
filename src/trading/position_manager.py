"""
Управление позициями — Crypto Trader Bot

Открытие, усреднение и закрытие позиций.
Координация между биржей, БД и риск-менеджером.
"""

from typing import Optional

from exchange.client import BybitClient
from storage.database import Database
from storage.models import Trade, Entry
from trading.risk_manager import RiskManager
from utils.logger import get_logger

logger = get_logger("position")


class PositionManager:
    """
    Управление торговыми позициями.

    Координирует: BybitClient (ордера) + Database (история) + RiskManager (проверки).
    """

    def __init__(
        self,
        client: BybitClient,
        db: Database,
        risk_manager: RiskManager,
        symbol: str = "ETHUSDT",
        leverage: int = 4,
        take_profit_pct: float = 1.0,
        stop_loss_pct: float = 5.0,
        position_size_pct: float = 5.0,
    ):
        self.client = client
        self.db = db
        self.risk = risk_manager
        self.symbol = symbol
        self.leverage = leverage
        self.take_profit_pct = take_profit_pct
        self.stop_loss_pct = stop_loss_pct
        self.position_size_pct = position_size_pct

        # Текущая открытая сделка
        self.current_trade: Optional[Trade] = None

        # Накопленная комиссия за все входы текущей сделки
        self._accumulated_commission: float = 0.0

        # Загружаем открытую сделку из БД (для восстановления)
        self._restore_state()

    def _restore_state(self):
        """Восстановление состояния из БД после перезапуска."""
        trade = self.db.get_open_trade()
        if trade:
            self.current_trade = trade
            logger.info(
                f"🔄 Восстановлена сделка #{trade.id}: "
                f"{trade.entries_count} входов, "
                f"средняя ${trade.avg_entry_price:,.2f}"
            )
        else:
            logger.info("Нет открытых сделок")

    async def open_position(self, current_price: float) -> Optional[Trade]:
        """
        Открыть новую позицию (первый вход).

        Args:
            current_price: Текущая цена актива

        Returns:
            Trade объект или None при ошибке
        """
        if self.current_trade is not None:
            logger.warning("Уже есть открытая позиция — используйте add_entry()")
            return None

        # Получаем баланс
        wallet = self.client.get_wallet_balance()
        if not wallet:
            logger.error("Не удалось получить баланс")
            return None
        balance = wallet["totalAvailableBalance"]

        # Рассчитываем объём
        qty = self.risk.calculate_entry_size(
            balance=balance,
            position_size_pct=self.position_size_pct,
            current_price=current_price,
            leverage=self.leverage,
        )

        if qty <= 0:
            logger.error(f"Некорректный объём: {qty}")
            return None

        # Проверка рисков
        entry_value = qty * current_price / self.leverage
        can_open, reason = self.risk.can_open_entry(
            current_entries=0,
            current_position_value=0,
            new_entry_value=entry_value,
            balance=balance,
            side="Buy",
        )

        if not can_open:
            logger.warning(f"Вход отклонён: {reason}")
            return None

        # Размещаем ордер
        order_id = self.client.place_order(
            symbol=self.symbol,
            side="Buy",
            qty=str(qty),
            order_type="Market",
        )

        if not order_id:
            logger.error("Не удалось разместить ордер")
            return None

        # Получаем реальную цену исполнения и комиссию
        exec_details = self.client.get_execution_details(self.symbol, order_id)
        fill_price = exec_details.get("avg_price", current_price)
        fill_commission = exec_details.get("commission", 0.0)

        # Создаём сделку
        trade = Trade(
            symbol=self.symbol,
            side="Buy",
            leverage=self.leverage,
        )
        trade.add_entry(price=fill_price, qty=qty, order_id=order_id)

        # Сохраняем в БД
        trade.id = self.db.create_trade(trade)
        entry = trade.entries[0]
        entry.trade_id = trade.id
        self.db.create_entry(entry)

        self.current_trade = trade
        self._accumulated_commission = fill_commission

        tp_price = trade.calculate_take_profit_price(self.take_profit_pct)
        logger.info(
            f"🟢 ПОЗИЦИЯ ОТКРЫТА #{trade.id}: "
            f"BUY {qty} {self.symbol} @ ${fill_price:,.2f} "
            f"(комиссия: ${fill_commission:,.4f}), "
            f"TP: ${tp_price:,.2f} (+{self.take_profit_pct}%)"
        )

        return trade

    async def add_entry(self, current_price: float) -> Optional[Entry]:
        """
        Добавить вход (усреднение) к текущей позиции.

        Args:
            current_price: Текущая цена актива

        Returns:
            Entry объект или None
        """
        if self.current_trade is None:
            logger.warning("Нет открытой позиции для усреднения")
            return None

        trade = self.current_trade

        # Получаем баланс
        wallet = self.client.get_wallet_balance()
        if not wallet:
            return None
        balance = wallet["totalAvailableBalance"]

        # Рассчитываем объём
        qty = self.risk.calculate_entry_size(
            balance=balance,
            position_size_pct=self.position_size_pct,
            current_price=current_price,
            leverage=self.leverage,
        )

        if qty <= 0:
            return None

        # Текущая стоимость позиции
        current_value = trade.total_qty * trade.avg_entry_price / self.leverage
        new_value = qty * current_price / self.leverage

        # Проверяем ликвидацию
        position = self.client.get_position(self.symbol)
        liq_price = position.get("liqPrice") if position else None

        # Проверка рисков
        can_open, reason = self.risk.can_open_entry(
            current_entries=trade.entries_count,
            current_position_value=current_value,
            new_entry_value=new_value,
            balance=balance,
            liq_price=liq_price,
            side="Buy",
        )

        if not can_open:
            logger.warning(f"Усреднение отклонено: {reason}")
            return None

        # Размещаем ордер
        order_id = self.client.place_order(
            symbol=self.symbol,
            side="Buy",
            qty=str(qty),
            order_type="Market",
        )

        if not order_id:
            logger.error("Не удалось разместить ордер на усреднение")
            return None

        # Получаем реальную цену исполнения и комиссию
        exec_details = self.client.get_execution_details(self.symbol, order_id)
        fill_price = exec_details.get("avg_price", current_price)
        fill_commission = exec_details.get("commission", 0.0)
        self._accumulated_commission += fill_commission

        # Обновляем сделку
        entry = trade.add_entry(price=fill_price, qty=qty, order_id=order_id)
        entry.trade_id = trade.id

        # Сохраняем в БД
        self.db.create_entry(entry)
        self.db.update_trade(trade)

        tp_price = trade.calculate_take_profit_price(self.take_profit_pct)
        logger.info(
            f"🟢 УСРЕДНЕНИЕ #{trade.entries_count}/{self.risk.max_entries}: "
            f"BUY {qty} @ ${fill_price:,.2f} "
            f"(комиссия: ${fill_commission:,.4f}), "
            f"средняя: ${trade.avg_entry_price:,.2f}, "
            f"TP: ${tp_price:,.2f}"
        )

        return entry

    async def close_position(self, current_price: float) -> Optional[Trade]:
        """
        Закрыть текущую позицию (тейк-профит).

        Args:
            current_price: Цена закрытия (ориентировочная)

        Returns:
            Закрытый Trade или None
        """
        if self.current_trade is None:
            logger.warning("Нет открытой позиции для закрытия")
            return None

        trade = self.current_trade

        # Размещаем SELL ордер (reduce_only!)
        order_id = self.client.place_order(
            symbol=self.symbol,
            side="Sell",
            qty=str(trade.total_qty),
            order_type="Market",
            reduce_only=True,  # ВАЖНО: только закрытие, не шорт!
        )

        if not order_id:
            logger.error("Не удалось закрыть позицию")
            return None

        # Получаем реальную цену исполнения и комиссию
        exec_details = self.client.get_execution_details(self.symbol, order_id)
        exit_price = exec_details.get("avg_price", current_price)
        exit_commission = exec_details.get("commission", 0.0)
        total_commission = self._accumulated_commission + exit_commission

        # Закрываем сделку с реальными данными
        trade.close(exit_price=exit_price, commission=total_commission)
        self.db.update_trade(trade)

        logger.info(
            f"💰 СДЕЛКА ЗАКРЫТА #{trade.id}: "
            f"выход ${exit_price:,.2f}, "
            f"PnL: ${trade.pnl:+,.2f}, "
            f"комиссия: ${total_commission:,.4f}, "
            f"чистый PnL: ${trade.net_pnl:+,.2f}, "
            f"входов: {trade.entries_count}"
        )

        self.current_trade = None
        self._accumulated_commission = 0.0
        return trade

    def should_take_profit(self, current_price: float) -> bool:
        """
        Проверить, достигнут ли тейк-профит.

        Args:
            current_price: Текущая цена

        Returns:
            True если пора закрывать
        """
        if self.current_trade is None:
            return False

        tp_price = self.current_trade.calculate_take_profit_price(self.take_profit_pct)
        return current_price >= tp_price

    def should_stop_loss(self, current_price: float) -> bool:
        """
        Проверить, достигнут ли стоп-лосс.

        Закрывает позицию если цена упала ниже stop_loss_pct% от средней входной.

        Args:
            current_price: Текущая цена

        Returns:
            True если пора закрывать с убытком
        """
        if self.current_trade is None:
            return False

        sl_price = self.current_trade.avg_entry_price * (1 - self.stop_loss_pct / 100)
        return current_price <= sl_price

    @property
    def has_position(self) -> bool:
        """Есть ли открытая позиция."""
        return self.current_trade is not None

    @property
    def entries_count(self) -> int:
        """Количество входов текущей позиции."""
        return self.current_trade.entries_count if self.current_trade else 0
