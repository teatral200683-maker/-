"""
Разовый отчёт о торговле — отправляется в Telegram.
Запуск: python /opt/crypto-bot/send_report.py
"""
import json
import os
import sqlite3
import urllib.request
from datetime import datetime, timezone, timedelta

DB_PATH = "/opt/crypto-bot/data/trades.db"
ENV_PATH = "/opt/crypto-bot/.env"

MSK = timezone(timedelta(hours=3))

def load_env():
    """Загрузить переменные из .env файла."""
    env = {}
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    env[key.strip()] = value.strip()
    return env

def send_telegram(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "HTML"}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10)

def main():
    env = load_env()
    token = env.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = env.get("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        print("Telegram not configured")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Все сделки
    cur.execute("SELECT * FROM trades ORDER BY id")
    trades = cur.fetchall()

    total = len(trades)
    closed = [t for t in trades if t["status"] == "closed"]
    open_trades = [t for t in trades if t["status"] == "open"]

    winning = [t for t in closed if (t["net_pnl"] or 0) > 0]
    losing = [t for t in closed if (t["net_pnl"] or 0) <= 0]

    total_pnl = sum(t["net_pnl"] or 0 for t in closed)
    total_commission = sum(t["commission"] or 0 for t in closed)
    total_gross = sum(t["pnl"] or 0 for t in closed)

    win_rate = len(winning) / len(closed) * 100 if closed else 0
    avg_win = sum(t["net_pnl"] or 0 for t in winning) / len(winning) if winning else 0
    avg_loss = sum(t["net_pnl"] or 0 for t in losing) / len(losing) if losing else 0

    # Входы
    cur.execute("SELECT COUNT(*) as cnt FROM entries")
    total_entries = cur.fetchone()["cnt"]

    # Статистика по дням (может быть другая схема)
    daily = []
    try:
        cur.execute("SELECT * FROM daily_stats ORDER BY date DESC LIMIT 7")
        daily = cur.fetchall()
    except Exception:
        pass

    # Состояние бота
    state = {}
    try:
        cur.execute("SELECT key, value FROM bot_state")
        state = {r["key"]: r["value"] for r in cur.fetchall()}
    except Exception:
        pass

    conn.close()

    now = datetime.now(MSK).strftime("%d.%m.%Y %H:%M МСК")

    # Формируем отчёт
    lines = [
        f"📊 <b>ПОЛНЫЙ ОТЧЁТ О ТОРГОВЛЕ</b>",
        f"⏰ {now}",
        f"{'─' * 24}",
        f"",
        f"💰 <b>Финансы:</b>",
        f"  └ Чистый PnL: <b>${total_pnl:+,.2f}</b>",
        f"  └ Валовый PnL: ${total_gross:+,.2f}",
        f"  └ Комиссии: ${total_commission:,.2f}",
        f"",
        f"📈 <b>Статистика сделок:</b>",
        f"  └ Всего сделок: {total}",
        f"  └ Закрыто: {len(closed)}",
        f"  └ Открыто сейчас: {len(open_trades)}",
        f"  └ Прибыльных: {len(winning)} ({win_rate:.1f}%)",
        f"  └ Убыточных: {len(losing)}",
        f"  └ Средний выигрыш: ${avg_win:+,.2f}",
        f"  └ Средний убыток: ${avg_loss:+,.2f}",
        f"  └ Всего входов (DCA): {total_entries}",
        f"",
    ]

    # Открытые позиции
    if open_trades:
        lines.append("📂 <b>Открытые позиции:</b>")
        for t in open_trades:
            lines.append(
                f"  └ #{t['id']}: {t['entries_count']} вх., "
                f"средняя ${t['avg_entry_price']:,.2f}, "
                f"объём {t['total_qty']}"
            )
        lines.append("")

    # Дневная статистика (последние 7 дней)
    if daily:
        lines.append("📅 <b>По дням (последние 7):</b>")
        for d in daily:
            try:
                pnl = d["total_pnl"] or 0
                emoji = "🟢" if pnl >= 0 else "🔴"
                tc = d["trades_closed"] if "trades_closed" in d.keys() else 0
                dt = d["date"] if "date" in d.keys() else "?"
                lines.append(
                    f"  {emoji} {dt}: ${pnl:+,.2f} "
                    f"({tc or 0} сделок)"
                )
            except Exception:
                pass
        lines.append("")

    # Состояние бота
    bot_status = state.get("bot_status", "unknown")
    last_price = state.get("last_price", "—")
    session_trades = state.get("session_trades", "0")
    session_pnl = state.get("session_pnl", "0")
    version = state.get("bot_version", "—")

    lines.extend([
        f"🤖 <b>Состояние бота:</b>",
        f"  └ Статус: {bot_status}",
        f"  └ Версия: {version}",
        f"  └ Последняя цена: ${last_price}",
        f"  └ Сделок за сессию: {session_trades}",
        f"  └ PnL за сессию: ${float(session_pnl):+,.2f}",
        f"",
        f"{'─' * 24}",
        f"✅ Отчёт сформирован автоматически",
    ])

    text = "\n".join(lines)
    send_telegram(token, chat_id, text)
    print(f"Report sent at {now}")

if __name__ == "__main__":
    main()
