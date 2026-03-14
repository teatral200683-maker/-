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

        # ── Счётчики дневного PnL (Max daily loss) ──
        self._daily_pnl: float = 0.0
        self._daily_date: str = date.today().isoformat()
        self._daily_loss_paused: bool = False
        self._daily_balance_snapshot: float = 0.0  # Баланс на начало дня

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
            liq_safety_pct=config.risk.anti_liquidation_pct,
            max_daily_loss_pct=config.risk.max_daily_loss_pct,
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
            trailing_tp_enabled=config.trading.trailing_tp_enabled,
            trailing_tp_activation_pct=config.trading.trailing_tp_activation_pct,
            trailing_tp_callback_pct=config.trading.trailing_tp_callback_pct,
            trend_filter_enabled=config.trading.trend_filter_enabled,
            trend_rsi_min=config.trading.trend_rsi_min,
            adaptive_sizing_enabled=config.trading.adaptive_sizing_enabled,
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
        self._daily_balance_snapshot = balance  # Баланс на начало дня для max daily loss

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
        self.commander.on_pnl(self._handle_telegram_pnl)
        self.commander.on_config(self._handle_telegram_config)

        logger.info("🟢 Бот запущен и готов к торговле")
        logger.info("Telegram-команды: /stop, /status, /pnl, /config, /help")
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

        # ── Сброс дневных счётчиков в полночь (UTC) ──
        today = date.today().isoformat()
        if today != self._daily_date:
            logger.info(
                f"📅 Новый день ({today}). Сброс дневного PnL "
                f"(вчера: ${self._daily_pnl:+,.2f})"
            )
            self._daily_date = today
            self._daily_pnl = 0.0
            self._daily_loss_paused = False
            # Обновить баланс на начало дня
            try:
                wallet = self.client.get_wallet_balance()
                self._daily_balance_snapshot = wallet.get("totalEquity", 0) if wallet else 0
            except Exception:
                pass

        # ── Max daily loss check ──
        if self._daily_loss_paused:
            return  # Торговля приостановлена до завтра

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

        # Если произошла сделка — уведомление + обновление счётчиков
        if result is not None:
            from storage.models import Trade, Entry

            if isinstance(result, Trade):
                if result.status == "closed":
                    # Сделка закрыта — уведомляем
                    self._session_trades += 1
                    net = result.net_pnl or 0
                    self._session_pnl += net
                    self._daily_pnl += net
                    self._period_trades_closed += 1
                    if net >= 0:
                        self._period_winning_pnl += net
                    else:
                        self._period_losing_pnl += net

                    try:
                        # Вычисляем длительность
                        duration = "—"
                        if result.opened_at and result.closed_at:
                            delta = result.closed_at - result.opened_at
                            hours, remainder = divmod(int(delta.total_seconds()), 3600)
                            minutes = remainder // 60
                            if hours >= 24:
                                days = hours // 24
                                hours = hours % 24
                                duration = f"{days}д {hours}ч {minutes}мин"
                            else:
                                duration = f"{hours}ч {minutes}мин"

                        # Баланс
                        balance = 0
                        try:
                            wallet = self.client.get_wallet_balance()
                            balance = wallet.get("totalEquity", 0) if wallet else 0
                        except Exception as e:
                            logger.warning(f"Не удалось получить баланс: {e}")

                        await self.notifier.notify_exit(
                            symbol=self.config.trading.symbol,
                            exit_price=result.exit_price or 0,
                            entries=result.entries_count,
                            pnl=result.pnl or 0,
                            commission=result.commission or 0,
                            net_pnl=result.net_pnl or 0,
                            balance=balance,
                            duration=duration,
                        )
                        logger.info("📲 Уведомление о закрытии отправлено")
                    except Exception as e:
                        logger.error(f"❌ Ошибка отправки уведомления о закрытии: {e}", exc_info=True)

                    # ── Проверка дневного лимита убытков ──
                    balance_for_check = self._daily_balance_snapshot or balance or 10000
                    exceeded, reason = self.risk_manager.is_daily_loss_exceeded(
                        daily_pnl=self._daily_pnl,
                        balance=balance_for_check,
                    )
                    if exceeded:
                        logger.critical(reason)
                        self._daily_loss_paused = True
                        try:
                            await self.notifier.notify_bot_stopped(
                                reason=reason,
                                balance=balance_for_check,
                                session_trades=self._session_trades,
                                session_pnl=self._session_pnl,
                                uptime="—",
                            )
                        except Exception:
                            pass

                else:
                    # Новая позиция — уведомляем
                    self._period_trades_opened += 1
                    try:
                        entry = result.entries[0] if result.entries else None
                        if entry:
                            tp_price = result.avg_entry_price * (1 + self.config.trading.take_profit_pct / 100)
                            total_value = result.total_qty * result.avg_entry_price
                            await self.notifier.notify_entry(
                                entry_num=1,
                                max_entries=self.config.trading.max_entries,
                                symbol=self.config.trading.symbol,
                                price=entry.price,
                                qty=entry.qty,
                                avg_price=result.avg_entry_price,
                                tp_price=tp_price,
                                total_value=total_value,
                            )
                            logger.info("📲 Уведомление о входе отправлено")
                    except Exception as e:
                        logger.error(f"❌ Ошибка отправки уведомления о входе: {e}", exc_info=True)

            elif isinstance(result, Entry):
                # Усреднение — тоже уведомляем
                try:
                    trade = self.position_manager.current_trade
                    if trade:
                        tp_price = trade.avg_entry_price * (1 + self.config.trading.take_profit_pct / 100)
                        total_value = trade.total_qty * trade.avg_entry_price
                        await self.notifier.notify_entry(
                            entry_num=result.entry_number,
                            max_entries=self.config.trading.max_entries,
                            symbol=self.config.trading.symbol,
                            price=result.price,
                            qty=result.qty,
                            avg_price=trade.avg_entry_price,
                            tp_price=tp_price,
                            total_value=total_value,
                        )
                        logger.info("📲 Уведомление о DCA отправлено")
                except Exception as e:
                    logger.error(f"❌ Ошибка отправки уведомления о DCA: {e}", exc_info=True)

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

    async def _handle_telegram_pnl(self) -> str:
        """Обработчик Telegram-команды /pnl."""
        try:
            cursor = self.db.conn.cursor()

            today = date.today().isoformat()
            week_ago = (date.today() - timedelta(days=7)).isoformat()
            month_ago = (date.today() - timedelta(days=30)).isoformat()

            # За сегодня
            cursor.execute(
                "SELECT COUNT(*) as cnt, COALESCE(SUM(net_pnl),0) as pnl "
                "FROM trades WHERE status='closed' AND date(closed_at) = ?", (today,)
            )
            day = cursor.fetchone()
            day_cnt, day_pnl = day["cnt"], day["pnl"]

            # За неделю
            cursor.execute(
                "SELECT COUNT(*) as cnt, COALESCE(SUM(net_pnl),0) as pnl "
                "FROM trades WHERE status='closed' AND date(closed_at) >= ?", (week_ago,)
            )
            week = cursor.fetchone()
            week_cnt, week_pnl = week["cnt"], week["pnl"]

            # За месяц
            cursor.execute(
                "SELECT COUNT(*) as cnt, COALESCE(SUM(net_pnl),0) as pnl "
                "FROM trades WHERE status='closed' AND date(closed_at) >= ?", (month_ago,)
            )
            month = cursor.fetchone()
            month_cnt, month_pnl = month["cnt"], month["pnl"]

            # Всего
            stats = self.db.get_total_stats()

            def emoji(v): return "🟢" if v >= 0 else "🔴"

            text = (
                f"💰 <b>PnL Статистика</b>\n\n"
                f"{emoji(day_pnl)} <b>Сегодня:</b> ${day_pnl:+,.2f} ({day_cnt} сделок)\n"
                f"{emoji(week_pnl)} <b>Неделя:</b> ${week_pnl:+,.2f} ({week_cnt} сделок)\n"
                f"{emoji(month_pnl)} <b>Месяц:</b> ${month_pnl:+,.2f} ({month_cnt} сделок)\n\n"
                f"📊 <b>Всего:</b>\n"
                f"  Сделок: {stats['total_trades']}\n"
                f"  Win rate: {stats['win_rate']:.0f}%\n"
                f"  Прибыль: ${stats['total_profit']:+,.2f}\n"
                f"  Средняя: ${stats['avg_profit']:+,.2f}\n"
            )
            return text
        except Exception as e:
            logger.error(f"Ошибка /pnl: {e}")
            return f"❌ Ошибка: {e}"

    async def _handle_telegram_config(self) -> str:
        """Обработчик Telegram-команды /config."""
        try:
            c = self.config
            t = c.trading
            r = c.risk

            trail = "ВКЛ" if t.trailing_tp_enabled else "ВЫКЛ"
            trend = "ВКЛ" if t.trend_filter_enabled else "ВЫКЛ"
            adapt = "ВКЛ" if t.adaptive_sizing_enabled else "ВЫКЛ"
            mode = "TESTNET" if c.bybit_testnet else "MAINNET"

            text = (
                f"⚙️ <b>НАСТРОЙКИ БОТА</b>\n\n"
                f"🎯 <b>Торговля:</b>\n"
                f"  Пара: {t.symbol}\n"
                f"  Плечо: {t.leverage}x\n"
                f"  ТP: +{t.take_profit_pct}%\n"
                f"  SL: -{t.stop_loss_pct}%\n"
                f"  Макс. входов: {t.max_entries}\n"
                f"  Шаг DCA: {t.entry_step_pct}%\n"
                f"  Размер: {t.position_size_pct}%\n\n"
                f"🛡 <b>Риски:</b>\n"
                f"  Anti-liquidation: {r.anti_liquidation_pct}%\n"
                f"  Max daily loss: {r.max_daily_loss_pct}%\n\n"
                f"🔧 <b>Модули:</b>\n"
                f"  Trailing TP: {trail}\n"
                f"  RSI фильтр: {trend} (min={t.trend_rsi_min})\n"
                f"  Адаптивный размер: {adapt}\n\n"
                f"🏭 Режим: <b>{mode}</b>\n"
            )
            return text
        except Exception as e:
            logger.error(f"Ошибка /config: {e}")
            return f"❌ Ошибка: {e}"
