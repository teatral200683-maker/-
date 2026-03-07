"""
Оптимизатор параметров DCA-стратегии — Crypto Trader Bot

Grid Search по комбинациям: TP%, шаг усреднения, размер входа, макс. входов.
Находит лучшие параметры по ROI, винрейту и Шарпу.

Использование:
    python optimizer.py --data data/ethusdt_1h_4y.csv
    python optimizer.py --data data/ethusdt_1h_4y.csv --deposit 5000
"""

import csv
import os
import sys
import argparse
import itertools
from datetime import datetime

from backtester import Backtester, BacktestConfig, load_csv


# ══════════════════════════════════════════
# Сетка параметров для поиска
# ══════════════════════════════════════════

PARAM_GRID = {
    "take_profit_pct":  [0.3, 0.5, 0.7, 1.0, 1.5, 2.0],
    "entry_step_pct":   [1.0, 1.5, 2.0, 3.0, 4.0],
    "position_size_pct": [3.0, 5.0, 8.0, 10.0, 15.0],
    "max_entries":      [3, 5, 7],
    "leverage":         [2, 4, 6],
}

# Итого комбинаций: 6 × 5 × 5 × 3 × 3 = 1,350


def run_optimization(data_file: str, deposit: float = 1000.0, top_n: int = 20):
    """
    Запуск grid search оптимизации.

    Args:
        data_file: Путь к CSV с данными
        deposit: Начальный депозит
        top_n: Сколько лучших результатов показать
    """
    # Загрузка данных
    candles = load_csv(data_file)
    if not candles:
        return

    # Все комбинации параметров
    keys = list(PARAM_GRID.keys())
    values = list(PARAM_GRID.values())
    combinations = list(itertools.product(*values))
    total = len(combinations)

    print(f"\n{'='*60}")
    print(f"🔬 ОПТИМИЗАЦИЯ ПАРАМЕТРОВ СТРАТЕГИИ")
    print(f"{'='*60}")
    print(f"  Данные:      {os.path.basename(data_file)}")
    print(f"  Свечей:      {len(candles):,}")
    print(f"  Депозит:     ${deposit:,.2f}")
    print(f"  Комбинаций:  {total:,}")
    print(f"  Параметры:")
    for k, v in PARAM_GRID.items():
        print(f"    {k}: {v}")
    print(f"{'='*60}\n")

    results = []
    start_time = datetime.now()

    for i, combo in enumerate(combinations):
        params = dict(zip(keys, combo))

        config = BacktestConfig(
            deposit=deposit,
            leverage=params["leverage"],
            take_profit_pct=params["take_profit_pct"],
            max_entries=params["max_entries"],
            entry_step_pct=params["entry_step_pct"],
            position_size_pct=params["position_size_pct"],
        )

        # Тихий прогон (без вывода)
        bt = Backtester(config)
        bt._silent = True

        # Переопределяем print чтобы не засорять вывод
        import builtins
        _print = builtins.print
        builtins.print = lambda *a, **kw: None

        try:
            report = bt.run(candles)
        except Exception:
            builtins.print = _print
            continue
        finally:
            builtins.print = _print

        if not report:
            continue

        result = {
            **params,
            "roi": report.get("roi", 0),
            "total_pnl": report.get("total_pnl", 0),
            "win_rate": report.get("win_rate", 0),
            "total_trades": report.get("total_trades", 0),
            "trades_per_day": report.get("trades_per_day", 0),
            "daily_pnl": report.get("daily_pnl", 0),
            "max_trade_dd": report.get("max_trade_drawdown", 0),
            "max_balance_dd": report.get("max_balance_drawdown", 0),
            "max_duration_h": report.get("max_duration_h", 0),
            "avg_entries": report.get("avg_entries", 0),
            "final_balance": report.get("final_balance", 0),
            "commission": report.get("total_commission", 0),
        }
        results.append(result)

        # Прогресс
        if (i + 1) % 50 == 0 or (i + 1) == total:
            pct = (i + 1) / total * 100
            elapsed = (datetime.now() - start_time).total_seconds()
            eta = elapsed / (i + 1) * (total - i - 1) if i > 0 else 0
            best_roi = max((r["roi"] for r in results), default=0)
            _print(
                f"  [{pct:5.1f}%] {i+1}/{total} | "
                f"Лучший ROI: {best_roi:+.2f}% | "
                f"ETA: {eta:.0f}с"
            )

    elapsed_total = (datetime.now() - start_time).total_seconds()

    if not results:
        print("❌ Нет результатов")
        return

    # ── Сортировка по ROI ──
    results.sort(key=lambda r: r["roi"], reverse=True)

    # ── Вывод TOP-N ──
    print(f"\n{'='*60}")
    print(f"🏆 ТОП-{top_n} ЛУЧШИХ КОМБИНАЦИЙ (по ROI)")
    print(f"{'='*60}")
    print(f"{'#':>3} {'TP%':>5} {'Шаг%':>5} {'Разм%':>5} {'Вход':>4} "
          f"{'Плечо':>5} {'ROI%':>8} {'Сделок':>6} {'WR%':>5} "
          f"{'PnL':>10} {'MaxDD%':>7} {'Макс.дн':>8}")
    print(f"{'─'*3} {'─'*5} {'─'*5} {'─'*5} {'─'*4} "
          f"{'─'*5} {'─'*8} {'─'*6} {'─'*5} "
          f"{'─'*10} {'─'*7} {'─'*8}")

    for idx, r in enumerate(results[:top_n]):
        max_days = r["max_duration_h"] / 24
        print(
            f"{idx+1:3} {r['take_profit_pct']:5.1f} {r['entry_step_pct']:5.1f} "
            f"{r['position_size_pct']:5.1f} {r['max_entries']:4} "
            f"{r['leverage']:5} {r['roi']:+8.2f} {r['total_trades']:6} "
            f"{r['win_rate']:5.1f} {r['total_pnl']:+10.2f} "
            f"{r['max_balance_dd']:7.1f} {max_days:8.0f}"
        )

    # ── Лучший результат ──
    best = results[0]
    print(f"\n{'='*60}")
    print(f"⭐ ЛУЧШИЕ ПАРАМЕТРЫ")
    print(f"{'='*60}")
    print(f"  take_profit_pct:   {best['take_profit_pct']}%")
    print(f"  entry_step_pct:    {best['entry_step_pct']}%")
    print(f"  position_size_pct: {best['position_size_pct']}%")
    print(f"  max_entries:       {best['max_entries']}")
    print(f"  leverage:          {best['leverage']}x")
    print(f"")
    print(f"  ROI:               {best['roi']:+.2f}%")
    print(f"  Итоговый баланс:   ${best['final_balance']:,.2f}")
    print(f"  PnL:               ${best['total_pnl']:+,.2f}")
    print(f"  Сделок:            {best['total_trades']}")
    print(f"  Винрейт:           {best['win_rate']:.1f}%")
    print(f"  Сделок/день:       {best['trades_per_day']:.1f}")
    print(f"  PnL/день:          ${best['daily_pnl']:+,.2f}")
    print(f"  Макс. просадка:    {best['max_balance_dd']:.1f}%")
    print(f"  Комиссии:          ${best['commission']:,.2f}")

    # ── Баланс ROI vs Риск ──
    # Ищем лучший по ROI/Drawdown
    for r in results:
        if r["max_balance_dd"] > 0:
            r["roi_dd_ratio"] = r["roi"] / r["max_balance_dd"]
        else:
            r["roi_dd_ratio"] = r["roi"]

    results_safe = sorted(results, key=lambda r: r["roi_dd_ratio"], reverse=True)

    print(f"\n{'='*60}")
    print(f"🛡️ ЛУЧШЕЕ СООТНОШЕНИЕ ROI/РИСК (TOP-5)")
    print(f"{'='*60}")
    print(f"{'#':>3} {'TP%':>5} {'Шаг%':>5} {'Разм%':>5} {'Вход':>4} "
          f"{'Плечо':>5} {'ROI%':>8} {'MaxDD%':>7} {'Ratio':>7}")
    print(f"{'─'*3} {'─'*5} {'─'*5} {'─'*5} {'─'*4} "
          f"{'─'*5} {'─'*8} {'─'*7} {'─'*7}")

    for idx, r in enumerate(results_safe[:5]):
        print(
            f"{idx+1:3} {r['take_profit_pct']:5.1f} {r['entry_step_pct']:5.1f} "
            f"{r['position_size_pct']:5.1f} {r['max_entries']:4} "
            f"{r['leverage']:5} {r['roi']:+8.2f} "
            f"{r['max_balance_dd']:7.1f} {r['roi_dd_ratio']:7.2f}"
        )

    print(f"\n⏱️ Время оптимизации: {elapsed_total:.0f}с ({total} комбинаций)")

    # ── Сохранение в CSV ──
    output_dir = os.path.dirname(data_file) or "data"
    output_file = os.path.join(output_dir, "optimization_results.csv")

    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)

    print(f"📄 Все результаты сохранены: {output_file}")

    # ── Рекомендация для config.json ──
    print(f"\n{'='*60}")
    print(f"📋 РЕКОМЕНДОВАННЫЙ config.json")
    print(f"{'='*60}")
    print(f"""{{
  "trading": {{
    "symbol": "ETHUSDT",
    "leverage": {best['leverage']},
    "take_profit_pct": {best['take_profit_pct']},
    "max_entries": {best['max_entries']},
    "entry_step_pct": {best['entry_step_pct']},
    "position_size_pct": {best['position_size_pct']},
    "working_deposit": {deposit}
  }}
}}""")


def main():
    parser = argparse.ArgumentParser(
        description="🔬 Оптимизация параметров DCA-стратегии",
    )
    parser.add_argument("--data", required=True, help="CSV файл с данными")
    parser.add_argument("--deposit", type=float, default=1000, help="Начальный депозит ($)")
    parser.add_argument("--top", type=int, default=20, help="Показать N лучших")

    args = parser.parse_args()

    if not os.path.exists(args.data):
        print(f"❌ Файл не найден: {args.data}")
        sys.exit(1)

    run_optimization(args.data, args.deposit, args.top)


if __name__ == "__main__":
    main()
