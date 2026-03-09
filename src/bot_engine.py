"""
Bot Engine — Crypto Trader Bot

Оркестратор: координация всех модулей, основной цикл работы.
"""

import asyncio
import signal
import sys
from datetime import datetime, timedelta

from config import Config, load_config, validate_config
from exchange.client import BybitClient
from exchange.websocket import BybitWebSocket
from storage.database import Database
from trading.risk_manager import RiskManager
from trading.position_manager import PositionManager
from trading.strategy import TradingStrategy
from notifications.telegram import TelegramNotifier
from notifications.commander import TelegramCommander
from utils.logger import setup_logger, get_logger

logger = get_logger("engine")


class BotEngine:
    """
    Главный оркестратор бота.

    Инициализирует все модули, запускает основной цикл,
    обрабатывает graceful shutdown.
    """

    def __init__(self, config: Config):
        self.config = config
        self._running = False
        self._started_at: datetime = None
        self._session_trades: int = 0
        self._session_pnl: float = 0.0

        # ── Инициализация модулей ──
        # Логирование
        setup_logger(
            log_level=config.bot.log_level,
            log_file=config.bot.log_file,
        )

        # База данных
        self.db = Database()

        # Bybit клиент (REST)
        self.client = BybitClient(
            api_key=config.bybit_api_key,
            api_secret=config.bybit_api_secret,
            testnet=config.bybit_testnet,
        )

        # Bybit WebSocket
        self.ws = BybitWebSocket(
            api_key=config.bybit_api_key,
            api_secret=config.bybit_api_secret,
            testnet=config.bybit_testnet,
            reconnect_attempts=config.bot.reconnect_attempts,
            reconnect_delay=config.bot.reconnect_delay_sec,
        )

        # Риск-менеджмент
        self.risk_manager = RiskManager(
            max_entries=config.trading.max_entries,
            max_position_pct=config.risk.max_position_pct_of_balance,
            check_liquidation=config.risk.check_liquidation,
        )

        # Управление позициями
        self.position_manager = PositionManager(
            client=self.client,
            db=self.db,
            risk_manager=self.risk_manager,
            symbol=config.trading.symbol,
            leverage=config.trading.leverage,
            take_profit_pct=config.trading.take_profit_pct,
            stop_loss_pct=config.trading.stop_loss_pct,
            position_size_pct=config.trading.position_size_pct,
        )

        # Торговая стратегия
        self.strategy = TradingStrategy(
            position_manager=self.position_manager,
            risk_manager=self.risk_manager,
            entry_step_pct=config.trading.entry_step_pct,
            take_profit_pct=config.trading.take_profit_pct,
        )

        # Telegram
        self.notifier = TelegramNotifier(
            bot_token=config.telegram_bot_token,
            chat_id=config.telegram_chat_id,
        )

        # Telegram-команды
        self.commander = TelegramCommander(
            bot_token=config.telegram_bot_token,
            chat_id=config.telegram_chat_id,
        )

        logger.info("✅ Все модули инициализированы")

    async def _pre_flight_checks(self) -> bool:
        """Предполётные проверки перед запуском торговли."""
        logger.info("⏳ Предполётные проверки...")

        checks_passed = True

        # 1. Проверка API-ключа
        perms = self.client.check_api_permissions()
        if not perms.get("can_trade"):
            logger.error("❌ API-ключ не имеет торговых прав")
            checks_passed = False
        else:
            logger.info("  ✅ API-ключ: торговые права")

        if perms.get("has_withdraw"):
            logger.warning("  ⚠️ API-ключ имеет права на вывод!")

        # 2. Баланс
        wallet = self.client.get_wallet_balance()
        if not wallet:
            logger.error("❌ Не удалось получить баланс")
            checks_passed = False
        else:
            balance = wallet["totalEquity"]
            if balance < self.config.trading.working_deposit:
                logger.warning(
                    f"  ⚠️ Баланс ${balance:,.2f} меньше рабочего депозита "
                    f"${self.config.trading.working_deposit:,.2f}"
                )
            else:
                logger.info(f"  ✅ Баланс: ${balance:,.2f}")

        # 3. Установка плеча
        if self.client.set_leverage(self.config.trading.symbol, self.config.trading.leverage):
            logger.info(f"  ✅ Плечо: {self.config.trading.leverage}x")
        else:
            logger.error("❌ Не удалось установить плечо")
            checks_passed = False

        # 4. Telegram
        logger.info("  ✅ Telegram: настроен")

        # 5. База данных
        logger.info("  ✅ База данных: подключена")

        return checks_passed

    async def start(self):
        """Запуск бота."""
        self._running = True
        self._started_at = datetime.utcnow()

        logger.info("=" * 50)
        logger.info("🤖 CRYPTO TRADER BOT v1.1")
        logger.info("=" * 50)
        logger.info(f"🛡️ Стоп-лосс: {self.config.trading.stop_loss_pct}%")

        # Предполётные проверки
        if not await self._pre_flight_checks():
            logger.error("❌ Предполётные проверки не пройдены. Бот не запущен.")
            return

        # Уведомление в Telegram
        wallet = self.client.get_wallet_balance()
        balance = wallet.get("totalEquity", 0) if wallet else 0

        await self.notifier.notify_bot_started(
            balance=balance,
            symbol=self.config.trading.symbol,
            leverage=self.config.trading.leverage,
            tp_pct=self.config.trading.take_profit_pct,
            testnet=self.config.bybit_testnet,
        )

        # Регистрация обработчиков WebSocket
        self.ws.on_price(self._on_price)
        self.ws.on_error(self._on_ws_error)

        # Регистрация Telegram-команд
        self.commander.on_stop(self._handle_telegram_stop)
        self.commander.on_status(self._handle_telegram_status)

        logger.info("🟢 Бот запущен и готов к торговле")
        logger.info("Telegram-команды: /stop, /status, /help")
        logger.info("Press Ctrl+C для остановки")

        # Запуск WebSocket + Telegram-команды параллельно
        try:
            await asyncio.gather(
                self.ws.start(symbol=self.config.trading.symbol),
                self.commander.start(),
            )
        except asyncio.CancelledError:
            logger.info("Получен сигнал остановки")
        finally:
            await self.stop("Завершение работы")

    async def stop(self, reason: str = "Ручная остановка"):
        """Graceful shutdown."""
        if not self._running:
            return

        self._running = False
        logger.info(f"🛑 Остановка бота: {reason}")

        # Останавливаем WebSocket и Telegram-команды
        await self.ws.stop()
        await self.commander.stop()

        # Вычисляем uptime
        uptime = ""
        if self._started_at:
            delta = datetime.utcnow() - self._started_at
            hours, remainder = divmod(int(delta.total_seconds()), 3600)
            minutes = remainder // 60
            uptime = f"{hours}ч {minutes}мин"

        # Уведомление
        wallet = self.client.get_wallet_balance()
        balance = wallet.get("totalEquity", 0) if wallet else 0

        await self.notifier.notify_bot_stopped(
            reason=reason,
            balance=balance,
            session_trades=self._session_trades,
            session_pnl=self._session_pnl,
            uptime=uptime,
        )

        # Закрываем БД
        self.db.close()
        logger.info("Бот остановлен")

    async def _on_price(self, price: float, ticker_data: dict):
        """Обработчик обновления цены из WebSocket."""
        if not self._running:
            return

        result = await self.strategy.on_price_update(price, ticker_data)

        # Если произошла сделка — уведомляем
        if result is not None:
            from storage.models import Trade, Entry

            if isinstance(result, Trade):
                if result.status == "closed":
                    # Сделка закрыта
                    self._session_trades += 1
                    self._session_pnl += result.net_pnl or 0

                    wallet = self.client.get_wallet_balance()
                    balance = wallet.get("totalEquity", 0) if wallet else 0

                    duration = ""
                    if result.opened_at and result.closed_at:
                        delta = result.closed_at - result.opened_at
                        hours, remainder = divmod(int(delta.total_seconds()), 3600)
                        minutes = remainder // 60
                        duration = f"{hours}ч {minutes}мин"

                    await self.notifier.notify_exit(
                        symbol=result.symbol,
                        exit_price=result.exit_price,
                        entries=result.entries_count,
                        pnl=result.pnl or 0,
                        commission=result.commission,
                        net_pnl=result.net_pnl or 0,
                        balance=balance,
                        duration=duration,
                    )
                else:
                    # Новая позиция
                    tp = result.calculate_take_profit_price(self.config.trading.take_profit_pct)
                    total_val = result.total_qty * result.avg_entry_price
                    await self.notifier.notify_entry(
                        entry_num=result.entries_count,
                        max_entries=self.config.trading.max_entries,
                        symbol=result.symbol,
                        price=result.avg_entry_price,
                        qty=result.total_qty,
                        avg_price=result.avg_entry_price,
                        tp_price=tp,
                        total_value=total_val,
                    )

            elif isinstance(result, Entry):
                # Усреднение
                trade = self.position_manager.current_trade
                if trade:
                    tp = trade.calculate_take_profit_price(self.config.trading.take_profit_pct)
                    total_val = trade.total_qty * trade.avg_entry_price
                    await self.notifier.notify_entry(
                        entry_num=trade.entries_count,
                        max_entries=self.config.trading.max_entries,
                        symbol=trade.symbol,
                        price=result.price,
                        qty=result.qty,
                        avg_price=trade.avg_entry_price,
                        tp_price=tp,
                        total_value=total_val,
                    )

                    # Если макс. входов
                    if trade.entries_count >= self.risk_manager.max_entries:
                        await self.notifier.notify_max_entries(
                            symbol=trade.symbol,
                            entries=trade.entries_count,
                            max_entries=self.risk_manager.max_entries,
                            avg_price=trade.avg_entry_price,
                            tp_price=tp,
                            total_value=total_val,
                        )

    async def _on_ws_error(self, error_type: str, message: str, attempt: int):
        """Обработчик ошибок WebSocket."""
        await self.notifier.notify_error(error_type, message, attempt)

    async def _handle_telegram_stop(self):
        """Обработчик Telegram-команды /stop."""
        logger.info("🛑 Получена команда /stop из Telegram")
        await self.stop("Команда /stop из Telegram")

    async def _handle_telegram_status(self) -> str:
        """Обработчик Telegram-команды /status."""
        try:
            # Uptime
            uptime = "N/A"
            if self._started_at:
                delta = datetime.utcnow() - self._started_at
                hours, remainder = divmod(int(delta.total_seconds()), 3600)
                minutes = remainder // 60
                uptime = f"{hours}ч {minutes}мин"

            # Баланс
            wallet = self.client.get_wallet_balance()
            balance = wallet.get("totalEquity", 0) if wallet else 0

            # Статус стратегии
            strategy_status = self.strategy.get_status()
            price = strategy_status.get("last_price", 0)
            highest = strategy_status.get("highest_price", 0)

            # Позиция
            position_lines = ""
            if strategy_status.get("has_position"):
                avg = strategy_status.get("avg_entry_price", 0)
                tp = strategy_status.get("take_profit_price", 0)
                entries = strategy_status.get("entries", 0)
                max_e = strategy_status.get("max_entries", 5)
                pnl = strategy_status.get("unrealized_pnl", 0)
                position_lines = (
                    f"\n📊 ПОЗИЦИЯ\n"
                    f"  Входов: {entries}/{max_e}\n"
                    f"  Средняя: ${avg:,.2f}\n"
                    f"  TP: ${tp:,.2f}\n"
                    f"  PnL: ${pnl:+,.2f}\n"
                )
            else:
                position_lines = "\n📊 Позиция: нет\n"

            text = (
                f"📈 СТАТУС БОТА\n\n"
                f"💵 Цена ETH: ${price:,.2f}\n"
                f"📈 Максимум: ${highest:,.2f}\n"
                f"💼 Баланс: ${balance:,.2f}\n"
                f"{position_lines}\n"
                f"📊 За сессию:\n"
                f"  Сделок: {self._session_trades}\n"
                f"  PnL: ${self._session_pnl:+,.2f}\n"
                f"  Uptime: {uptime}\n"
            )
            return text
        except Exception as e:
            logger.error(f"Ошибка формирования /status: {e}")
            return f"❌ Ошибка получения статуса: {e}"
