"""
Telegram-команды — Crypto Trader Bot

Обработка входящих команд из Telegram для управления ботом.
Команды: /stop, /status, /pnl, /config, /help
"""

import asyncio
from typing import Optional, Callable, Awaitable
from datetime import datetime

import aiohttp
from utils.logger import get_logger

logger = get_logger("tg_cmd")


class TelegramCommander:
    """
    Слушатель команд Telegram через long-polling getUpdates.

    Безопасность: обрабатывает команды ТОЛЬКО от авторизованного chat_id.
    """

    POLL_INTERVAL = 2  # Секунды между запросами getUpdates

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = str(chat_id)
        self._enabled = bool(bot_token and chat_id)
        self._running = False
        self._offset: int = 0  # offset для getUpdates (пропуск старых сообщений)

        # Callback-функции для команд
        self._on_stop: Optional[Callable[[], Awaitable]] = None
        self._on_status: Optional[Callable[[], Awaitable[str]]] = None
        self._on_pnl: Optional[Callable[[], Awaitable[str]]] = None
        self._on_config: Optional[Callable[[], Awaitable[str]]] = None

        if self._enabled:
            logger.info("✅ Telegram-команды включены")

    def on_stop(self, callback: Callable[[], Awaitable]):
        """Регистрация обработчика команды /stop."""
        self._on_stop = callback

    def on_status(self, callback: Callable[[], Awaitable[str]]):
        """Регистрация обработчика команды /status."""
        self._on_status = callback

    def on_pnl(self, callback: Callable[[], Awaitable[str]]):
        """Регистрация обработчика команды /pnl."""
        self._on_pnl = callback

    def on_config(self, callback: Callable[[], Awaitable[str]]):
        """Регистрация обработчика команды /config."""
        self._on_config = callback

    async def start(self):
        """Запуск polling для получения команд."""
        if not self._enabled:
            logger.warning("Telegram-команды отключены")
            return

        self._running = True

        # Сначала пропускаем все старые сообщения
        await self._skip_old_updates()

        logger.info("🎧 Ожидание Telegram-команд...")
        while self._running:
            try:
                await self._poll_updates()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка polling Telegram: {e}")
                await asyncio.sleep(5)

    async def stop(self):
        """Остановка polling."""
        self._running = False

    async def _skip_old_updates(self):
        """Пропустить все накопившиеся обновления (чтобы не реагировать на старые команды)."""
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
            params = {"offset": -1, "limit": 1}

            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        results = data.get("result", [])
                        if results:
                            self._offset = results[-1]["update_id"] + 1
                            logger.info(f"Пропущено старых обновлений, offset={self._offset}")
        except Exception as e:
            logger.warning(f"Не удалось пропустить старые обновления: {e}")

    async def _poll_updates(self):
        """Один цикл polling."""
        url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
        params = {
            "offset": self._offset,
            "limit": 10,
            "timeout": 10,  # Long polling — ждём до 10 секунд
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    await asyncio.sleep(self.POLL_INTERVAL)
                    return

                data = await resp.json()
                updates = data.get("result", [])

                for update in updates:
                    self._offset = update["update_id"] + 1
                    await self._handle_update(update)

    async def _handle_update(self, update: dict):
        """Обработка одного обновления."""
        message = update.get("message")
        if not message:
            return

        # Проверка авторизации — только наш chat_id
        chat_id = str(message.get("chat", {}).get("id", ""))
        if chat_id != self.chat_id:
            logger.warning(f"⚠️ Команда от неавторизованного чата: {chat_id}")
            return

        text = message.get("text", "").strip()
        if not text.startswith("/"):
            return

        command = text.split()[0].lower()
        # Убираем @botname если есть (напр. /stop@MyBot)
        command = command.split("@")[0]

        logger.info(f"📩 Telegram-команда: {command}")

        if command == "/stop":
            await self._cmd_stop()
        elif command == "/status":
            await self._cmd_status()
        elif command == "/pnl":
            await self._cmd_pnl()
        elif command == "/config":
            await self._cmd_config()
        elif command == "/help":
            await self._cmd_help()
        else:
            await self._reply(f"❓ Неизвестная команда: {command}\nНапишите /help для списка команд.")

    async def _cmd_stop(self):
        """Обработка команды /stop."""
        await self._reply("🛑 Остановка бота по команде из Telegram...")
        if self._on_stop:
            await self._on_stop()
        else:
            await self._reply("⚠️ Обработчик /stop не настроен")

    async def _cmd_status(self):
        """Обработка команды /status."""
        if self._on_status:
            try:
                status_text = await self._on_status()
                logger.info(f"Отправка /status ответа ({len(status_text)} символов)")
                await self._reply(status_text)
            except Exception as e:
                logger.error(f"Ошибка при обработке /status: {e}")
                await self._reply(f"❌ Ошибка: {e}")
        else:
            await self._reply("⚠️ Обработчик /status не настроен")

    async def _cmd_pnl(self):
        """Обработка команды /pnl."""
        if self._on_pnl:
            try:
                pnl_text = await self._on_pnl()
                await self._reply(pnl_text)
            except Exception as e:
                logger.error(f"Ошибка при обработке /pnl: {e}")
                await self._reply(f"❌ Ошибка: {e}")
        else:
            await self._reply("⚠️ Обработчик /pnl не настроен")

    async def _cmd_config(self):
        """Обработка команды /config."""
        if self._on_config:
            try:
                config_text = await self._on_config()
                await self._reply(config_text)
            except Exception as e:
                logger.error(f"Ошибка при обработке /config: {e}")
                await self._reply(f"❌ Ошибка: {e}")
        else:
            await self._reply("⚠️ Обработчик /config не настроен")

    async def _cmd_help(self):
        """Обработка команды /help."""
        text = (
            "📋 <b>КОМАНДЫ БОТА</b>\n\n"
            "/status — текущий статус\n"
            "/pnl — PnL за день / неделю / месяц\n"
            "/config — текущие настройки\n"
            "/stop — остановить бота\n"
            "/help — список команд\n"
        )
        await self._reply(text)

    async def _reply(self, text: str):
        """Отправить ответ в Telegram."""
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        logger.info("✅ Ответ отправлен в Telegram")
                    else:
                        body = await resp.text()
                        logger.warning(f"Telegram reply error: {resp.status} {body}")
        except Exception as e:
            logger.warning(f"Ошибка отправки ответа Telegram: {e}")
