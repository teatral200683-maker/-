"""
SQLite база данных — Crypto Trader Bot

CRUD-операции для сделок, входов и статистики.
Автоматическое создание таблиц при первом запуске.
"""

import sqlite3
import os
from datetime import datetime, date, timezone
from typing import Optional, List

from storage.models import Trade, Entry, DailyStats
from utils.logger import get_logger

logger = get_logger("database")


class Database:
    """
    SQLite хранилище для истории сделок и состояния бота.
    """

    def __init__(self, db_path: str = "data/trades.db"):
        """
        Инициализация БД.

        Args:
            db_path: Путь к файлу SQLite
        """
        # Создаём директорию
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()
        logger.info(f"✅ База данных подключена: {db_path}")

    def _create_tables(self):
        """Создание таблиц, если они не существуют."""
        cursor = self.conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                opened_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                closed_at       DATETIME,
                symbol          TEXT NOT NULL DEFAULT 'ETHUSDT',
                side            TEXT NOT NULL DEFAULT 'Buy',
                status          TEXT NOT NULL DEFAULT 'open',
                entries_count   INTEGER NOT NULL DEFAULT 1,
                avg_entry_price REAL NOT NULL,
                exit_price      REAL,
                total_qty       REAL NOT NULL,
                leverage        INTEGER NOT NULL DEFAULT 4,
                pnl             REAL,
                commission      REAL DEFAULT 0,
                net_pnl         REAL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS entries (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id        INTEGER NOT NULL,
                entry_number    INTEGER NOT NULL,
                timestamp       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                price           REAL NOT NULL,
                qty             REAL NOT NULL,
                order_id        TEXT,
                FOREIGN KEY (trade_id) REFERENCES trades(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_stats (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                date                DATE NOT NULL UNIQUE,
                trades_closed       INTEGER DEFAULT 0,
                total_pnl           REAL DEFAULT 0,
                total_commission    REAL DEFAULT 0,
                balance             REAL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bot_state (
                key         TEXT PRIMARY KEY,
                value       TEXT,
                updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Индексы
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_opened ON trades(opened_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_entries_trade ON entries(trade_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_daily_date ON daily_stats(date)")

        self.conn.commit()
        logger.debug("Таблицы БД созданы/проверены")

    # ── Сделки (trades) ──────────────────────────

    def create_trade(self, trade: Trade) -> int:
        """Создать новую сделку. Возвращает ID."""
        cursor = self.conn.cursor()
        cursor.execute(
            """INSERT INTO trades (opened_at, symbol, side, status, entries_count,
               avg_entry_price, total_qty, leverage)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                trade.opened_at.isoformat(),
                trade.symbol,
                trade.side,
                trade.status,
                trade.entries_count,
                trade.avg_entry_price,
                trade.total_qty,
                trade.leverage,
            ),
        )
        self.conn.commit()
        trade_id = cursor.lastrowid
        logger.info(f"Сделка #{trade_id} создана")
        return trade_id

    def update_trade(self, trade: Trade):
        """Обновить существующую сделку."""
        cursor = self.conn.cursor()
        cursor.execute(
            """UPDATE trades SET
               closed_at=?, status=?, entries_count=?, avg_entry_price=?,
               exit_price=?, total_qty=?, pnl=?, commission=?, net_pnl=?
               WHERE id=?""",
            (
                trade.closed_at.isoformat() if trade.closed_at else None,
                trade.status,
                trade.entries_count,
                trade.avg_entry_price,
                trade.exit_price,
                trade.total_qty,
                trade.pnl,
                trade.commission,
                trade.net_pnl,
                trade.id,
            ),
        )
        self.conn.commit()
        logger.debug(f"Сделка #{trade.id} обновлена")

    def get_open_trade(self) -> Optional[Trade]:
        """Получить текущую открытую сделку (если есть)."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM trades WHERE status='open' LIMIT 1")
        row = cursor.fetchone()
        if row:
            trade = self._row_to_trade(row)
            # Загружаем входы
            trade.entries = self.get_entries(trade.id)
            return trade
        return None

    def get_trade_by_id(self, trade_id: int) -> Optional[Trade]:
        """Получить сделку по ID."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM trades WHERE id=?", (trade_id,))
        row = cursor.fetchone()
        if row:
            trade = self._row_to_trade(row)
            trade.entries = self.get_entries(trade.id)
            return trade
        return None

    def get_closed_trades(self, limit: int = 50) -> List[Trade]:
        """Получить последние закрытые сделки."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM trades WHERE status='closed' ORDER BY closed_at DESC LIMIT ?",
            (limit,),
        )
        return [self._row_to_trade(row) for row in cursor.fetchall()]

    # ── Входы (entries) ──────────────────────────

    def create_entry(self, entry: Entry) -> int:
        """Создать запись о входе. Возвращает ID."""
        cursor = self.conn.cursor()
        cursor.execute(
            """INSERT INTO entries (trade_id, entry_number, timestamp, price, qty, order_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                entry.trade_id,
                entry.entry_number,
                entry.timestamp.isoformat(),
                entry.price,
                entry.qty,
                entry.order_id,
            ),
        )
        self.conn.commit()
        entry_id = cursor.lastrowid
        logger.debug(f"Вход #{entry.entry_number} для сделки #{entry.trade_id} записан")
        return entry_id

    def get_entries(self, trade_id: int) -> List[Entry]:
        """Получить все входы для сделки."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM entries WHERE trade_id=? ORDER BY entry_number",
            (trade_id,),
        )
        return [self._row_to_entry(row) for row in cursor.fetchall()]

    # ── Статистика ────────────────────────────────

    def save_daily_stats(self, stats: DailyStats):
        """Сохранить/обновить дневную статистику."""
        cursor = self.conn.cursor()
        cursor.execute(
            """INSERT OR REPLACE INTO daily_stats (date, trades_closed, total_pnl, total_commission, balance)
               VALUES (?, ?, ?, ?, ?)""",
            (stats.date, stats.trades_closed, stats.total_pnl, stats.total_commission, stats.balance),
        )
        self.conn.commit()

    def get_daily_stats(self, days: int = 30) -> List[DailyStats]:
        """Получить статистику за последние N дней."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM daily_stats ORDER BY date DESC LIMIT ?", (days,)
        )
        results = []
        for row in cursor.fetchall():
            results.append(DailyStats(
                id=row["id"], date=row["date"],
                trades_closed=row["trades_closed"],
                total_pnl=row["total_pnl"],
                total_commission=row["total_commission"],
                balance=row["balance"],
            ))
        return results

    def get_total_stats(self) -> dict:
        """Общая статистика по всем сделкам."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT
                COUNT(*) AS total_trades,
                SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END) AS winning,
                SUM(net_pnl) AS total_profit,
                AVG(net_pnl) AS avg_profit
            FROM trades WHERE status='closed'
        """)
        row = cursor.fetchone()
        total = row["total_trades"] or 0
        return {
            "total_trades": total,
            "winning_trades": row["winning"] or 0,
            "win_rate": (row["winning"] / total * 100) if total > 0 else 0,
            "total_profit": row["total_profit"] or 0,
            "avg_profit": row["avg_profit"] or 0,
        }

    # ── Состояние бота ────────────────────────────

    def save_state(self, key: str, value: str):
        """Сохранить параметр состояния бота."""
        cursor = self.conn.cursor()
        cursor.execute(
            """INSERT OR REPLACE INTO bot_state (key, value, updated_at)
               VALUES (?, ?, ?)""",
            (key, value, datetime.now(timezone.utc).isoformat()),
        )
        self.conn.commit()

    def get_state(self, key: str) -> Optional[str]:
        """Получить параметр состояния бота."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT value FROM bot_state WHERE key=?", (key,))
        row = cursor.fetchone()
        return row["value"] if row else None

    # ── Утилиты ───────────────────────────────────

    def _row_to_trade(self, row) -> Trade:
        """Конвертировать строку БД в объект Trade."""
        return Trade(
            id=row["id"],
            opened_at=datetime.fromisoformat(row["opened_at"]),
            closed_at=datetime.fromisoformat(row["closed_at"]) if row["closed_at"] else None,
            symbol=row["symbol"],
            side=row["side"],
            status=row["status"],
            entries_count=row["entries_count"],
            avg_entry_price=row["avg_entry_price"],
            exit_price=row["exit_price"],
            total_qty=row["total_qty"],
            leverage=row["leverage"],
            pnl=row["pnl"],
            commission=row["commission"] or 0,
            net_pnl=row["net_pnl"],
        )

    def _row_to_entry(self, row) -> Entry:
        """Конвертировать строку БД в объект Entry."""
        return Entry(
            id=row["id"],
            trade_id=row["trade_id"],
            entry_number=row["entry_number"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            price=row["price"],
            qty=row["qty"],
            order_id=row["order_id"] or "",
        )

    def close(self):
        """Закрыть соединение с БД."""
        self.conn.close()
        logger.info("База данных закрыта")
