# ── Crypto Trader Bot — Dockerfile ──────────────────
# Multi-stage build для минимального образа

# === Stage 1: Dependencies ===
FROM python:3.12-slim AS deps

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# === Stage 2: Production ===
FROM python:3.12-slim AS production

# Безопасность: non-root пользователь
RUN groupadd -g 1001 botgroup && \
    useradd -u 1001 -g botgroup -m -s /bin/bash botuser

WORKDIR /app

# Копируем зависимости из Stage 1
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# Копируем исходный код
COPY --chown=botuser:botgroup . .

# Создаём директории для данных и логов
RUN mkdir -p /app/data /app/logs && \
    chown -R botuser:botgroup /app/data /app/logs

# Переключаемся на non-root
USER botuser

# Health check: проверяем что процесс Python жив
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import sqlite3; conn=sqlite3.connect('/app/data/trades.db'); conn.close()" || exit 1

# Запуск бота
CMD ["python", "main.py", "start"]
