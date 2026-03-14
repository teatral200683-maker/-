"""
Grid-стратегия — Crypto Trader Bot v2.0

Виртуальная сетка ордеров: покупает при падении, продаёт при росте.
Работает 24/7 на любом движении цены.

Только Long: покупает (Buy) при падении, продаёт (Sell reduce_only) при росте.
"""

import time
from typing import Optional, List
from dataclasses import dataclass, field

from exchange.client import BybitClient
from storage.database import Database
from trading.risk_manager import RiskManager
from utils.logger import get_logger

logger = get_logger("grid")


@dataclass
class GridLevel:
    """Один уровень сетки."""
    price: float           # Цена уровня
    index: int             # Индекс уровня (0 = центр)
    is_buy: bool           # True = уровень покупки, False = уровень продажи
    filled: bool = False   # Был ли активирован (куплено на этом уровне)
    qty: float = 0.0       # Сколько куплено на этом уровне


class GridStrategy:
    """
    Виртуальная Grid-стратегия (только Long).

    Логика:
    1. Строим сетку из N уровней BUY (ниже текущей цены)
       и N уровней SELL (выше текущей цены)
    2. Когда цена пересекает BUY-уровень вниз → покупаем
    3. Когда цена пересекает SELL-уровень вверх → продаём
    4. Каждая покупка ждёт свою продажу на уровень выше
    5. Если цена выходит за границы сетки → пересчитываем сетку
    """

    MIN_TRADE_INTERVAL = 10  # Минимальный интервал между сделками (сек)

    def __init__(
        self,
        client: BybitClient,
        db: Database,
        risk_manager: RiskManager,
        symbol: str = "ETHUSDT",
        leverage: int = 2,
        # Grid-параметры
        grid_levels: int = 5,       # Кол-во уровней в каждую сторону
        grid_step_pct: float = 0.5, # Шаг сетки в %
        order_qty: float = 0.01,    # Объём ордера (ETH)
        # Безопасность
        max_open_buys: int = 5,     # Макс. кол-во открытых покупок
        stop_loss_pct: float = 5.0, # СЛ от нижней границы сетки
    ):
        self.client = client
        self.db = db
        self.risk = risk_manager
        self.symbol = symbol
        self.leverage = leverage

        self.grid_levels = grid_levels
        self.grid_step_pct = grid_step_pct
        self.order_qty = order_qty
        self.max_open_buys = max_open_buys
        self.stop_loss_pct = stop_loss_pct

        # Состояние
        self._grid: List[GridLevel] = []
        self._center_price: float = 0.0
        self._last_price: float = 0.0
        self._last_trade_time: float = 0.0
        self._initialized: bool = False
        self._total_bought: float = 0.0   # Суммарная купленная позиция
        self._avg_buy_price: float = 0.0  # Средняя цена покупки
        self._session_trades: int = 0
        self._session_pnl: float = 0.0
        self._tick_count: int = 0  # Счётчик тиков для heartbeat

        logger.info(
            f"Grid-стратегия инициализирована: "
            f"{grid_levels} уровней, шаг {grid_step_pct}%, "
            f"ордер {order_qty} ETH"
        )

    def _build_grid(self, center_price: float):
        """Построить сетку вокруг указанной цены."""
        self._grid = []
        self._center_price = center_price

        # BUY уровни (ниже центра)
        for i in range(1, self.grid_levels + 1):
            price = center_price * (1 - self.grid_step_pct * i / 100)
            self._grid.append(GridLevel(
                price=round(price, 2),
                index=-i,
                is_buy=True,
            ))

        # SELL уровни (выше центра)
        for i in range(1, self.grid_levels + 1):
            price = center_price * (1 + self.grid_step_pct * i / 100)
            self._grid.append(GridLevel(
                price=round(price, 2),
                index=i,
                is_buy=False,
            ))

        # Сортируем по цене
        self._grid.sort(key=lambda g: g.price)

        lower = self._grid[0].price
        upper = self._grid[-1].price
        logger.info(
            f"📊 Сетка построена: центр ${center_price:,.2f}, "
            f"диапазон ${lower:,.2f} – ${upper:,.2f} "
            f"({len(self._grid)} уровней)"
        )

    def _count_open_buys(self) -> int:
        """Сколько BUY-уровней заполнено (позиция открыта)."""
        return sum(1 for g in self._grid if g.is_buy and g.filled)

    async def on_price_update(self, price: float, ticker_data: dict = None):
        """
        Основной обработчик обновления цены.
        Вызывается WebSocket-клиентом при каждом тике.
        """
        # Инициализация при первом тике
        if not self._initialized:
            self._last_price = price
            self._initialized = True
            self._build_grid(price)
            logger.info(f"Grid запущена. Стартовая цена: ${price:,.2f}")
            return

        prev_price = self._last_price
        self._last_price = price

        # Heartbeat — лог каждые 200 тиков + первые 5 тиков
        self._tick_count += 1
        if self._tick_count <= 5 or self._tick_count % 200 == 0:
            nearest_buy = next(
                (g for g in sorted(self._grid, key=lambda x: abs(x.price - price))
                 if g.is_buy and not g.filled), None
            )
            buy_info = f", ближайший BUY: ${nearest_buy.price:,.2f}" if nearest_buy else ""
            logger.info(
                f"💓 Grid tick #{self._tick_count}: ${price:,.2f}{buy_info}"
            )

        # Cooldown между сделками
        now = time.time()
        if now - self._last_trade_time < self.MIN_TRADE_INTERVAL:
            return

        # ── Проверяем пересечение уровней ──
        for level in self._grid:
            if level.is_buy and not level.filled:
                # BUY: цена пересекла уровень сверху вниз
                if prev_price > level.price and price <= level.price:
                    await self._execute_buy(level, price)
                    return

            elif not level.is_buy:
                # SELL: цена пересекла уровень снизу вверх
                if prev_price < level.price and price >= level.price:
                    # Продаём только если есть что продавать
                    if self._total_bought > 0:
                        await self._execute_sell(level, price)
                        return

        # ── Проверка стоп-лосса ──
        if self._total_bought > 0 and self._avg_buy_price > 0:
            loss_pct = (self._avg_buy_price - price) / self._avg_buy_price * 100
            if loss_pct >= self.stop_loss_pct:
                await self._execute_stop_loss(price)
                return

        # ── Пересчёт сетки если цена вышла за границы ──
        if self._grid:
            lower = self._grid[0].price
            upper = self._grid[-1].price
            margin = (upper - lower) * 0.1  # 10% запас

            if price < lower - margin or price > upper + margin:
                if self._total_bought == 0:
                    logger.info(
                        f"🔄 Цена ${price:,.2f} вышла за сетку — пересчёт"
                    )
                    self._build_grid(price)

    async def _execute_buy(self, level: GridLevel, price: float):
        """Выполнить покупку на уровне сетки."""
        # Проверка лимита открытых позиций
        if self._count_open_buys() >= self.max_open_buys:
            logger.info(
                f"⚠️ Макс. {self.max_open_buys} покупок открыто — пропуск"
            )
            return

        # Проверка баланса
        wallet = self.client.get_wallet_balance()
        if not wallet:
            logger.error("Не удалось получить баланс")
            return

        available = wallet["totalAvailableBalance"]
        required = self.order_qty * price / self.leverage
        if available < required * 1.1:  # 10% запас
            logger.warning(
                f"⚠️ Недостаточно средств: нужно ${required:.2f}, "
                f"доступно ${available:.2f}"
            )
            return

        # Размещаем BUY ордер
        qty_str = f"{self.order_qty:.2f}"
        order_id = self.client.place_order(
            symbol=self.symbol,
            side="Buy",
            qty=qty_str,
            order_type="Market",
        )

        if order_id:
            level.filled = True
            level.qty = self.order_qty

            # Обновляем среднюю
            total_cost = self._avg_buy_price * self._total_bought + price * self.order_qty
            self._total_bought += self.order_qty
            self._avg_buy_price = total_cost / self._total_bought

            self._last_trade_time = time.time()
            self._session_trades += 1

            open_buys = self._count_open_buys()
            logger.info(
                f"🟢 GRID BUY #{self._session_trades}: "
                f"купил {qty_str} ETH @ ${price:,.2f} "
                f"(уровень {level.index}, позиция: {self._total_bought:.2f} ETH, "
                f"средняя: ${self._avg_buy_price:,.2f}, "
                f"открыто: {open_buys}/{self.max_open_buys})"
            )
        else:
            logger.error(f"❌ Не удалось купить на уровне ${level.price:,.2f}")

    async def _execute_sell(self, level: GridLevel, price: float):
        """Продать часть позиции при росте до уровня."""
        sell_qty = min(self.order_qty, self._total_bought)
        if sell_qty <= 0:
            return

        qty_str = f"{sell_qty:.2f}"
        order_id = self.client.place_order(
            symbol=self.symbol,
            side="Sell",
            qty=qty_str,
            order_type="Market",
            reduce_only=True,
        )

        if order_id:
            # Считаем прибыль
            profit = (price - self._avg_buy_price) * sell_qty
            self._total_bought -= sell_qty
            self._session_pnl += profit
            self._last_trade_time = time.time()
            self._session_trades += 1

            # Очищаем заполненный BUY-уровень ниже этого SELL
            for g in self._grid:
                if g.is_buy and g.filled and g.price < level.price:
                    g.filled = False
                    g.qty = 0.0
                    break  # один BUY за один SELL

            if self._total_bought <= 0:
                self._total_bought = 0
                self._avg_buy_price = 0

            logger.info(
                f"🔴 GRID SELL #{self._session_trades}: "
                f"продал {qty_str} ETH @ ${price:,.2f} "
                f"(прибыль: ${profit:+,.2f}, "
                f"PnL сессии: ${self._session_pnl:+,.2f}, "
                f"осталось: {self._total_bought:.2f} ETH)"
            )
        else:
            logger.error(
                f"❌ Не удалось продать на уровне ${level.price:,.2f}"
            )

    async def _execute_stop_loss(self, price: float):
        """Экстренное закрытие всей позиции."""
        if self._total_bought <= 0:
            return

        qty_str = f"{self._total_bought:.2f}"
        order_id = self.client.place_order(
            symbol=self.symbol,
            side="Sell",
            qty=qty_str,
            order_type="Market",
            reduce_only=True,
        )

        if order_id:
            loss = (price - self._avg_buy_price) * self._total_bought
            self._session_pnl += loss
            logger.warning(
                f"🛑 GRID СТОП-ЛОСС: продал {qty_str} ETH @ ${price:,.2f} "
                f"(убыток: ${loss:,.2f}, средняя была: ${self._avg_buy_price:,.2f})"
            )
            self._total_bought = 0
            self._avg_buy_price = 0
            self._last_trade_time = time.time()

            # Очищаем все BUY-уровни
            for g in self._grid:
                if g.is_buy:
                    g.filled = False
                    g.qty = 0.0

            # Пересчитываем сетку от текущей цены
            self._build_grid(price)

    def get_status(self) -> dict:
        """Получить текущий статус стратегии."""
        return {
            "strategy": "Grid",
            "last_price": self._last_price,
            "center_price": self._center_price,
            "total_bought": self._total_bought,
            "avg_buy_price": self._avg_buy_price,
            "open_buys": self._count_open_buys(),
            "max_buys": self.max_open_buys,
            "session_trades": self._session_trades,
            "session_pnl": self._session_pnl,
            "grid_levels": len(self._grid),
            "grid_range": (
                f"${self._grid[0].price:,.2f} – ${self._grid[-1].price:,.2f}"
                if self._grid else "N/A"
            ),
        }
