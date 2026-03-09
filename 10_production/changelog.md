# 📝 Changelog — Crypto Trader Bot

## v1.1 (09.03.2026)
### Added
- **Стоп-лосс** `-5%` — автозакрытие при убытке ≥ stop_loss_pct% от средней
- Метод `should_stop_loss()` в `position_manager.py`
- Параметр `stop_loss_pct` в `config.py` и `config.json`
- Лог `🛡️ Стоп-лосс: X%` при старте

### Changed
- Приоритет проверок: TP → SL → DCA (был TP → DCA)
- Версия бота в баннере: v1.0 → v1.1

### Fixed
- `NameError: config` → `self.config` в `bot_engine.py`

---

## v1.0 (07.03.2026)
### Added
- Полный торговый движок: DCA-стратегия, 5 входов, усреднение
- Bybit REST API v5 + WebSocket (реалтайм)
- Telegram-уведомления (7 типов)
- Telegram-команды (`/status`, `/stop`, `/help`)
- SQLite база данных (сделки, статистика)
- CLI: `start`, `status`, `stats`, `check-config`
- Graceful shutdown (Ctrl+C)
- Бэктестинг на 2 датасетах (4 года 1H + 2 года 15M)
- Оптимизатор параметров

### Fixed
- `.env` encoding (UTF-16 → UTF-8)
- `recv_window=20000` для синхронизации времени
- Retry 30208 (3 попытки с задержкой)

---

## v0.1 (06.03.2026)
- Начальная структура проекта
- Конфигурация (.env + config.json)
- Логирование (файл + консоль)
