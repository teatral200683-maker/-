# 📖 Руководство пользователя — Crypto Trader Bot v1.1

## Что делает бот
Автоматически торгует ETH/USDT на бирже Bybit:
- Покупает ETH когда цена растёт (лонг)
- При падении цены — усредняет позицию (до 5 входов)
- Закрывает с прибылью при +1% от средней цены
- Защита: стоп-лосс при -5% от средней цены

## Быстрый старт

### 1. Создать API-ключ на Bybit
- [bybit.com](https://bybit.com) → API Management → Create New Key
- ✅ Contract Trade (USDT Perp) → Read/Write
- ❌ Withdraw — **НЕ включать!**

### 2. Создать Telegram-бота
- Написать [@BotFather](https://t.me/BotFather) → `/newbot`
- Сохранить токен бота
- Узнать свой chat_id: [@userinfobot](https://t.me/userinfobot)

### 3. Настроить `.env`
```
BYBIT_API_KEY=ваш_ключ
BYBIT_API_SECRET=ваш_секрет
BYBIT_TESTNET=true
TELEGRAM_BOT_TOKEN=токен_бота
TELEGRAM_CHAT_ID=ваш_chat_id
```

### 4. Запустить
```bash
# Docker
docker compose up -d

# Или без Docker
python main.py start
```

## Управление

### Telegram
| Команда | Описание |
|---|---|
| `/status` | Текущий баланс и позиция |
| `/stop` | Остановить бота |
| `/help` | Список команд |

### Терминал
```bash
python main.py start          # Запустить
python main.py status         # Статус
python main.py stats          # Статистика
python main.py check-config   # Проверка конфига
```

## Настройки (config.json)

| Параметр | По умолчанию | Описание |
|---|---|---|
| `take_profit_pct` | 1.0 | Тейк-профит в % |
| `stop_loss_pct` | 5.0 | Стоп-лосс в % |
| `max_entries` | 5 | Макс. входов (усреднение) |
| `entry_step_pct` | 2.0 | Шаг усреднения в % |
| `leverage` | 4 | Кредитное плечо |
| `working_deposit` | 1000 | Рабочий депозит ($) |

## Безопасность
- 🔒 API-ключ только на торговлю (без вывода)
- 🔒 Только LONG-сделки (шорт запрещён в коде)
- 🔒 Стоп-лосс: -5% автозакрытие
- 🔒 Контроль ликвидации перед каждым входом
