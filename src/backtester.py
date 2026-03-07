"""
Бэктестинг DCA-стратегии — Crypto Trader Bot

Симуляция торговой стратегии на исторических данных ETH/USDT.
Поддерживает загрузку CSV из Kaggle и генерацию отчётов.

Использование:
    python backtester.py --data data.csv --timeframe 1h
    python backtester.py --data data.csv --deposit 5000 --leverage 4
"""

import csv
import os
import sys
import argparse
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


# ══════════════════════════════════════════
# Модели данных для бэктестинга
# ══════════════════════════════════════════

@dataclass
class Candle:
    """Одна свеча (OHLCV)."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class BacktestEntry:
    """Один вход в позицию."""
    entry_number: int
    timestamp: datetime
    price: float
    qty: float


@dataclass
class BacktestTrade:
    """Один торговый цикл."""
    id: int
    opened_at: datetime
    closed_at: Optional[datetime] = None
    entries: List[BacktestEntry] = field(default_factory=list)
    avg_entry_price: float = 0.0
    total_qty: float = 0.0
    exit_price: Optional[float] = None
    pnl: float = 0.0
    commission: float = 0.0
    net_pnl: float = 0.0
    max_drawdown_pct: float = 0.0  # максимальная просадка внутри сделки

    def add_entry(self, price: float, qty: float, timestamp: datetime):
        entry = BacktestEntry(
            entry_number=len(self.entries) + 1,
            timestamp=timestamp,
            price=price,
            qty=qty,
        )
        self.entries.append(entry)
        total_cost = sum(e.price * e.qty for e in self.entries)
        self.total_qty = sum(e.qty for e in self.entries)
        self.avg_entry_price = total_cost / self.total_qty if self.total_qty > 0 else 0.0

    def close(self, exit_price: float, timestamp: datetime, commission_rate: float = 0.0006):
        self.exit_price = exit_price
        self.closed_at = timestamp
        self.pnl = (exit_price - self.avg_entry_price) * self.total_qty
        self.commission = (self.avg_entry_price * self.total_qty + exit_price * self.total_qty) * commission_rate
        self.net_pnl = self.pnl - self.commission

    @property
    def duration(self) -> str:
        if self.opened_at and self.closed_at:
            delta = self.closed_at - self.opened_at
            hours = int(delta.total_seconds() // 3600)
            mins = int((delta.total_seconds() % 3600) // 60)
            if hours >= 24:
                days = hours // 24
                hours = hours % 24
                return f"{days}д {hours}ч {mins}мин"
            return f"{hours}ч {mins}мин"
        return "—"


# ══════════════════════════════════════════
# Загрузчик данных
# ══════════════════════════════════════════

def load_csv(filepath: str) -> List[Candle]:
    """
    Загрузить OHLCV данные из CSV. Автоматически определяет формат.

    Поддерживаемые форматы колонок:
    - datetime/timestamp, open, high, low, close, volume
    - Unix timestamp (миллисекунды)
    """
    candles = []

    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        headers = [h.strip().lower() for h in reader.fieldnames]

        # Определяем имя колонки с временем
        time_col = None
        for candidate in ["datetime", "timestamp", "date", "time", "open_time", "open time"]:
            for h in reader.fieldnames:
                if h.strip().lower() == candidate:
                    time_col = h
                    break
            if time_col:
                break

        if not time_col:
            time_col = reader.fieldnames[0]  # первая колонка

        # Определяем колонки OHLCV
        def find_col(names):
            for n in names:
                for h in reader.fieldnames:
                    if h.strip().lower() == n:
                        return h
            return None

        open_col = find_col(["open", "open_price"])
        high_col = find_col(["high", "high_price"])
        low_col = find_col(["low", "low_price"])
        close_col = find_col(["close", "close_price"])
        vol_col = find_col(["volume", "vol", "quote_volume"])

        if not all([open_col, high_col, low_col, close_col]):
            print(f"❌ Не удалось определить колонки OHLCV в файле.")
            print(f"   Найденные заголовки: {reader.fieldnames}")
            return []

        for row in reader:
            try:
                # Парсинг времени
                raw_time = row[time_col].strip()
                ts = _parse_timestamp(raw_time)
                if ts is None:
                    continue

                candle = Candle(
                    timestamp=ts,
                    open=float(row[open_col]),
                    high=float(row[high_col]),
                    low=float(row[low_col]),
                    close=float(row[close_col]),
                    volume=float(row[vol_col]) if vol_col and row.get(vol_col) else 0.0,
                )
                candles.append(candle)
            except (ValueError, KeyError):
                continue

    candles.sort(key=lambda c: c.timestamp)
    print(f"✅ Загружено {len(candles):,} свечей из {os.path.basename(filepath)}")
    if candles:
        print(f"   Период: {candles[0].timestamp.strftime('%Y-%m-%d')} — {candles[-1].timestamp.strftime('%Y-%m-%d')}")
        print(f"   Первая цена: ${candles[0].close:,.2f}, Последняя: ${candles[-1].close:,.2f}")

    return candles


def _parse_timestamp(raw: str) -> Optional[datetime]:
    """Парсинг timestamp из разных форматов."""
    # Unix timestamp (секунды или миллисекунды)
    try:
        val = float(raw)
        if val > 1e12:  # миллисекунды
            return datetime.utcfromtimestamp(val / 1000)
        else:
            return datetime.utcfromtimestamp(val)
    except ValueError:
        pass

    # Строковые форматы
    for fmt in [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d",
        "%d.%m.%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
    ]:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue

    return None


# ══════════════════════════════════════════
# Бэктестер
# ══════════════════════════════════════════

@dataclass
class BacktestConfig:
    """Конфигурация бэктеста."""
    deposit: float = 1000.0         # Начальный депозит ($)
    leverage: int = 4               # Кредитное плечо
    take_profit_pct: float = 1.0    # Тейк-профит (%)
    max_entries: int = 5            # Макс. входов
    entry_step_pct: float = 2.0     # Шаг усреднения (%)
    position_size_pct: float = 5.0  # Размер входа (% от депозита)
    commission_rate: float = 0.0006 # Комиссия (0.06% Bybit taker)


class Backtester:
    """
    Симулятор DCA-стратегии на исторических данных.

    Логика:
    1. Цена падает на entry_step_pct% от локального макс → первый вход
    2. Цена падает ещё на entry_step_pct% от средней → усреднение
    3. Цена растёт до avg_price × (1 + tp%) → тейк-профит
    4. После закрытия → сброс, ждём новый сигнал
    """

    def __init__(self, config: BacktestConfig = None):
        self.cfg = config or BacktestConfig()

        # Состояние
        self.balance: float = self.cfg.deposit
        self.initial_deposit: float = self.cfg.deposit
        self.trades: List[BacktestTrade] = []
        self.current_trade: Optional[BacktestTrade] = None
        self.highest_price: float = 0.0
        self.trade_counter: int = 0

        # Статистика
        self.max_balance: float = self.cfg.deposit
        self.min_balance: float = self.cfg.deposit
        self.max_drawdown_pct: float = 0.0
        self.max_open_duration: str = "—"
        self.balance_history: List[tuple] = []  # (timestamp, balance)

    def run(self, candles: List[Candle]) -> dict:
        """
        Запуск бэктестинга.

        Args:
            candles: Список свечей OHLCV

        Returns:
            dict со статистикой
        """
        if not candles:
            print("❌ Нет данных для бэктестинга")
            return {}

        print(f"\n{'='*60}")
        print(f"🧪 ЗАПУСК БЭКТЕСТИНГА")
        print(f"{'='*60}")
        print(f"  Депозит:     ${self.cfg.deposit:,.2f}")
        print(f"  Плечо:       {self.cfg.leverage}x")
        print(f"  TP:          {self.cfg.take_profit_pct}%")
        print(f"  Макс.входов: {self.cfg.max_entries}")
        print(f"  Шаг усредн.: {self.cfg.entry_step_pct}%")
        print(f"  Свечей:      {len(candles):,}")
        print(f"{'='*60}\n")

        for i, candle in enumerate(candles):
            self._process_candle(candle)

            # Прогресс каждые 10%
            if i > 0 and i % (len(candles) // 10) == 0:
                pct = i / len(candles) * 100
                closed = len([t for t in self.trades if t.closed_at])
                print(f"  ▶ {pct:.0f}% | Баланс: ${self.balance:,.2f} | Закрыто сделок: {closed}")

        # Закрываем открытую позицию по последней цене
        if self.current_trade:
            last_price = candles[-1].close
            self.current_trade.close(last_price, candles[-1].timestamp, self.cfg.commission_rate)
            self.balance += self.current_trade.net_pnl
            self.trades.append(self.current_trade)
            self.current_trade = None

        return self._generate_report(candles)

    def _process_candle(self, candle: Candle):
        """Обработка одной свечи."""
        price = candle.close

        # Обновляем максимум
        if price > self.highest_price:
            self.highest_price = price

        # Записываем историю баланса
        self.balance_history.append((candle.timestamp, self.balance))

        if self.current_trade:
            # ── Есть открытая позиция ──

            # Обновляем макс. просадку внутри сделки
            dd = (self.current_trade.avg_entry_price - price) / self.current_trade.avg_entry_price * 100
            if dd > self.current_trade.max_drawdown_pct:
                self.current_trade.max_drawdown_pct = dd

            # Проверяем тейк-профит (по HIGH свечи для реалистичности)
            tp_price = self.current_trade.avg_entry_price * (1 + self.cfg.take_profit_pct / 100)
            if candle.high >= tp_price:
                # Закрываем по цене тейк-профита
                self.current_trade.close(tp_price, candle.timestamp, self.cfg.commission_rate)
                self.balance += self.current_trade.net_pnl
                self.trades.append(self.current_trade)

                # Обновляем статистику
                self.max_balance = max(self.max_balance, self.balance)
                self.min_balance = min(self.min_balance, self.balance)

                if self.max_balance > 0:
                    dd_pct = (self.max_balance - self.min_balance) / self.max_balance * 100
                    self.max_drawdown_pct = max(self.max_drawdown_pct, dd_pct)

                self.current_trade = None
                self.highest_price = price  # Сброс
                return

            # Проверяем усреднение (по LOW свечи)
            entries_count = len(self.current_trade.entries)
            if entries_count < self.cfg.max_entries:
                avg_price = self.current_trade.avg_entry_price
                threshold = avg_price * (1 - self.cfg.entry_step_pct / 100)

                if candle.low <= threshold:
                    qty = self._calc_qty(threshold)
                    if qty > 0:
                        self.current_trade.add_entry(threshold, qty, candle.timestamp)
        else:
            # ── Нет позиции — ищем сигнал на вход ──
            if self.highest_price > 0:
                drop_pct = (self.highest_price - price) / self.highest_price * 100
                if drop_pct >= self.cfg.entry_step_pct:
                    qty = self._calc_qty(price)
                    if qty > 0:
                        self.trade_counter += 1
                        self.current_trade = BacktestTrade(
                            id=self.trade_counter,
                            opened_at=candle.timestamp,
                        )
                        self.current_trade.add_entry(price, qty, candle.timestamp)
                        self.highest_price = 0  # Сброс для следующего цикла

    def _calc_qty(self, price: float) -> float:
        """Рассчитать объём входа."""
        entry_usd = self.balance * (self.cfg.position_size_pct / 100)
        qty = entry_usd / price  # Без учёта плеча для расчёта залога
        return round(qty, 4)

    def _generate_report(self, candles: List[Candle]) -> dict:
        """Генерация итогового отчёта."""
        closed_trades = [t for t in self.trades if t.closed_at]
        winning = [t for t in closed_trades if t.net_pnl > 0]
        losing = [t for t in closed_trades if t.net_pnl <= 0]

        total_pnl = sum(t.net_pnl for t in closed_trades)
        total_commission = sum(t.commission for t in closed_trades)
        total_gross = sum(t.pnl for t in closed_trades)

        avg_pnl = total_pnl / len(closed_trades) if closed_trades else 0
        avg_win = sum(t.net_pnl for t in winning) / len(winning) if winning else 0
        avg_loss = sum(t.net_pnl for t in losing) / len(losing) if losing else 0
        win_rate = len(winning) / len(closed_trades) * 100 if closed_trades else 0

        # Макс. кол-во входов
        max_entries_used = max((len(t.entries) for t in closed_trades), default=0)
        avg_entries = sum(len(t.entries) for t in closed_trades) / len(closed_trades) if closed_trades else 0

        # Длительности
        durations = []
        for t in closed_trades:
            if t.opened_at and t.closed_at:
                durations.append((t.closed_at - t.opened_at).total_seconds())

        avg_duration_h = (sum(durations) / len(durations) / 3600) if durations else 0
        max_duration_h = max(durations, default=0) / 3600
        min_duration_h = min(durations, default=0) / 3600

        # ROI
        roi = (self.balance - self.initial_deposit) / self.initial_deposit * 100

        # Период
        days = (candles[-1].timestamp - candles[0].timestamp).days if candles else 0
        trades_per_day = len(closed_trades) / days if days > 0 else 0
        daily_pnl = total_pnl / days if days > 0 else 0

        # Макс просадка в сделках
        max_trade_dd = max((t.max_drawdown_pct for t in closed_trades), default=0)

        report = {
            "period_days": days,
            "total_trades": len(closed_trades),
            "winning_trades": len(winning),
            "losing_trades": len(losing),
            "win_rate": win_rate,
            "total_pnl": total_pnl,
            "total_commission": total_commission,
            "total_gross": total_gross,
            "avg_pnl": avg_pnl,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "roi": roi,
            "initial_deposit": self.initial_deposit,
            "final_balance": self.balance,
            "daily_pnl": daily_pnl,
            "trades_per_day": trades_per_day,
            "max_entries_used": max_entries_used,
            "avg_entries": avg_entries,
            "avg_duration_h": avg_duration_h,
            "max_duration_h": max_duration_h,
            "min_duration_h": min_duration_h,
            "max_trade_drawdown": max_trade_dd,
            "max_balance_drawdown": self.max_drawdown_pct,
        }

        self._print_report(report, candles)
        return report

    def _print_report(self, report: dict, candles: List[Candle]):
        """Красивый вывод отчёта."""
        print(f"\n{'='*60}")
        print(f"📊 РЕЗУЛЬТАТЫ БЭКТЕСТИНГА")
        print(f"{'='*60}")

        print(f"\n📅 Период: {candles[0].timestamp.strftime('%d.%m.%Y')} — "
              f"{candles[-1].timestamp.strftime('%d.%m.%Y')} ({report['period_days']} дней)")

        print(f"\n💰 Финансовые результаты:")
        print(f"  ├─ Начальный депозит:  ${report['initial_deposit']:,.2f}")
        print(f"  ├─ Итоговый баланс:    ${report['final_balance']:,.2f}")
        sign = "+" if report['roi'] >= 0 else ""
        print(f"  ├─ ROI:                {sign}{report['roi']:.2f}%")
        print(f"  ├─ Общий PnL:          ${report['total_pnl']:+,.2f}")
        print(f"  ├─ Комиссии:           ${report['total_commission']:,.2f}")
        print(f"  └─ PnL/день:           ${report['daily_pnl']:+,.2f}")

        print(f"\n📈 Торговая статистика:")
        print(f"  ├─ Всего сделок:       {report['total_trades']}")
        print(f"  ├─ Прибыльных:         {report['winning_trades']} ({report['win_rate']:.1f}%)")
        print(f"  ├─ Убыточных:          {report['losing_trades']}")
        print(f"  ├─ Средний PnL:        ${report['avg_pnl']:+,.2f}")
        print(f"  ├─ Средний выигрыш:    ${report['avg_win']:+,.2f}")
        print(f"  ├─ Средний убыток:     ${report['avg_loss']:+,.2f}")
        print(f"  └─ Сделок/день:        {report['trades_per_day']:.1f}")

        print(f"\n🔄 Усреднение:")
        print(f"  ├─ Макс. входов:       {report['max_entries_used']}")
        print(f"  └─ Среднее входов:     {report['avg_entries']:.1f}")

        print(f"\n⏱️ Длительность сделок:")
        print(f"  ├─ Средняя:            {report['avg_duration_h']:.1f}ч")
        print(f"  ├─ Минимальная:        {report['min_duration_h']:.1f}ч")
        print(f"  └─ Максимальная:       {report['max_duration_h']:.1f}ч ({report['max_duration_h']/24:.1f} дней)")

        print(f"\n⚠️ Риски:")
        print(f"  ├─ Макс. просадка сделки:  {report['max_trade_drawdown']:.1f}%")
        print(f"  └─ Макс. просадка баланса: {report['max_balance_drawdown']:.1f}%")

        print(f"\n{'='*60}")

        # Оценка стратегии
        print(f"\n🏆 ОЦЕНКА СТРАТЕГИИ:")
        if report['win_rate'] >= 95:
            print(f"  ✅ Винрейт {report['win_rate']:.1f}% — отлично!")
        elif report['win_rate'] >= 80:
            print(f"  ⚠️ Винрейт {report['win_rate']:.1f}% — хорошо, но есть убыточные сделки")
        else:
            print(f"  ❌ Винрейт {report['win_rate']:.1f}% — стратегия требует доработки")

        if report['roi'] > 0:
            monthly_roi = report['roi'] / max(report['period_days'] / 30, 1)
            print(f"  💹 Месячная доходность: ~{monthly_roi:.1f}%")

        if report['max_duration_h'] > 720:  # > 30 дней
            print(f"  ⚠️ Макс. сделка длилась {report['max_duration_h']/24:.0f} дней — долгое удержание!")

        if report['max_entries_used'] >= 5:
            print(f"  ⚠️ Использовались все 5 входов — были сильные просадки")

        print()

    def save_report_csv(self, filepath: str):
        """Сохранить список сделок в CSV."""
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "ID", "Открытие", "Закрытие", "Входов",
                "Средняя цена", "Цена выхода", "Количество",
                "PnL", "Комиссия", "Чистый PnL", "Просадка %", "Длительность"
            ])
            for t in self.trades:
                writer.writerow([
                    t.id,
                    t.opened_at.strftime("%Y-%m-%d %H:%M") if t.opened_at else "",
                    t.closed_at.strftime("%Y-%m-%d %H:%M") if t.closed_at else "",
                    len(t.entries),
                    f"{t.avg_entry_price:.2f}",
                    f"{t.exit_price:.2f}" if t.exit_price else "",
                    f"{t.total_qty:.4f}",
                    f"{t.pnl:.2f}",
                    f"{t.commission:.2f}",
                    f"{t.net_pnl:.2f}",
                    f"{t.max_drawdown_pct:.1f}",
                    t.duration,
                ])
        print(f"📄 Отчёт сохранён: {filepath}")

    def save_balance_csv(self, filepath: str):
        """Сохранить историю баланса в CSV (для графиков)."""
        # Сэмплируем — каждую 100-ю точку, чтобы файл не был огромным
        step = max(1, len(self.balance_history) // 5000)
        sampled = self.balance_history[::step]

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "balance"])
            for ts, bal in sampled:
                writer.writerow([ts.strftime("%Y-%m-%d %H:%M"), f"{bal:.2f}"])
        print(f"📈 История баланса сохранена: {filepath}")


# ══════════════════════════════════════════
# CLI
# ══════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="🧪 Бэктестинг DCA-стратегии на исторических данных ETH/USDT",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  python backtester.py --data eth_1h.csv
  python backtester.py --data eth_1h.csv --deposit 5000 --leverage 4
  python backtester.py --data eth_1h.csv --tp 1.5 --step 3.0 --entries 3
        """,
    )
    parser.add_argument("--data", required=True, help="Путь к CSV файлу с OHLCV данными")
    parser.add_argument("--deposit", type=float, default=1000, help="Начальный депозит ($)")
    parser.add_argument("--leverage", type=int, default=4, help="Кредитное плечо")
    parser.add_argument("--tp", type=float, default=1.0, help="Тейк-профит (%%)")
    parser.add_argument("--entries", type=int, default=5, help="Макс. входов")
    parser.add_argument("--step", type=float, default=2.0, help="Шаг усреднения (%%)")
    parser.add_argument("--size", type=float, default=5.0, help="Размер входа (%% от депозита)")
    parser.add_argument("--output", default=None, help="Сохранить отчёт в CSV")

    args = parser.parse_args()

    if not os.path.exists(args.data):
        print(f"❌ Файл не найден: {args.data}")
        sys.exit(1)

    # Загрузка данных
    candles = load_csv(args.data)
    if not candles:
        sys.exit(1)

    # Конфигурация
    config = BacktestConfig(
        deposit=args.deposit,
        leverage=args.leverage,
        take_profit_pct=args.tp,
        max_entries=args.entries,
        entry_step_pct=args.step,
        position_size_pct=args.size,
    )

    # Запуск
    bt = Backtester(config)
    bt.run(candles)

    # Сохранение
    if args.output:
        bt.save_report_csv(args.output)
    else:
        output_dir = os.path.dirname(args.data) or "."
        base = os.path.splitext(os.path.basename(args.data))[0]
        bt.save_report_csv(os.path.join(output_dir, f"{base}_trades.csv"))
        bt.save_balance_csv(os.path.join(output_dir, f"{base}_balance.csv"))


if __name__ == "__main__":
    main()
