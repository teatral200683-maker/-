# 📂 Файловая структура проекта — Бот Криптотрейдер

## Структура MVP

```
src/
├── main.py                     # Точка входа, CLI, запуск/остановка
├── config.py                   # Загрузка .env + config.json, валидация
├── bot_engine.py               # Оркестратор: основной цикл, координация модулей
│
├── exchange/                   # Слой интеграции с биржей
│   ├── __init__.py
│   ├── client.py               # Bybit REST API v5 (ордера, баланс, позиции)
│   └── websocket.py            # Bybit WebSocket (поток цен, события ордеров)
│
├── trading/                    # Бизнес-логика торговли
│   ├── __init__.py
│   ├── strategy.py             # Торговый алгоритм: анализ, сигналы входа
│   ├── position_manager.py     # Управление позициями: открытие, усреднение, закрытие
│   └── risk_manager.py         # Риск-менеджмент: ликвидация, объём, лимиты
│
├── notifications/              # Уведомления
│   ├── __init__.py
│   └── telegram.py             # Telegram Bot API: форматирование, отправка
│
├── storage/                    # Хранение данных
│   ├── __init__.py
│   ├── database.py             # SQLite: CRUD для сделок, статистика
│   └── models.py               # Модели данных: Trade, Entry, DailyStats
│
├── utils/                      # Утилиты
│   ├── __init__.py
│   └── logger.py               # Настройка логирования, ротация файлов
│
├── .env.example                # Шаблон переменных окружения
├── config.json                 # Параметры стратегии (дефолтные)
└── requirements.txt            # Python-зависимости
```

## Вспомогательные файлы (корень проекта)

```
Бот криптотрейдер/
├── README.md                   # Документация + инструкция по установке
├── .gitignore                  # Исключения для Git
├── .env.example                # Шаблон секретов (без значений)
│
├── logs/                       # Логи (создаётся автоматически)
│   └── bot.log                 # Основной лог бота
│
├── data/                       # Данные (создаётся автоматически)
│   └── trades.db               # SQLite база данных
│
└── tests/                      # Тесты
    ├── __init__.py
    ├── test_strategy.py        # Тесты торгового алгоритма
    ├── test_risk_manager.py    # Тесты риск-менеджмента
    ├── test_position_manager.py # Тесты управления позициями
    └── test_exchange_client.py # Тесты API-клиента (мок)
```

---

## Описание ключевых папок

| Папка | Назначение |
|---|---|
| `src/exchange/` | Всё взаимодействие с Bybit API. Остальные модули НЕ обращаются к API напрямую |
| `src/trading/` | Чистая бизнес-логика. Не знает про Telegram, не пишет в БД |
| `src/notifications/` | Только отправка уведомлений. Не принимает торговых решений |
| `src/storage/` | Только чтение/запись данных. Не зависит от биржи |
| `src/utils/` | Общие утилиты, которые используются во всех модулях |
| `tests/` | Тесты для каждого модуля |
| `logs/` | Автосоздаваемая папка для логов (в `.gitignore`) |
| `data/` | Автосоздаваемая папка для БД (в `.gitignore`) |

---

## Зависимости между модулями

```
main.py
  └── config.py           (загрузка конфигурации)
  └── bot_engine.py        (основной цикл)
        ├── exchange/client.py       (API-запросы)
        ├── exchange/websocket.py    (поток цен)
        ├── trading/strategy.py      (сигналы)
        ├── trading/position_manager.py (позиции)
        │     └── exchange/client.py (размещение ордеров)
        ├── trading/risk_manager.py  (проверки)
        │     └── exchange/client.py (баланс, ликвидация)
        ├── notifications/telegram.py (уведомления)
        ├── storage/database.py      (история)
        └── utils/logger.py          (логи)
```

> **Правило**: Модули `trading/` обращаются к `exchange/` для торговых операций. Модули `notifications/` и `storage/` вызываются только из `bot_engine.py`.
