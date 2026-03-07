"""
Модуль логирования — Crypto Trader Bot

Настройка логгера с ротацией файлов и цветным выводом в консоль.
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from colorama import Fore, Style, init as colorama_init

# Инициализация colorama для Windows
colorama_init(autoreset=True)


class ColoredFormatter(logging.Formatter):
    """Форматтер с цветным выводом для консоли."""

    COLORS = {
        logging.DEBUG: Fore.CYAN,
        logging.INFO: Fore.GREEN,
        logging.WARNING: Fore.YELLOW,
        logging.ERROR: Fore.RED,
        logging.CRITICAL: Fore.RED + Style.BRIGHT,
    }

    def format(self, record):
        color = self.COLORS.get(record.levelno, "")
        # Формат: [время] [УРОВЕНЬ] [модуль] Сообщение
        record.msg = (
            f"{color}[{self.formatTime(record, '%Y-%m-%d %H:%M:%S')}] "
            f"[{record.levelname:<8}] "
            f"[{record.name:<12}] "
            f"{record.getMessage()}{Style.RESET_ALL}"
        )
        return record.msg


class FileFormatter(logging.Formatter):
    """Форматтер для записи в файл (без цветов)."""

    def __init__(self):
        super().__init__(
            fmt="[%(asctime)s] [%(levelname)-8s] [%(name)-12s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )


def setup_logger(
    log_level: str = "INFO",
    log_file: str = "logs/bot.log",
    max_bytes: int = 10 * 1024 * 1024,  # 10 МБ
    backup_count: int = 5,
) -> logging.Logger:
    """
    Настройка корневого логгера.

    Args:
        log_level: Уровень логирования (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Путь к файлу логов
        max_bytes: Максимальный размер файла логов (по умолчанию 10 МБ)
        backup_count: Количество файлов для ротации

    Returns:
        Настроенный корневой логгер
    """
    # Создаём директорию для логов
    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    # Корневой логгер
    root_logger = logging.getLogger("bot")
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Очищаем старые хэндлеры (если перенастраиваем)
    root_logger.handlers.clear()

    # Консольный хэндлер (цветной)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(ColoredFormatter())
    root_logger.addHandler(console_handler)

    # Файловый хэндлер (с ротацией)
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(FileFormatter())
    root_logger.addHandler(file_handler)

    return root_logger


def get_logger(name: str) -> logging.Logger:
    """
    Получить именованный логгер (дочерний от корневого).

    Args:
        name: Имя модуля (exchange, strategy, risk, position, notifier, database)

    Returns:
        Именованный логгер

    Пример:
        logger = get_logger("strategy")
        logger.info("Сигнал на вход: цена $2,450.30")
    """
    return logging.getLogger(f"bot.{name}")
