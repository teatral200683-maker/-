"""
Watchdog — мониторинг здоровья бота на VPS

Запуск через cron каждые 5 минут:
  */5 * * * * /opt/crypto-bot/venv/bin/python /opt/crypto-bot/watchdog.py

Проверяет:
1. Процесс main.py запущен?
2. Лог-файл обновлялся недавно?
3. Файл trades.db доступен?

При проблеме → алерт в Telegram.
"""

import os
import sys
import time
import json
import subprocess
from datetime import datetime, timezone

# Настройки
BOT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BOT_DIR, "logs", "bot.log")
DB_FILE = os.path.join(BOT_DIR, "data", "trades.db")
ENV_FILE = os.path.join(BOT_DIR, ".env")
MAX_LOG_AGE_SEC = 600  # Лог старше 10 минут → тревога
SERVICE_NAME = "crypto-bot"


def load_telegram_creds():
    """Загрузить Telegram-токен и chat_id из .env."""
    token = ""
    chat_id = ""
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("TELEGRAM_BOT_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                elif line.startswith("TELEGRAM_CHAT_ID="):
                    chat_id = line.split("=", 1)[1].strip()
    return token, chat_id


def send_telegram_alert(token: str, chat_id: str, message: str):
    """Отправить алерт в Telegram через curl."""
    import urllib.request
    import urllib.parse

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
    }).encode()

    try:
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                print(f"[WATCHDOG] Telegram алерт отправлен")
            else:
                print(f"[WATCHDOG] Telegram ошибка: {resp.status}")
    except Exception as e:
        print(f"[WATCHDOG] Ошибка отправки Telegram: {e}")


def check_process_running() -> tuple[bool, str]:
    """Проверить, работает ли процесс бота."""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", SERVICE_NAME],
            capture_output=True, text=True, timeout=5
        )
        is_active = result.stdout.strip() == "active"
        if is_active:
            return True, "active"
        return False, result.stdout.strip()
    except Exception as e:
        return False, str(e)


def check_log_fresh() -> tuple[bool, str]:
    """Проверить, обновлялся ли лог недавно."""
    if not os.path.exists(LOG_FILE):
        return False, "файл не существует"

    mtime = os.path.getmtime(LOG_FILE)
    age_sec = time.time() - mtime
    age_min = int(age_sec / 60)

    if age_sec > MAX_LOG_AGE_SEC:
        return False, f"последнее обновление {age_min} мин назад"
    return True, f"обновлён {age_min} мин назад"


def check_db_accessible() -> tuple[bool, str]:
    """Проверить, доступен ли файл БД."""
    if not os.path.exists(DB_FILE):
        return False, "файл не существует"

    try:
        size = os.path.getsize(DB_FILE)
        if size == 0:
            return False, "пустой файл"
        return True, f"OK ({size / 1024:.1f} KB)"
    except Exception as e:
        return False, str(e)


def check_memory() -> tuple[bool, str]:
    """Проверить потребление памяти."""
    try:
        result = subprocess.run(
            ["free", "-m"], capture_output=True, text=True, timeout=5
        )
        lines = result.stdout.strip().split("\n")
        for line in lines:
            if line.startswith("Mem:"):
                parts = line.split()
                total = int(parts[1])
                used = int(parts[2])
                available = int(parts[6]) if len(parts) > 6 else total - used
                pct = (used / total) * 100
                if available < 50:  # Меньше 50 MB свободно
                    return False, f"мало памяти: {available} MB свободно ({pct:.0f}% занято)"
                return True, f"{available} MB свободно ({pct:.0f}% занято)"
    except Exception as e:
        return True, f"не удалось проверить: {e}"
    return True, "OK"


def main():
    """Основная логика watchdog."""
    now = datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
    problems = []

    # Проверка 1: Процесс
    proc_ok, proc_msg = check_process_running()
    if not proc_ok:
        problems.append(f"❌ Процесс: {proc_msg}")

    # Проверка 2: Лог
    log_ok, log_msg = check_log_fresh()
    if not log_ok:
        problems.append(f"❌ Лог: {log_msg}")

    # Проверка 3: БД
    db_ok, db_msg = check_db_accessible()
    if not db_ok:
        problems.append(f"❌ БД: {db_msg}")

    # Проверка 4: Память
    mem_ok, mem_msg = check_memory()
    if not mem_ok:
        problems.append(f"⚠️ RAM: {mem_msg}")

    # Если есть проблемы → алерт
    if problems:
        token, chat_id = load_telegram_creds()
        if token and chat_id:
            details = "\n".join(problems)
            message = (
                f"🚨 <b>WATCHDOG ALERT</b>\n\n"
                f"⏰ {now}\n"
                f"────────────────────\n"
                f"{details}\n"
                f"────────────────────\n"
                f"🔧 Проверьте VPS!"
            )
            send_telegram_alert(token, chat_id, message)
        else:
            print(f"[WATCHDOG] ПРОБЛЕМЫ (Telegram не настроен):")
            for p in problems:
                print(f"  {p}")
    else:
        print(
            f"[WATCHDOG] {now}: ✅ Всё ОК "
            f"(процесс: {proc_msg}, лог: {log_msg}, БД: {db_msg}, RAM: {mem_msg})"
        )


if __name__ == "__main__":
    main()
