"""
Тест Grid-стратегии v2.1 — зональная детекция.

Проверяет:
- Построение сетки
- BUY при цене ≤ уровня
- SELL при цене ≥ уровня
- Ночной режим
- Стоп-лосс
"""

import asyncio
import sys
import os

# Добавляем src в путь
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class MockClient:
    """Мок Bybit-клиента."""
    def __init__(self):
        self.orders = []
        self.balance = 1000.0

    def get_wallet_balance(self):
        return {
            "totalEquity": self.balance,
            "totalAvailableBalance": self.balance,
        }

    def place_order(self, symbol, side, qty, order_type="Market", reduce_only=False):
        self.orders.append({
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "reduce_only": reduce_only,
        })
        return f"test_order_{len(self.orders)}"


class MockDatabase:
    """Мок базы данных."""
    def save_state(self, key, value):
        pass

    def get_open_trade(self):
        return None


class MockRiskManager:
    """Мок риск-менеджера."""
    def __init__(self):
        self.max_entries = 5


def run_test(name, passed_flag):
    """Вспомогательная функция для вывода результата."""
    status = "PASS ✅" if passed_flag else "FAIL ❌"
    print(f"  {name}: {status}")
    return 1 if passed_flag else 0


def test_grid_build():
    """Тест: построение сетки."""
    from trading.grid_strategy import GridStrategy

    client = MockClient()
    db = MockDatabase()
    risk = MockRiskManager()

    strategy = GridStrategy(
        client=client, db=db, risk_manager=risk,
        grid_levels=5, grid_step_pct=0.5, order_qty=0.01,
    )
    strategy._build_grid(2000.0)

    passed = 0
    total = 0

    # Проверяем кол-во уровней
    total += 1
    passed += run_test(
        "10 уровней (5 BUY + 5 SELL)",
        len(strategy._grid) == 10
    )

    # BUY уровни ниже центра
    buy_levels = [g for g in strategy._grid if g.is_buy]
    total += 1
    passed += run_test(
        "5 BUY уровней",
        len(buy_levels) == 5
    )

    # Все BUY ниже центра
    total += 1
    passed += run_test(
        "BUY уровни ниже центра $2000",
        all(g.price < 2000 for g in buy_levels)
    )

    # SELL уровни выше центра
    sell_levels = [g for g in strategy._grid if not g.is_buy]
    total += 1
    passed += run_test(
        "SELL уровни выше центра $2000",
        all(g.price > 2000 for g in sell_levels)
    )

    # Шаг ~$10 (0.5% от $2000)
    total += 1
    first_buy = max(buy_levels, key=lambda g: g.price)  # Ближайший BUY к центру
    step = 2000.0 - first_buy.price
    passed += run_test(
        f"Шаг сетки ~$10 (реальный: ${step:.2f})",
        9.0 < step < 11.0
    )

    return passed, total


def test_zone_buy():
    """Тест: зональная детекция BUY."""
    from trading.grid_strategy import GridStrategy

    client = MockClient()
    db = MockDatabase()
    risk = MockRiskManager()

    strategy = GridStrategy(
        client=client, db=db, risk_manager=risk,
        grid_levels=5, grid_step_pct=0.5, order_qty=0.01,
        max_open_buys=5,
    )

    # Инициализация
    asyncio.run(strategy.on_price_update(2000.0))

    # Цена падает до первого BUY-уровня (~$1990)
    # Ждём, чтобы пройти cooldown
    strategy._last_trade_time = 0

    asyncio.run(strategy.on_price_update(1989.0))

    passed = 0
    total = 0

    # Должен был купить
    total += 1
    buy_orders = [o for o in client.orders if o["side"] == "Buy"]
    passed += run_test(
        f"BUY ордер создан при цене $1989 (ордеров: {len(buy_orders)})",
        len(buy_orders) >= 1
    )

    # Позиция должна быть > 0
    total += 1
    passed += run_test(
        f"Позиция > 0 ({strategy._total_bought:.2f} ETH)",
        strategy._total_bought > 0
    )

    return passed, total


