---
description: Deploy bot changes to VPS and restart service
---

// turbo-all

## Деплой бота на VPS

1. Сохранить изменения в Git:
```
git add -A && git commit -m "update" && git push origin main
```

2. Копировать файлы на VPS:
```
scp src/trading/*.py root@176.32.37.184:/opt/crypto-bot/trading/
scp src/config.json root@176.32.37.184:/opt/crypto-bot/config.json
scp src/config.py root@176.32.37.184:/opt/crypto-bot/config.py
scp src/bot_engine.py root@176.32.37.184:/opt/crypto-bot/bot_engine.py
```

3. Перезапустить бота:
```
ssh root@176.32.37.184 "systemctl restart crypto-bot"
```

4. Проверить логи:
```
ssh root@176.32.37.184 "sleep 8 && tail -20 /opt/crypto-bot/logs/bot.log"
```
