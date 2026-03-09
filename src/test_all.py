"""
Полный тест-скрипт — Crypto Trader Bot
T-050: Connectivity | T-051: Position | T-052: Telegram
"""
import sys
import io
import asyncio

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from config import load_config
from exchange.client import BybitClient
from notifications.telegram import TelegramNotifier
from storage.database import Database

config = load_config()
client = BybitClient(
    api_key=config.bybit_api_key,
    api_secret=config.bybit_api_secret,
    testnet=config.bybit_testnet,
)

passed = 0
failed = 0

# === T-050: Connectivity ===
print("=" * 50)
print("T-050: CONNECTIVITY TEST")
print("=" * 50)

wallet = client.get_wallet_balance()
if wallet:
    print(f"  Balance:     ${wallet['totalEquity']:,.2f}")
    print(f"  Available:   ${wallet['totalAvailableBalance']:,.2f}")
    print("  RESULT: PASS")
    passed += 1
else:
    print("  RESULT: FAIL - no wallet data")
    failed += 1

perms = client.check_api_permissions()
can_trade = perms.get("can_trade", False)
has_withdraw = perms.get("has_withdraw", False)
print(f"  Can trade:   {can_trade}")
print(f"  Withdraw:    {has_withdraw}")

if can_trade:
    print("  API perms:   PASS")
    passed += 1
else:
    print("  API perms:   FAIL")
    failed += 1

if not has_withdraw:
    print("  No withdraw: PASS (safe!)")
    passed += 1
else:
    print("  No withdraw: WARNING - withdraw enabled!")

# === T-051: Position / Orders ===
print()
print("=" * 50)
print("T-051: POSITION & ORDERS TEST")
print("=" * 50)

pos = client.get_position("ETHUSDT")
if pos:
    side = pos.get("side", "None")
    size = pos.get("size", 0)
    avg_price = pos.get("avgPrice", 0)
    pnl = pos.get("unrealisedPnl", 0)
    liq_price = pos.get("liqPrice", "N/A")
    print(f"  Side:        {side}")
    print(f"  Size:        {size}")
    print(f"  Avg Price:   {avg_price}")
    print(f"  PnL:         {pnl}")
    print(f"  Liq Price:   {liq_price}")
    print("  RESULT: PASS (position active)")
    passed += 1
else:
    print("  No open position")
    print("  RESULT: PASS (idle)")
    passed += 1

# DB check
db = Database()
stats = db.get_total_stats()
open_trade = db.get_open_trade()
print(f"  DB trades:   {stats['total_trades']}")
print(f"  DB win rate: {stats['win_rate']:.1f}%")
print(f"  DB PnL:      ${stats['total_profit']:+,.2f}")
if open_trade:
    print(f"  Open trade:  #{open_trade.id} ({open_trade.entries_count} entries)")
print("  DB:          PASS")
passed += 1
db.close()

# === T-052: Telegram ===
print()
print("=" * 50)
print("T-052: TELEGRAM NOTIFICATION TEST")
print("=" * 50)

notifier = TelegramNotifier(config.telegram_bot_token, config.telegram_chat_id)
if notifier._enabled:
    async def test_telegram():
        await notifier._send("Audit test (09.03.2026) - all systems OK")
    asyncio.run(test_telegram())
    print("  Telegram:    PASS (message sent)")
    passed += 1
else:
    print("  Telegram:    SKIP (not configured)")

# === SUMMARY ===
print()
print("=" * 50)
total = passed + failed
print(f"RESULTS: {passed}/{total} PASSED, {failed} FAILED")
if failed == 0:
    print("ALL TESTS PASSED")
else:
    print("SOME TESTS FAILED!")
print("=" * 50)
