"""
Загрузчик исторических данных из Bybit API — Crypto Trader Bot

Скачивает OHLCV-свечи ETH/USDT и сохраняет в CSV.
Не требует API-ключей (публичный эндпоинт).

Использование:
    python download_data.py --symbol ETHUSDT --interval 60 --days 365 --output data/eth_1h.csv
    python download_data.py --interval 15 --days 180
"""

import argparse
import csv
import os
import sys
import time
from datetime import datetime, timedelta, timezone

try:
    import requests
except ImportError:
    print("❌ Установите requests: pip install requests")
    sys.exit(1)


BYBIT_KLINE_URL = "https://api.bybit.com/v5/market/kline"

# Интервалы (минуты → строка API)
INTERVALS = {
    1: "1", 3: "3", 5: "5", 15: "15", 30: "30",
    60: "60", 120: "120", 240: "240", 360: "360",
    720: "720", 1440: "D", 10080: "W",
}


def download_klines(
    symbol: str = "ETHUSDT",
    interval: int = 60,
    days: int = 365,
    output: str = None,
) -> str:
    """
    Скачать исторические свечи из Bybit API.

    Args:
        symbol: Торговая пара
        interval: Интервал в минутах (1, 5, 15, 60, 240, 1440)
        days: Количество дней истории
        output: Путь для сохранения CSV

    Returns:
        Путь к сохранённому файлу
    """
    if interval not in INTERVALS:
        print(f"❌ Неподдерживаемый интервал: {interval}")
        print(f"   Доступные: {list(INTERVALS.keys())}")
        return ""

    interval_str = INTERVALS[interval]

    # Имя файла по умолчанию
    if not output:
        interval_name = {1: "1m", 5: "5m", 15: "15m", 60: "1h", 240: "4h", 1440: "1d"}.get(interval, f"{interval}m")
        output = f"data/{symbol.lower()}_{interval_name}_{days}d.csv"

    # Создаём директорию
    os.makedirs(os.path.dirname(output) if os.path.dirname(output) else "data", exist_ok=True)

    print(f"\n{'='*50}")
    print(f"📥 ЗАГРУЗКА ДАННЫХ ИЗ BYBIT API")
    print(f"{'='*50}")
    print(f"  Пара:      {symbol}")
    print(f"  Интервал:  {interval} мин")
    print(f"  Период:    {days} дней")
    print(f"  Файл:      {output}")

    # Расчёт временных границ
    end_ts = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ts = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)

    all_candles = []
    current_end = end_ts
    batch = 0

    while current_end > start_ts:
        batch += 1
        params = {
            "category": "linear",
            "symbol": symbol,
            "interval": interval_str,
            "end": current_end,
            "limit": 1000,
        }

        try:
            resp = requests.get(BYBIT_KLINE_URL, params=params, timeout=10)
            data = resp.json()

            if data.get("retCode") != 0:
                print(f"  ❌ Ошибка API: {data.get('retMsg')}")
                break

            klines = data["result"]["list"]
            if not klines:
                break

            for k in klines:
                ts = int(k[0])
                if ts < start_ts:
                    continue
                all_candles.append({
                    "timestamp": ts,
                    "datetime": datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5]),
                })

            # Сдвигаем окно назад
            current_end = int(klines[-1][0]) - 1

            if batch % 5 == 0:
                oldest = datetime.fromtimestamp(int(klines[-1][0]) / 1000, tz=timezone.utc)
                print(f"  ▶ Пакет {batch}: {len(all_candles):,} свечей (до {oldest.strftime('%Y-%m-%d')})")

            time.sleep(0.1)  # Не превышаем лимит API

        except requests.RequestException as e:
            print(f"  ⚠️ Ошибка запроса: {e}. Повтор через 3 сек...")
            time.sleep(3)
            continue

    if not all_candles:
        print("❌ Не удалось скачать данные")
        return ""

    # Сортируем по времени (API отдаёт от новых к старым)
    all_candles.sort(key=lambda x: x["timestamp"])

    # Убираем дубликаты
    seen = set()
    unique = []
    for c in all_candles:
        if c["timestamp"] not in seen:
            seen.add(c["timestamp"])
            unique.append(c)
    all_candles = unique

    # Сохраняем в CSV
    with open(output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["datetime", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        for c in all_candles:
            writer.writerow({
                "datetime": c["datetime"],
                "open": c["open"],
                "high": c["high"],
                "low": c["low"],
                "close": c["close"],
                "volume": c["volume"],
            })

    period_start = all_candles[0]["datetime"][:10]
    period_end = all_candles[-1]["datetime"][:10]

    print(f"\n✅ Загружено {len(all_candles):,} свечей")
    print(f"   Период: {period_start} — {period_end}")
    print(f"   Файл:   {output}")
    print(f"   Размер: {os.path.getsize(output) / 1024:.1f} КБ")
    print(f"\n💡 Запуск бэктеста:")
    print(f"   python backtester.py --data {output}")

    return output


def main():
    parser = argparse.ArgumentParser(
        description="📥 Загрузка исторических данных ETH/USDT из Bybit API",
    )
    parser.add_argument("--symbol", default="ETHUSDT", help="Торговая пара")
    parser.add_argument("--interval", type=int, default=60, help="Интервал в минутах (1,5,15,60,240)")
    parser.add_argument("--days", type=int, default=365, help="Количество дней истории")
    parser.add_argument("--output", default=None, help="Путь для сохранения CSV")

    args = parser.parse_args()
    download_klines(args.symbol, args.interval, args.days, args.output)


if __name__ == "__main__":
    main()
