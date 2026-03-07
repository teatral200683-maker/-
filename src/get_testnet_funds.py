"""
Перевод средств из Funding в Unified Trading Account на Bybit Testnet
"""
import sys
import io

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from pybit.unified_trading import HTTP
from dotenv import load_dotenv
import os

load_dotenv()

session = HTTP(
    testnet=True,
    api_key=os.getenv("BYBIT_API_KEY"),
    api_secret=os.getenv("BYBIT_API_SECRET"),
)

# 1. Проверяем текущий баланс Unified
print("=== Баланс ДО перевода ===")
try:
    result = session.get_wallet_balance(accountType="UNIFIED")
    coins = result["result"]["list"][0]["coin"]
    total = result["result"]["list"][0].get("totalEquity", "0")
    print(f"  Unified Total Equity: ${total}")
    for coin in coins:
        bal = float(coin.get("walletBalance", 0))
        if bal > 0:
            print(f"  {coin['coin']}: {bal}")
except Exception as e:
    print(f"  Ошибка: {e}")

# 2. Перевод USDT: FUND -> UNIFIED
print("\n=== Перевод USDT: Funding -> Unified ===")
try:
    import uuid
    transfer_id = str(uuid.uuid4())
    result = session.create_internal_transfer(
        transferId=transfer_id,
        coin="USDT",
        amount="5000",
        fromAccountType="FUND",
        toAccountType="UNIFIED",
    )
    print(f"  Результат: {result}")
except Exception as e:
    print(f"  Ошибка перевода: {e}")

# 3. Также переведём немного BTC на случай
print("\n=== Перевод BTC: Funding -> Unified ===")
try:
    transfer_id2 = str(uuid.uuid4())
    result2 = session.create_internal_transfer(
        transferId=transfer_id2,
        coin="BTC",
        amount="0.5",
        fromAccountType="FUND",
        toAccountType="UNIFIED",
    )
    print(f"  Результат: {result2}")
except Exception as e:
    print(f"  Ошибка перевода BTC: {e}")

# 4. Проверяем баланс ПОСЛЕ перевода
print("\n=== Баланс ПОСЛЕ перевода ===")
try:
    result = session.get_wallet_balance(accountType="UNIFIED")
    total = result["result"]["list"][0].get("totalEquity", "0")
    print(f"  Unified Total Equity: ${total}")
    coins = result["result"]["list"][0]["coin"]
    for coin in coins:
        bal = float(coin.get("walletBalance", 0))
        if bal > 0:
            print(f"  {coin['coin']}: {bal}")
except Exception as e:
    print(f"  Ошибка: {e}")
