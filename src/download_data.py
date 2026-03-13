"""
Загрузка исторических данных ETH/USDT с Bybit API.

Скачивает 1-часовые свечи и сохраняет в CSV.
Bybit поддерживает до 1000 свечей за запрос.

Использование:
    python download_data.py
"""

import csv
import time
import os
import sys
from datetime import datetime, timezone
import urllib.request
import json


BYBIT_API = "https://api.bybit.com"
SYMBOL = "ETHUSDT"
INTERVAL = "60"  # 1 час
LIMIT = 1000     # макс за запрос


def fetch_klines(start_ms: int, end_ms: int) -> list:
    """Загрузить свечи с Bybit API."""
    url = (
        f"{BYBIT_API}/v5/market/kline"
        f"?category=linear&symbol={SYMBOL}&interval={INTERVAL}"
        f"&start={start_ms}&end={end_ms}&limit={LIMIT}"
    )

    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "CryptoBot-Backtest/1.0")
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())

        if data.get("retCode") != 0:
            print(f"  ❌ API ошибка: {data.get('retMsg')}")
            return []

        return data.get("result", {}).get("list", [])

    except Exception as e:
        print(f"  ❌ Ошибка запроса: {e}")
        return []


def download_eth_2026():
    """Скачать данные ETH/USDT за январь–март 2026."""

    start_dt = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    end_dt = datetime(2026, 3, 13, 23, 59, 59, tzinfo=timezone.utc)

    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)

    print(f"📥 Загрузка ETH/USDT 1H свечей с Bybit")
    print(f"   Период: {start_dt.strftime('%d.%m.%Y')} — {end_dt.strftime('%d.%m.%Y')}")

    all_candles = []
    current_end = end_ms

    while current_end > start_ms:
        candles = fetch_klines(start_ms, current_end)
        if not candles:
            break

        all_candles.extend(candles)
        print(f"  ✅ Получено {len(candles)} свечей, всего: {len(all_candles)}")

        oldest_ts = int(candles[-1][0])
        current_end = oldest_ts - 1

        if len(candles) < LIMIT:
            break

        time.sleep(0.3)

    if not all_candles:
        print("❌ Не удалось загрузить данные")
        return None

    # Убираем дубли и сортируем
    seen = set()
    unique = []
    for c in all_candles:
        ts = c[0]
        if ts not in seen:
            seen.add(ts)
            unique.append(c)

    unique.sort(key=lambda x: int(x[0]))
    filtered = [c for c in unique if start_ms <= int(c[0]) <= end_ms]

    print(f"\n📊 Итого: {len(filtered)} уникальных свечей")

    # Сохранение CSV
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, "eth_2026_1h.csv")

    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for c in filtered:
            ts = datetime.utcfromtimestamp(int(c[0]) / 1000)
            writer.writerow([ts.strftime("%Y-%m-%d %H:%M:%S"), c[1], c[2], c[3], c[4], c[5]])

    print(f"✅ Сохранено: {output_file}")

    if filtered:
        first_price = float(filtered[0][4])
        last_price = float(filtered[-1][4])
        change_pct = (last_price - first_price) / first_price * 100
        print(f"   Первая цена: ${first_price:,.2f}, Последняя: ${last_price:,.2f}, Изменение: {change_pct:+.1f}%")

    return output_file


if __name__ == "__main__":
    download_eth_2026()
