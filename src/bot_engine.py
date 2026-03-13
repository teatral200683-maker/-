"""
Bot Engine — Crypto Trader Bot

Оркестратор: координация всех модулей, основной цикл работы.
"""

import asyncio
import signal
import sys
from datetime import datetime, date, timedelta, timezone

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

    SUMMARY_INTERVAL_SEC = 3 * 3600  # Сводка каждые 3 часа

    def __init__(self, config: Config):
        self.config = config
        self._running = False
        self._started_at: datetime = None
        self._session_trades: int = 0
        self._session_pnl: float = 0.0
        self._tick_counter: int = 0

        # ── Счётчики для периодической сводки ──
        self._period_trades_opened: int = 0
        self._period_trades_closed: int = 0
        self._period_winning_pnl: float = 0.0
        self._period_losing_pnl: float = 0.0
        self._period_errors: int = 0
        self._period_error_types: list = []

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
        self._started_at = datetime.now(timezone.utc)

        logger.info("=" * 50)
        logger.info("🤖 CRYPTO TRADER BOT v1.4")
        logger.info("=" * 50)

        # Сохраняем состояние при старте
        self.db.save_state("session_start", self._started_at.isoformat())
        self.db.save_state("bot_version", "1.4")
        self.db.save_state("bot_status", "running")
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

        # Запуск WebSocket + Telegram-команды + периодическая сводка параллельно
        try:
            await asyncio.gather(
                self.ws.start(symbol=self.config.trading.symbol),
                self.commander.start(),
                self._periodic_summary_task(),
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
            delta = datetime.now(timezone.utc) - self._started_at
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

        # Сохраняем финальное состояние
        self.db.save_state("bot_status", "stopped")
        self.db.save_state("last_stop_reason", reason)
        self.db.save_state("last_stop_time", datetime.now(timezone.utc).isoformat())
        self.db.save_state("session_trades", str(self._session_trades))
        self.db.save_state("session_pnl", f"{self._session_pnl:.4f}")

        # Закрываем БД
        self.db.close()
        logger.info("Бот остановлен")

    async def _on_price(self, price: float, ticker_data: dict):
        """Обработчик обновления цены из WebSocket."""
        if not self._running:
            return

        result = await self.strategy.on_price_update(price, ticker_data)

        # Периодическое сохранение состояния (каждые 100 тиков)
        self._tick_counter += 1
        if self._tick_counter % 100 == 0:
            try:
                self.db.save_state("last_price", f"{price:.2f}")
                self.db.save_state("session_trades", str(self._session_trades))
                self.db.save_state("session_pnl", f"{self._session_pnl:.4f}")
                self.db.save_state("last_tick_time", datetime.now(timezone.utc).isoformat())
            except Exception as e:
                logger.debug(f"Ошибка сохранения состояния: {e}")

        # Если произошла сделка — обновляем счётчики (без уведомлений)
        if result is not None:
            from storage.models import Trade, Entry

            if isinstance(result, Trade):
                if result.status == "closed":
                    # Сделка закрыта
                    self._session_trades += 1
                    self._session_pnl += result.net_pnl or 0
                    self._period_trades_closed += 1
                    net = result.net_pnl or 0
                    if net >= 0:
                        self._period_winning_pnl += net
                    else:
                        self._period_losing_pnl += net
                else:
                    # Новая позиция
                    self._period_trades_opened += 1

            elif isinstance(result, Entry):
                # Усреднение — не считаем как отдельную сделку
                pass

    async def _on_ws_error(self, error_type: str, message: str, attempt: int):
        """Обработчик ошибок WebSocket — сразу в Telegram + копим для сводки."""
        self._period_errors += 1
        short = f"{error_type} (попытка {attempt})"
        if short not in self._period_error_types:
            self._period_error_types.append(short)
        # Ошибки всегда отправляем сразу (websocket.py уже фильтрует первые 2 попытки)
        await self.notifier.notify_error(error_type, message, attempt)

    # ── Периодическая сводка ──────────────────────

    async def _periodic_summary_task(self):
        """Фоновая задача: отправка сводки каждые 3 часа."""
        while self._running:
            await asyncio.sleep(self.SUMMARY_INTERVAL_SEC)
            if not self._running:
                break
            try:
                await self._send_periodic_summary()
            except Exception as e:
                logger.error(f"Ошибка отправки периодической сводки: {e}")

    async def _send_periodic_summary(self):
        """Собрать и отправить периодическую сводку."""
        # Uptime
        uptime = "N/A"
        if self._started_at:
            delta = datetime.now(timezone.utc) - self._started_at
            hours, remainder = divmod(int(delta.total_seconds()), 3600)
            minutes = remainder // 60
            uptime = f"{hours}ч {minutes}мин"

        # Баланс
        wallet = self.client.get_wallet_balance()
        balance = wallet.get("totalEquity", 0) if wallet else 0

        # Позиция
        has_position = self.position_manager.has_position
        position_info = ""
        if has_position:
            trade = self.position_manager.current_trade
            if trade:
                tp = trade.calculate_take_profit_price(self.config.trading.take_profit_pct)
                position_info = (
                    f"{trade.entries_count} вх., "
                    f"средняя ${trade.avg_entry_price:,.2f}, "
                    f"TP: ${tp:,.2f}"
                )

        # Ошибки
        error_details = ""
        if self._period_error_types:
            error_details = "  " + "\n  ".join(self._period_error_types[-5:])  # макс 5 типов

        await self.notifier.notify_periodic_summary(
            period_label="3 ЧАСА",
            trades_opened=self._period_trades_opened,
            trades_closed=self._period_trades_closed,
            winning_pnl=self._period_winning_pnl,
            losing_pnl=self._period_losing_pnl,
            balance=balance,
            errors_count=self._period_errors,
            error_details=error_details,
            uptime=uptime,
            has_position=has_position,
            position_info=position_info,
        )

        logger.info(
            f"📊 Сводка отправлена: открыто={self._period_trades_opened}, "
            f"закрыто={self._period_trades_closed}, ошибок={self._period_errors}"
        )

        # Сохраняем дневную статистику в БД
        try:
            from storage.models import DailyStats
            net_pnl = self._period_winning_pnl + self._period_losing_pnl
            daily = DailyStats(
                date=date.today().isoformat(),
                trades_closed=self._period_trades_closed,
                total_pnl=net_pnl,
                total_commission=0,
                balance=balance,
            )
            self.db.save_daily_stats(daily)
            logger.info(f"📊 Дневная статистика сохранена: {daily.date}")
        except Exception as e:
            logger.error(f"Ошибка сохранения daily_stats: {e}")

        # Сброс счётчиков
        self._period_trades_opened = 0
        self._period_trades_closed = 0
        self._period_winning_pnl = 0.0
        self._period_losing_pnl = 0.0
        self._period_errors = 0
        self._period_error_types.clear()

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
                delta = datetime.now(timezone.utc) - self._started_at
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
