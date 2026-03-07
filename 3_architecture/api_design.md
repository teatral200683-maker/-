# 🔌 API Design — Бот Криптотрейдер

## Используемые API

---

## 1. Bybit REST API v5

**Базовый URL**:
- Mainnet: `https://api.bybit.com`
- Testnet: `https://api-testnet.bybit.com`

### 1.1 Аккаунт и баланс

#### Получить баланс кошелька
```
GET /v5/account/wallet-balance
Params: accountType=UNIFIED
```
**Используется для**: Проверка баланса перед входом в позицию, расчёт макс. объёма.

**Ключевые поля ответа**:
- `totalEquity` — общий баланс
- `totalAvailableBalance` — доступный баланс
- `coin[].walletBalance` — баланс по монете

---

#### Получить информацию об API-ключе
```
GET /v5/user/query-api
```
**Используется для**: Проверка прав API-ключа при старте (нет ли прав на вывод).

**Проверяем поля**:
- `permissions.ContractTrade` — должно содержать "Order", "Position"
- `permissions.Withdraw` — должно быть ПУСТЫМ

---

### 1.2 Позиции

#### Получить список позиций
```
GET /v5/position/list
Params: category=linear, symbol=ETHUSDT
```
**Используется для**: Проверка открытых позиций при старте, синхронизация.

**Ключевые поля**:
- `side` — Buy / Sell
- `size` — объём позиции
- `avgPrice` — средняя цена входа
- `liqPrice` — цена ликвидации (должна быть пустой!)
- `unrealisedPnl` — нереализованный PnL

---

#### Установить плечо
```
POST /v5/position/set-leverage
Body: { category: "linear", symbol: "ETHUSDT", buyLeverage: "4", sellLeverage: "4" }
```
**Используется для**: Установка плеча 4x при старте бота.

---

### 1.3 Ордера

#### Разместить ордер (вход в позицию)
```
POST /v5/order/create
Body: {
  category: "linear",
  symbol: "ETHUSDT",
  side: "Buy",         ← ВСЕГДА Buy (только лонг!)
  orderType: "Market",
  qty: "0.5",
  timeInForce: "GTC"
}
```

#### Разместить ордер (тейк-профит / закрытие)
```
POST /v5/order/create
Body: {
  category: "linear",
  symbol: "ETHUSDT",
  side: "Sell",
  orderType: "Market",
  qty: "0.5",
  reduceOnly: true      ← ВАЖНО: только закрытие, не шорт!
  timeInForce: "GTC"
}
```

#### Отменить ордер
```
POST /v5/order/cancel
Body: { category: "linear", symbol: "ETHUSDT", orderId: "..." }
```

---

## 2. Bybit WebSocket

**URL**:
- Mainnet: `wss://stream.bybit.com/v5/public/linear`
- Mainnet (private): `wss://stream.bybit.com/v5/private`
- Testnet: `wss://stream-testnet.bybit.com/v5/public/linear`

### 2.1 Публичные каналы

#### Тикер (цена в реальном времени)
```json
{
  "op": "subscribe",
  "args": ["tickers.ETHUSDT"]
}
```
**Ответ** (поток):
```json
{
  "topic": "tickers.ETHUSDT",
  "data": {
    "lastPrice": "2450.30",
    "prevPrice24h": "2400.00",
    "price24hPcnt": "0.0209",
    "highPrice24h": "2470.00",
    "lowPrice24h": "2390.00",
    "turnover24h": "128456789.50",
    "volume24h": "52345.678"
  }
}
```

#### Свечи (для индикатора)
```json
{
  "op": "subscribe",
  "args": ["kline.1.ETHUSDT"]
}
```

### 2.2 Приватные каналы

#### Обновления позиций
```json
{
  "op": "subscribe",
  "args": ["position"]
}
```
**Ответ**: Изменения в позициях (автоматическое обновление при исполнении ордера).

#### Обновления ордеров
```json
{
  "op": "subscribe",
  "args": ["order"]
}
```
**Ответ**: Статус ордеров (New → Filled / Cancelled / Rejected).

---

## 3. Telegram Bot API

**Базовый URL**: `https://api.telegram.org/bot<TOKEN>`

### Отправить сообщение
```
POST /sendMessage
Body: {
  chat_id: "123456789",
  text: "🟢 ВХОД #1/5\nМонета: ETH/USDT\nЦена: $2,450.30",
  parse_mode: "HTML"
}
```

### Форматы сообщений

| Событие | Эмодзи | Пример |
|---|---|---|
| Бот запущен | ✅ | «Бот запущен. Баланс: $5,000» |
| Вход в позицию | 🟢 | «ВХОД #2/5. Цена: $2,450» |
| Сделка закрыта | 💰 | «PnL: +$46.40» |
| Макс. входов | ⚠️ | «Достигнут максимум 5/5 входов» |
| Ошибка | 🔴 | «Разрыв WebSocket. Реконнект 3/10» |
| Дневная сводка | 📊 | «Сделок: 3, PnL: +$125.50» |
| Бот остановлен | 🛑 | «Бот остановлен вручную» |

---

## 4. Ограничения API

| API | Лимит | Наше использование |
|---|---|---|
| Bybit REST | 120 запросов/мин | ~10–20 запросов/мин (достаточно) |
| Bybit WebSocket | 200 подписок | 3–4 подписки (достаточно) |
| Telegram | 30 сообщений/сек | 1–5 сообщений/час (достаточно) |
