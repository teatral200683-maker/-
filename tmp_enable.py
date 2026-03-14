import sqlite3
import shutil

db_path = "/opt/crypto-bot/data/trades.db"
shutil.copy(db_path, db_path + ".testnet.bak")

c = sqlite3.connect(db_path)
# Close any open testnet trades
r1 = c.execute("UPDATE trades SET status='closed' WHERE status='open'").rowcount
# Clear bot state (strategy position tracking)
r2 = c.execute("DELETE FROM bot_state").rowcount
c.commit()
print(f"Closed {r1} open trades, cleared {r2} state records")
c.close()
