"""
Модуль конфигурации — Crypto Trader Bot

Загрузка .env (секреты) и config.json (параметры стратегии).
Валидация всех параметров при старте.
"""

import json
import os
import sys
from dataclasses import dataclass, field
from typing import Optional

from dotenv import load_dotenv

from utils.logger import get_logger

logger = get_logger("config")


@dataclass
class TradingConfig:
    """Параметры торговой стратегии."""
    symbol: str = "ETHUSDT"
    side: str = "Buy"
    leverage: int = 4
    take_profit_pct: float = 1.0
    stop_loss_pct: float = 5.0          # Стоп-лосс: -5% от средней цены → закрытие
    max_entries: int = 5
    entry_step_pct: float = 2.0
    position_size_pct: float = 5.0
    working_deposit: float = 1000.0
    # Trailing Take Profit
    trailing_tp_enabled: bool = False
    trailing_tp_activation_pct: float = 0.5  # Активация после +0.5%
    trailing_tp_callback_pct: float = 0.3    # Откат от максимума для закрытия
    # Фильтр тренда
    trend_filter_enabled: bool = False
    trend_rsi_min: int = 25              # Не входить если RSI ниже
    # Адаптивный размер
    adaptive_sizing_enabled: bool = False


@dataclass
class RiskConfig:
    """Параметры риск-менеджмента."""
    max_position_pct_of_balance: float = 95.0
    check_liquidation: bool = True
    allow_short: bool = False  # ВСЕГДА False — безопасность
    anti_liquidation_pct: float = 30.0  # Запас до ликвидации (%) — закрыть если меньше
    max_daily_loss_pct: float = 3.0     # Макс. убыток за день (%) — стоп торговли


@dataclass
class NotificationsConfig:
    """Параметры Telegram-уведомлений."""
    on_entry: bool = True
    on_exit: bool = True
    on_error: bool = True
    daily_summary: bool = True
    daily_summary_hour: int = 21


@dataclass
class BotConfig:
    """Параметры работы бота."""
    reconnect_attempts: int = 10
    reconnect_delay_sec: int = 5
    log_level: str = "INFO"
    log_file: str = "logs/bot.log"


@dataclass
class Config:
    """Главный конфигурационный класс."""
    # Секреты из .env
    bybit_api_key: str = ""
    bybit_api_secret: str = ""
    bybit_testnet: bool = True
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Параметры из config.json
    trading: TradingConfig = field(default_factory=TradingConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    notifications: NotificationsConfig = field(default_factory=NotificationsConfig)
    bot: BotConfig = field(default_factory=BotConfig)


def load_config(
    env_path: Optional[str] = None,
    config_path: Optional[str] = None,
) -> Config:
    """
    Загрузка конфигурации из .env и config.json.

    Args:
        env_path: Путь к .env файлу (по умолчанию .env в текущей директории)
        config_path: Путь к config.json (по умолчанию config.json в текущей директории)

    Returns:
        Объект Config с загруженными параметрами
    """
    config = Config()

    # ── Загрузка .env ──────────────────────
    env_file = env_path or os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_file):
        load_dotenv(env_file)
        logger.info(f"Загружен .env: {env_file}")
    else:
        logger.warning(f"Файл .env не найден: {env_file}")

    config.bybit_api_key = os.getenv("BYBIT_API_KEY", "")
    config.bybit_api_secret = os.getenv("BYBIT_API_SECRET", "")
    config.bybit_testnet = os.getenv("BYBIT_TESTNET", "true").lower() == "true"
    config.telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    config.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    # ── Загрузка config.json ───────────────
    json_file = config_path or os.path.join(os.path.dirname(__file__), "config.json")
    if os.path.exists(json_file):
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        logger.info(f"Загружен config.json: {json_file}")

        # Trading
        if "trading" in data:
            config.trading = TradingConfig(**data["trading"])

        # Risk
        if "risk" in data:
            config.risk = RiskConfig(**data["risk"])

        # Notifications
        if "notifications" in data:
            config.notifications = NotificationsConfig(**data["notifications"])

        # Bot
        if "bot" in data:
            config.bot = BotConfig(**data["bot"])
    else:
        logger.warning(f"Файл config.json не найден: {json_file}, используются дефолтные параметры")

    # ── Принудительная безопасность ────────
    config.risk.allow_short = False  # НИКОГДА не разрешаем шорт
    config.trading.side = "Buy"     # ТОЛЬКО покупка

    return config


def validate_config(config: Config) -> list[str]:
    """
    Валидация конфигурации. Возвращает список ошибок.

    Args:
        config: Объект конфигурации

    Returns:
        Список строк с ошибками. Пустой список = всё ОК.
    """
    errors = []
    warnings = []

    # ── Проверка секретов ──────────────────
    if not config.bybit_api_key or config.bybit_api_key == "your_api_key_here":
        errors.append("❌ BYBIT_API_KEY — не указан или содержит placeholder")

    if not config.bybit_api_secret or config.bybit_api_secret == "your_api_secret_here":
        errors.append("❌ BYBIT_API_SECRET — не указан или содержит placeholder")

    if not config.telegram_bot_token or config.telegram_bot_token == "your_bot_token_here":
        errors.append("❌ TELEGRAM_BOT_TOKEN — не указан или содержит placeholder")

    if not config.telegram_chat_id or config.telegram_chat_id == "your_chat_id_here":
        errors.append("❌ TELEGRAM_CHAT_ID — не указан или содержит placeholder")

    # ── Проверка параметров стратегии ──────
    if config.trading.leverage < 1 or config.trading.leverage > 10:
        errors.append(f"❌ leverage: {config.trading.leverage} — должно быть 1–10")

    if config.trading.leverage > 5:
        warnings.append(f"⚠️ leverage: {config.trading.leverage} — рекомендуется ≤ 5")

    if config.trading.take_profit_pct <= 0 or config.trading.take_profit_pct > 10:
        errors.append(f"❌ take_profit_pct: {config.trading.take_profit_pct} — должно быть 0.1–10.0")

    if config.trading.max_entries < 1 or config.trading.max_entries > 10:
        errors.append(f"❌ max_entries: {config.trading.max_entries} — должно быть 1–10")

    if config.trading.entry_step_pct <= 0 or config.trading.entry_step_pct > 20:
        errors.append(f"❌ entry_step_pct: {config.trading.entry_step_pct} — должно быть 0.1–20.0")

    if config.trading.position_size_pct <= 0 or config.trading.position_size_pct > 50:
        errors.append(f"❌ position_size_pct: {config.trading.position_size_pct} — должно быть 0.1–50.0")

    if config.trading.working_deposit < 50:
        errors.append(f"❌ working_deposit: ${config.trading.working_deposit} — минимум $50")

    # ── Проверка безопасности ──────────────
    if config.risk.allow_short:
        errors.append("❌ allow_short: true — шорт запрещён в этом боте!")

    if config.trading.side != "Buy":
        errors.append(f"❌ side: {config.trading.side} — разрешён только 'Buy'")

    # ── Логирование ────────────────────────
    for error in errors:
        logger.error(error)
    for warning in warnings:
        logger.warning(warning)

    if not errors:
        logger.info("✅ Конфигурация валидна")
    else:
        logger.error(f"Найдено {len(errors)} ошибок в конфигурации")

    return errors
