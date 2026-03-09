# 📦 Руководство по деплою — Crypto Trader Bot

## Вариант 1: Docker (рекомендуется)

### Требования
- VPS/VDS сервер (Ubuntu 22.04+, 1 vCPU, 512MB RAM, $5/мес)
- Docker + Docker Compose

### Установка

```bash
# 1. Клонируем проект
git clone <repo-url> crypto-bot
cd crypto-bot/src

# 2. Создаём .env файл
cp .env.example .env
nano .env  # Вводим API-ключи

# 3. Запускаем
docker compose up -d

# 4. Проверяем логи
docker compose logs -f
```

### Управление

```bash
docker compose up -d       # Запуск
docker compose down        # Остановка
docker compose restart     # Перезапуск
docker compose logs -f     # Логи в реальном времени
docker compose ps          # Статус контейнеров
```

### Обновление

```bash
git pull
docker compose build
docker compose up -d
```

---

## Вариант 2: Без Docker

### Требования
- Python 3.11+
- pip / venv

### Установка

```bash
# 1. Клонируем и настраиваем
git clone <repo-url> crypto-bot
cd crypto-bot/src
python -m venv venv
source venv/bin/activate      # Linux
# venv\Scripts\activate       # Windows

# 2. Зависимости
pip install -r requirements.txt

# 3. Конфигурация
cp .env.example .env
nano .env

# 4. Запуск
python main.py start
```

### Запуск как сервис (systemd)

```bash
sudo nano /etc/systemd/system/crypto-bot.service
```

```ini
[Unit]
Description=Crypto Trader Bot
After=network.target

[Service]
Type=simple
User=botuser
WorkingDirectory=/home/botuser/crypto-bot/src
ExecStart=/home/botuser/crypto-bot/src/venv/bin/python main.py start
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable crypto-bot
sudo systemctl start crypto-bot
sudo systemctl status crypto-bot
```

---

## Безопасность

| Правило | Описание |
|---|---|
| `.env` НЕ в образе | Монтируется через volumes |
| API без вывода | Ключ только на торговлю |
| Non-root | Контейнер работает от пользователя `botuser` |
| Только LONG | Шорт запрещён на уровне кода |
| Стоп-лосс | -5% от средней цены → автозакрытие |

## Telegram-команды
- `/status` — текущая позиция и баланс
- `/stop` — остановка бота
- `/help` — справка

## CLI-команды
```bash
python main.py start         # Запуск бота
python main.py status        # Статус
python main.py stats         # Статистика сделок
python main.py check-config  # Проверка конфигурации
```
