"""
Bybit WebSocket клиент — Crypto Trader Bot

Подписка на реальное время: тикеры, свечи, позиции, ордера.
Автоматический реконнект при разрыве соединения.
"""

import asyncio
import json
import time
import hmac
import hashlib
from typing import Callable, Optional

import websockets

from utils.logger import get_logger

logger = get_logger("websocket")


class BybitWebSocket:
    """
    WebSocket-клиент для получения данных с Bybit в реальном времени.

    Поддерживает публичные (тикеры, свечи) и приватные (ордера, позиции) каналы.
    """

    # URL-адреса WebSocket
    PUBLIC_MAINNET = "wss://stream.bybit.com/v5/public/linear"
    PUBLIC_TESTNET = "wss://stream-testnet.bybit.com/v5/public/linear"
    PRIVATE_MAINNET = "wss://stream.bybit.com/v5/private"
    PRIVATE_TESTNET = "wss://stream-testnet.bybit.com/v5/private"

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        testnet: bool = True,
        reconnect_attempts: int = 10,
        reconnect_delay: int = 5,
    ):
        """
        Инициализация WebSocket-клиента.

        Args:
            api_key: API-ключ Bybit
            api_secret: Секретный ключ Bybit
            testnet: True = тестовая сеть
            reconnect_attempts: Макс. попыток переподключения
            reconnect_delay: Начальная задержка между попытками (сек)
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.reconnect_attempts = reconnect_attempts
        self.reconnect_delay = reconnect_delay

        # Текущие соединения
        self._public_ws: Optional[websockets.WebSocketClientProtocol] = None
        self._private_ws: Optional[websockets.WebSocketClientProtocol] = None

        # Флаг работы
        self._running = False

        # Callback-функции для обработки данных
        self._on_price_update: Optional[Callable] = None
        self._on_kline_update: Optional[Callable] = None
        self._on_order_update: Optional[Callable] = None
        self._on_position_update: Optional[Callable] = None
        self._on_error: Optional[Callable] = None

        mode = "TESTNET" if testnet else "MAINNET"
        logger.info(f"WebSocket клиент инициализирован ({mode})")

    # ── Регистрация callback-функций ──────────────

    def on_price(self, callback: Callable):
        """Регистрация обработчика обновления цены."""
        self._on_price_update = callback

    def on_kline(self, callback: Callable):
        """Регистрация обработчика обновления свечей."""
        self._on_kline_update = callback

    def on_order(self, callback: Callable):
        """Регистрация обработчика обновления ордеров."""
        self._on_order_update = callback

    def on_position(self, callback: Callable):
        """Регистрация обработчика обновления позиций."""
        self._on_position_update = callback

    def on_error(self, callback: Callable):
        """Регистрация обработчика ошибок."""
        self._on_error = callback

    # ── Подключение ───────────────────────────────

    def _get_auth_payload(self) -> dict:
        """Генерация payload для авторизации приватного канала."""
        expires = int(time.time() * 1000) + 10000
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            f"GET/realtime{expires}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return {
            "op": "auth",
            "args": [self.api_key, expires, signature],
        }

    async def _connect_public(self, symbol: str = "ETHUSDT"):
        """Подключение к публичному WebSocket (тикеры, свечи)."""
        url = self.PUBLIC_TESTNET if self.testnet else self.PUBLIC_MAINNET
        attempt = 0

        while self._running and attempt < self.reconnect_attempts:
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=30) as ws:
                    self._public_ws = ws
                    logger.info(f"✅ Публичный WebSocket подключён: {url}")
                    attempt = 0  # Сброс при успешном подключении

                    # Подписка на тикер
                    await ws.send(json.dumps({
                        "op": "subscribe",
                        "args": [f"tickers.{symbol}"],
                    }))
                    logger.info(f"Подписка: tickers.{symbol}")

                    # Подписка на свечи (1 мин)
                    await ws.send(json.dumps({
                        "op": "subscribe",
                        "args": [f"kline.1.{symbol}"],
                    }))
                    logger.info(f"Подписка: kline.1.{symbol}")

                    # Чтение сообщений
                    async for message in ws:
                        if not self._running:
                            break
                        await self._handle_public_message(message)

            except websockets.ConnectionClosed as e:
                attempt += 1
                delay = min(self.reconnect_delay * (2 ** (attempt - 1)), 30)  # Exp. backoff, макс 30с
                logger.warning(
                    f"🔄 Публичный WS разорван: {e}. "
                    f"Переподключение {attempt}/{self.reconnect_attempts} через {delay}с"
                )
                # Уведомление в Telegram только с 3-й попытки (первые 2 — штатный реконнект)
                if self._on_error and attempt >= 3:
                    await self._on_error("ws_disconnect", str(e), attempt)
                await asyncio.sleep(delay)

            except Exception as e:
                attempt += 1
                delay = min(self.reconnect_delay * (2 ** (attempt - 1)), 30)
                logger.error(
                    f"🔴 Ошибка публичного WS: {e}. "
                    f"Попытка {attempt}/{self.reconnect_attempts} через {delay}с"
                )
                if self._on_error and attempt >= 3:
                    await self._on_error("ws_error", str(e), attempt)
                await asyncio.sleep(delay)

        if attempt >= self.reconnect_attempts:
            logger.critical(
                f"❌ Не удалось подключиться после {self.reconnect_attempts} попыток!"
            )

    async def _connect_private(self):
        """Подключение к приватному WebSocket (ордера, позиции)."""
        url = self.PRIVATE_TESTNET if self.testnet else self.PRIVATE_MAINNET
        attempt = 0

        while self._running and attempt < self.reconnect_attempts:
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=30) as ws:
                    self._private_ws = ws
                    logger.info(f"✅ Приватный WebSocket подключён: {url}")
                    attempt = 0

                    # Авторизация
                    await ws.send(json.dumps(self._get_auth_payload()))
                    auth_response = await ws.recv()
                    auth_data = json.loads(auth_response)
                    if auth_data.get("success"):
                        logger.info("✅ Авторизация WebSocket успешна")
                    else:
                        logger.error(f"❌ Авторизация WebSocket: {auth_data}")
                        break

                    # Подписка на приватные каналы
                    await ws.send(json.dumps({
                        "op": "subscribe",
                        "args": ["order", "position", "wallet"],
                    }))
                    logger.info("Подписка: order, position, wallet")

                    # Чтение сообщений
                    async for message in ws:
                        if not self._running:
                            break
                        await self._handle_private_message(message)

            except websockets.ConnectionClosed as e:
                attempt += 1
                delay = min(self.reconnect_delay * (2 ** (attempt - 1)), 30)
                logger.warning(
                    f"🔄 Приватный WS разорван: {e}. "
                    f"Переподключение {attempt}/{self.reconnect_attempts} через {delay}с"
                )
                await asyncio.sleep(delay)

            except Exception as e:
                attempt += 1
                delay = min(self.reconnect_delay * (2 ** (attempt - 1)), 30)
                logger.error(f"🔴 Ошибка приватного WS: {e}. Попытка {attempt}/{self.reconnect_attempts}")
                await asyncio.sleep(delay)

    # ── Обработка сообщений ───────────────────────

    async def _handle_public_message(self, raw: str):
        """Обработка публичных сообщений (тикеры, свечи)."""
        try:
            data = json.loads(raw)

            # Пропускаем подтверждения подписки и пинги
            if "topic" not in data:
                return

            topic = data["topic"]

            if topic.startswith("tickers."):
                # Bybit отправляет snapshot (полный) и delta (частичный).
                # В delta-обновлениях lastPrice может отсутствовать,
                # если цена не изменилась — пропускаем такие.
                ticker = data.get("data", {})
                last_price = ticker.get("lastPrice")
                if last_price is not None and self._on_price_update:
                    await self._on_price_update(float(last_price), ticker)

            elif topic.startswith("kline."):
                if self._on_kline_update:
                    await self._on_kline_update(data["data"])

        except Exception as e:
            logger.error(f"Ошибка обработки публичного сообщения: {e}")

    async def _handle_private_message(self, raw: str):
        """Обработка приватных сообщений (ордера, позиции)."""
        try:
            data = json.loads(raw)

            if "topic" not in data:
                return

            topic = data["topic"]

            if topic == "order":
                if self._on_order_update:
                    for order in data["data"]:
                        await self._on_order_update(order)

            elif topic == "position":
                if self._on_position_update:
                    for position in data["data"]:
                        await self._on_position_update(position)

        except Exception as e:
            logger.error(f"Ошибка обработки приватного сообщения: {e}")

    # ── Управление ────────────────────────────────

    async def start(self, symbol: str = "ETHUSDT"):
        """
        Запуск WebSocket-клиента (публичный + приватный).

        Args:
            symbol: Торговая пара для подписки
        """
        self._running = True
        logger.info("⏳ Запуск WebSocket-подключений...")

        # Запускаем оба подключения параллельно
        await asyncio.gather(
            self._connect_public(symbol),
            self._connect_private(),
        )

    async def stop(self):
        """Остановка WebSocket-клиента."""
        self._running = False
        logger.info("🛑 Остановка WebSocket-клиента...")

        if self._public_ws:
            await self._public_ws.close()
        if self._private_ws:
            await self._private_ws.close()

        logger.info("WebSocket-клиент остановлен")
