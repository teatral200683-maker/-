# 🗃️ Схема базы данных — Бот Криптотрейдер

## СУБД: SQLite
**Обоснование**: Не требует отдельного сервера, достаточна для MVP, файл `data/trades.db`.

---

## ER-диаграмма

```
┌──────────────────────┐       ┌──────────────────────┐
│       trades          │       │       entries         │
├──────────────────────┤       ├──────────────────────┤
│ id (PK)              │──┐    │ id (PK)              │
│ opened_at            │  │    │ trade_id (FK) ───────│──┐
│ closed_at            │  │    │ entry_number          │  │
│ symbol               │  │    │ timestamp             │  │
│ side                 │  │    │ price                 │  │
│ status               │  │    │ qty                   │  │
│ entries_count        │  └───►│ order_id              │  │
│ avg_entry_price      │       └──────────────────────┘  │
│ exit_price           │                                  │
│ total_qty            │       ┌──────────────────────┐  │
│ leverage             │       │    daily_stats        │  │
│ pnl                  │       ├──────────────────────┤  │
│ commission           │       │ id (PK)              │  │
│ net_pnl              │       │ date (UNIQUE)        │  │
└──────────────────────┘       │ trades_closed        │  │
                                │ total_pnl            │  │
┌──────────────────────┐       │ total_commission     │  │
│     bot_state         │       │ balance              │  │
├──────────────────────┤       └──────────────────────┘  │
│ key (PK)             │                                  │
│ value (JSON)         │                                  │
│ updated_at           │                                  │
└──────────────────────┘                                  │
                                                          │
                        Связь: entries.trade_id → trades.id
```

---

## Таблицы

### 1. `trades` — История сделок (циклов)

Одна запись = один полный торговый цикл (от первого входа до закрытия).

```sql
CREATE TABLE trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    opened_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    closed_at       DATETIME,
    symbol          TEXT NOT NULL DEFAULT 'ETHUSDT',
    side            TEXT NOT NULL DEFAULT 'Buy',
    status          TEXT NOT NULL DEFAULT 'open',   -- open | closed
    entries_count   INTEGER NOT NULL DEFAULT 1,
    avg_entry_price REAL NOT NULL,
    exit_price      REAL,
    total_qty       REAL NOT NULL,
    leverage        INTEGER NOT NULL DEFAULT 4,
    pnl             REAL,
    commission      REAL DEFAULT 0,
    net_pnl         REAL
);
```

### 2. `entries` — Отдельные входы в позицию

Каждый вход (усреднение) — отдельная запись. Привязана к `trades`.

```sql
CREATE TABLE entries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id        INTEGER NOT NULL,
    entry_number    INTEGER NOT NULL,         -- 1, 2, 3, 4, 5
    timestamp       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    price           REAL NOT NULL,
    qty             REAL NOT NULL,
    order_id        TEXT,                      -- ID ордера на бирже
    FOREIGN KEY (trade_id) REFERENCES trades(id)
);
```

### 3. `daily_stats` — Дневная статистика

Одна запись на каждый день. Заполняется при формировании ежедневной сводки.

```sql
CREATE TABLE daily_stats (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    date                DATE NOT NULL UNIQUE,
    trades_closed       INTEGER DEFAULT 0,
    total_pnl           REAL DEFAULT 0,
    total_commission    REAL DEFAULT 0,
    balance             REAL
);
```

### 4. `bot_state` — Состояние бота

Хранит текущее состояние для восстановления после перезапуска.

```sql
CREATE TABLE bot_state (
    key         TEXT PRIMARY KEY,
    value       TEXT,                          -- JSON
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

**Примеры записей**:
| key | value |
|---|---|
| `current_trade_id` | `42` |
| `last_entry_number` | `3` |
| `is_position_open` | `true` |
| `bot_started_at` | `"2026-03-04T15:00:00"` |

---

## Индексы

```sql
CREATE INDEX idx_trades_status ON trades(status);
CREATE INDEX idx_trades_opened_at ON trades(opened_at);
CREATE INDEX idx_entries_trade_id ON entries(trade_id);
CREATE INDEX idx_daily_stats_date ON daily_stats(date);
```

---

## Типовые запросы

### Получить текущую открытую сделку
```sql
SELECT * FROM trades WHERE status = 'open' LIMIT 1;
```

### Получить все входы для сделки
```sql
SELECT * FROM entries WHERE trade_id = ? ORDER BY entry_number;
```

### Расчёт средней цены входа
```sql
SELECT SUM(price * qty) / SUM(qty) AS avg_price
FROM entries WHERE trade_id = ?;
```

### Статистика за период
```sql
SELECT 
    COUNT(*) AS total_trades,
    SUM(net_pnl) AS total_profit,
    AVG(net_pnl) AS avg_profit,
    MIN(net_pnl) AS min_profit,
    MAX(net_pnl) AS max_profit
FROM trades 
WHERE status = 'closed' 
  AND closed_at BETWEEN ? AND ?;
```

### Дневная доходность
```sql
SELECT date, total_pnl, balance
FROM daily_stats
ORDER BY date DESC
LIMIT 30;
```
