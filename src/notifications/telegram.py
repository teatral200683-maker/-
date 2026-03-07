"""
Telegram-уведомления — Crypto Trader Bot

Форматирование и отправка уведомлений в Telegram.
"""

import asyncio
from typing import Optional
from datetime import datetime

from utils.logger import get_logger

logger = get_logger("notifier")


class TelegramNotifier:
    """
    Отправка уведомлений о сделках, ошибках и статистике в Telegram.
    """

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self._enabled = bool(bot_token and chat_id)

        if self._enabled:
            logger.info("✅ Telegram-уведомления включены")
        else:
            logger.warning("⚠️ Telegram-уведомления отключены (не указан токен или chat_id)")

    async def _send(self, text: str):
        """Отправить сообщение в Telegram через HTTP API."""
        if not self._enabled:
            return

        import aiohttp
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
        }

        for attempt in range(3):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status == 200:
                            logger.debug("Telegram: сообщение отправлено")
                            return
                        else:
                            body = await resp.text()
                            logger.warning(f"Telegram ответ {resp.status}: {body}")
            except Exception as e:
                logger.warning(f"Telegram попытка {attempt + 1}/3: {e}")
                await asyncio.sleep(2)

        logger.error("Telegram: не удалось отправить сообщение после 3 попыток")

    # ── Шаблоны уведомлений ──────────────────────

    async def notify_bot_started(self, balance: float, symbol: str, leverage: int, tp_pct: float, testnet: bool):
        """Уведомление: бот запущен."""
        mode = "TESTNET" if testnet else "MAINNET"
        now = datetime.utcnow().strftime("%d.%m.%Y %H:%M:%S UTC")
        text = (
            f"✅ <b>БОТ ЗАПУЩЕН</b>\n\n"
            f"📍 Режим: {mode}\n"
            f"⏰ Время: {now}\n"
            f"💼 Баланс: ${balance:,.2f}\n"
            f"📈 Пара: {symbol}\n"
            f"⚙️ Плечо: {leverage}x\n"
            f"🎯 Тейк-профит: {tp_pct}%\n"
            f"────────────────────\n"
            f"🟢 Готов к торговле"
        )
        await self._send(text)

    async def notify_entry(
        self, entry_num: int, max_entries: int, symbol: str,
        price: float, qty: float, avg_price: float, tp_price: float,
        total_value: float,
    ):
        """Уведомление: вход в позицию."""
        now = datetime.utcnow().strftime("%d.%m.%Y %H:%M:%S")
        value = price * qty
        text = (
            f"🟢 <b>ВХОД В ПОЗИЦИЮ #{entry_num}/{max_entries}</b>\n\n"
            f"📈 {symbol}\n"
            f"💵 Цена входа:   ${price:,.2f}\n"
            f"📦 Объём:         {qty} ({f'${value:,.2f}'})\n"
            f"📊 Средняя цена: ${avg_price:,.2f}\n"
            f"🎯 Тейк-профит:  ${tp_price:,.2f}\n"
            f"💼 В позиции:     ${total_value:,.2f}\n"
            f"────────────────────\n"
            f"⏰ {now}"
        )
        await self._send(text)

    async def notify_exit(
        self, symbol: str, exit_price: float, entries: int,
        pnl: float, commission: float, net_pnl: float,
        balance: float, duration: str,
    ):
        """Уведомление: сделка закрыта."""
        now = datetime.utcnow().strftime("%d.%m.%Y %H:%M:%S")
        text = (
            f"💰 <b>СДЕЛКА ЗАКРЫТА</b>\n\n"
            f"📈 {symbol}\n"
            f"💵 Цена выхода:    ${exit_price:,.2f}\n"
            f"📊 Входов:          {entries}\n"
            f"⏱️ Длительность:   {duration}\n"
            f"────────────────────\n"
            f"💹 PnL:            ${pnl:+,.2f}\n"
            f"💸 Комиссия:       ${commission:,.2f}\n"
            f"✅ Чистая прибыль: <b>${net_pnl:+,.2f}</b>\n"
            f"💼 Баланс:         ${balance:,.2f}\n"
            f"────────────────────\n"
            f"⏰ {now}"
        )
        await self._send(text)

    async def notify_max_entries(
        self, symbol: str, entries: int, max_entries: int,
        avg_price: float, tp_price: float, total_value: float,
    ):
        """Уведомление: достигнут максимум входов."""
        now = datetime.utcnow().strftime("%d.%m.%Y %H:%M:%S")
        text = (
            f"⚠️ <b>МАКСИМУМ ВХОДОВ ДОСТИГНУТ</b>\n\n"
            f"📈 {symbol}\n"
            f"📊 Входов: {entries}/{max_entries}\n"
            f"💵 Средняя цена: ${avg_price:,.2f}\n"
            f"🎯 Тейк-профит:  ${tp_price:,.2f}\n"
            f"💼 В позиции:     ${total_value:,.2f}\n"
            f"────────────────────\n"
            f"⏳ Ожидание выхода в прибыль\n"
            f"⏰ {now}"
        )
        await self._send(text)

    async def notify_error(self, error_type: str, message: str, attempt: int = 0):
        """Уведомление: ошибка."""
        now = datetime.utcnow().strftime("%d.%m.%Y %H:%M:%S")
        attempt_text = f"\n📍 Попытка: {attempt}" if attempt else ""
        text = (
            f"🔴 <b>ОШИБКА</b>\n\n"
            f"❌ Тип: {error_type}\n"
            f"📝 {message}"
            f"{attempt_text}\n"
            f"────────────────────\n"
            f"⏰ {now}"
        )
        await self._send(text)

    async def notify_daily_summary(
        self, date_str: str, trades_closed: int, total_pnl: float,
        commission: float, net_pnl: float, open_entries: int,
        max_entries: int, balance: float, monthly_pnl: float,
        total_trades: int,
    ):
        """Уведомление: ежедневная сводка."""
        text = (
            f"📊 <b>СВОДКА ЗА ДЕНЬ</b>\n\n"
            f"📅 {date_str}\n"
            f"────────────────────\n"
            f"✅ Закрыто сделок:  {trades_closed}\n"
            f"💰 PnL за день:    ${total_pnl:+,.2f}\n"
            f"💸 Комиссии:       ${commission:,.2f}\n"
            f"✅ Чистая прибыль: <b>${net_pnl:+,.2f}</b>\n"
            f"────────────────────\n"
            f"📈 Открытых:        {open_entries}/{max_entries}\n"
            f"💼 Баланс:         ${balance:,.2f}\n"
            f"────────────────────\n"
            f"📆 За месяц: ${monthly_pnl:+,.2f}\n"
            f"📆 Всего сделок: {total_trades}"
        )
        await self._send(text)

    async def notify_bot_stopped(self, reason: str, balance: float, session_trades: int, session_pnl: float, uptime: str):
        """Уведомление: бот остановлен."""
        text = (
            f"🛑 <b>БОТ ОСТАНОВЛЕН</b>\n\n"
            f"📍 Причина: {reason}\n"
            f"💼 Баланс: ${balance:,.2f}\n"
            f"────────────────────\n"
            f"📊 За сессию:\n"
            f"   Сделок: {session_trades}\n"
            f"   PnL: ${session_pnl:+,.2f}\n"
            f"   Uptime: {uptime}\n"
        )
        await self._send(text)