def test_zone_sell():
    """Тест: зональная детекция SELL."""
    from trading.grid_strategy import GridStrategy

    client = MockClient()
    db = MockDatabase()
    risk = MockRiskManager()

    strategy = GridStrategy(
        client=client, db=db, risk_manager=risk,
        grid_levels=5, grid_step_pct=0.5, order_qty=0.01,
        max_open_buys=5,
    )

    # Инициализация
    asyncio.run(strategy.on_price_update(2000.0))

    # Покупаем на первом уровне
    strategy._last_trade_time = 0
    asyncio.run(strategy.on_price_update(1989.0))

    # Цена растёт до SELL-уровня (~$2010)
    strategy._last_trade_time = 0
    asyncio.run(strategy.on_price_update(2011.0))

    passed = 0
    total = 0

    sell_orders = [o for o in client.orders if o["side"] == "Sell"]
    total += 1
    passed += run_test(
        f"SELL ордер создан при цене $2011 (ордеров: {len(sell_orders)})",
        len(sell_orders) >= 1
    )

    # SELL должен быть reduce_only
    total += 1
    if sell_orders:
        passed += run_test(
            "SELL ордер с reduce_only=True",
            sell_orders[0]["reduce_only"] == True
        )
    else:
        passed += run_test("SELL ордер с reduce_only=True", False)

    return passed, total


def test_night_mode():
    """Тест: ночной режим."""
    from trading.grid_strategy import GridStrategy

    strategy = GridStrategy(
        client=MockClient(), db=MockDatabase(), risk_manager=MockRiskManager(),
    )

    passed = 0
    total = 0

    # Проверяем что метод существует
    total += 1
    passed += run_test(
        "Метод _is_night_mode() существует",
        hasattr(strategy, '_is_night_mode')
    )

    # Константы
    total += 1
    passed += run_test(
        f"Ночь: {strategy.NIGHT_START_HOUR}:00–{strategy.NIGHT_END_HOUR}:00 UTC",
        strategy.NIGHT_START_HOUR == 2 and strategy.NIGHT_END_HOUR == 6
    )

    return passed, total


def test_stop_loss():
    """Тест: стоп-лосс."""
    from trading.grid_strategy import GridStrategy

    client = MockClient()
    strategy = GridStrategy(
        client=client, db=MockDatabase(), risk_manager=MockRiskManager(),
        grid_levels=5, grid_step_pct=0.5, order_qty=0.01,
        stop_loss_pct=4.0,
    )

    # Инициализация
    asyncio.run(strategy.on_price_update(2000.0))

    # Вручную устанавливаем позицию (чтобы изолировать тест SL)
    strategy._total_bought = 0.05
    strategy._avg_buy_price = 2000.0
    # Заполняем все BUY-уровни чтобы не было новых покупок
    for g in strategy._grid:
        if g.is_buy:
            g.filled = True
            g.qty = 0.01

    # Цена падает на 4%+ от средней → стоп-лосс
    strategy._last_trade_time = 0
    sl_price = 2000.0 * (1 - 4.0 / 100) - 1  # $1919 → ниже SL
    asyncio.run(strategy.on_price_update(sl_price))

    passed = 0
    total = 0

    sell_orders = [o for o in client.orders if o["side"] == "Sell"]
    total += 1
    passed += run_test(
        f"Стоп-лосс при падении >4% (SELL ордеров: {len(sell_orders)})",
        len(sell_orders) >= 1
    )

    # Позиция должна быть закрыта
    total += 1
    passed += run_test(
        f"Позиция закрыта ({strategy._total_bought:.2f} ETH)",
        strategy._total_bought == 0
    )

    return passed, total


# ═══════════════════════════════════════
# MAIN
# ═══════════════════════════════════════
if __name__ == "__main__":
    print("=" * 50)
    print("GRID STRATEGY v2.1 — UNIT TESTS")
    print("=" * 50)

    total_passed = 0
    total_tests = 0

    tests = [
        ("Построение сетки", test_grid_build),
        ("Зональная детекция BUY", test_zone_buy),
        ("Зональная детекция SELL", test_zone_sell),
        ("Ночной режим", test_night_mode),
        ("Стоп-лосс", test_stop_loss),
    ]

    for name, test_fn in tests:
        print(f"\n── {name} ──")
        try:
            p, t = test_fn()
            total_passed += p
            total_tests += t
        except Exception as e:
            print(f"  ОШИБКА: {e}")
            import traceback
            traceback.print_exc()
            total_tests += 1

    print()
    print("=" * 50)
    print(f"РЕЗУЛЬТАТ: {total_passed}/{total_tests} PASSED")
    if total_passed == total_tests:
        print("✅ ALL TESTS PASSED")
    else:
        print(f"❌ {total_tests - total_passed} TESTS FAILED")
    print("=" * 50)
