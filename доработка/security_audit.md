# 🔒 Security Audit — Crypto Trader Bot

> **Дата аудита:** 15.03.2026  
> **Среда:** MAINNET (реальные деньги)  
> **VPS:** 176.32.37.184 (Ubuntu, systemd)

---

## 🟢 Что хорошо

| # | Проверка | Статус |
|---|---|---|
| ✅ | `.env` НЕ попала в git-историю | Безопасно |
| ✅ | `.gitignore` включает `.env` | Настроено |
| ✅ | Нет хардкод-секретов в Python-коде | Чисто |
| ✅ | API-ключи загружаются из `.env` через `os.environ` | Правильно |
| ✅ | Bybit TESTNET=false на VPS | Корректно |
| ✅ | Bot Token и Chat ID разделены | OK |

---

## 🔴 Критичное — ИСПРАВЛЕНО АВТОМАТИЧЕСКИ

### 1. `.env` была world-readable (644)
```
БЫЛО:   -rw-r--r-- (все могут читать API-ключи!)
СТАЛО:  -rw------- (только root)
```
✅ **ИСПРАВЛЕНО** — `chmod 600 /opt/crypto-bot/.env`

### 2. UFW firewall был отключён
```
БЫЛО:   Status: inactive (все порты открыты!)
СТАЛО:  Status: active, SSH (22/tcp) only
```
✅ **ИСПРАВЛЕНО** — `ufw allow 22/tcp; ufw --force enable`

---

## 🟡 Важное — Рекомендуется исправить вручную

### 3. SSH root login с паролем
```
PermitRootLogin yes  ← ОПАСНО
```
**Рекомендация:** После настройки SSH-ключа:
```bash
# На VPS:
sed -i 's/PermitRootLogin yes/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
systemctl restart sshd
```

### 4. Бот работает под root
```
[Service]
# Нет User= → работает под root
ExecStart=/opt/crypto-bot/venv/bin/python main.py start
```
**Рекомендация:** Создать отдельного пользователя:
```bash
useradd -r -s /bin/false botuser
chown -R botuser:botuser /opt/crypto-bot
# Добавить в crypto-bot.service:
# User=botuser
# Group=botuser
```

### 5. nginx на порт 80 (не используется ботом)
```
LISTEN 0.0.0.0:80  nginx
```
**Рекомендация:** Если nginx не нужен:
```bash
systemctl stop nginx
systemctl disable nginx
```

### 6. API-ключ Bybit — проверить права
**Рекомендация:** В Bybit → API Management убедиться:
- ☑ Contract Trading — включено
- ☐ Withdraw — **ВЫКЛЮЧЕНО** (критично!)
- ☑ IP Restriction — Добавить IP VPS: `176.32.37.184`

### 7. Нет бэкапа trades.db
```
/opt/crypto-bot/data/trades.db — 136KB
/opt/crypto-bot/data/trades.db.testnet.bak — есть (старый бэкап)
```
**Рекомендация:** Настроить cron-бэкап:
```bash
crontab -e
# Добавить:
0 */6 * * * cp /opt/crypto-bot/data/trades.db /opt/crypto-bot/data/trades.db.bak
```

---

## 📊 Итоговая оценка

| Категория | До аудита | После |
|---|---|---|
| Секреты и .env | 🔴 Критично | ✅ Исправлено |
| Файрвол | 🔴 Отключён | ✅ Активен |
| SSH | 🟡 Root+пароль | 🟡 Рекомендация |
| Процесс | 🟡 Root | 🟡 Рекомендация |
| Код | ✅ Чисто | ✅ Чисто |
| Git | ✅ Безопасно | ✅ Безопасно |
| Бэкап | 🟡 Нет | 🟡 Рекомендация |

**Общая оценка: 7/10** (до аудита: 4/10)
