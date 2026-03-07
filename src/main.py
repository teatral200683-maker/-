"""
Crypto Trader Bot — Точка входа

Автоматизированный торговый бот для Bybit.
Лонговая DCA-стратегия на ETH/USDT.
"""

import argparse
import asyncio
import sys
import os
import io

# Исправление кодировки для Windows (cp1251 → UTF-8)
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from colorama import Fore, Style, init as colorama_init

colorama_init(autoreset=True)


def print_banner(config):
    """Вывод красивого баннера при запуске."""
    mode = "Testnet" if config.bybit_testnet else "MAINNET ⚡"
    print(f"""{Fore.CYAN}
╔══════════════════════════════════════════╗
║       🤖 CRYPTO TRADER BOT v1.0         ║
╠══════════════════════════════════════════╣
║  Биржа:     Bybit ({mode:<21})║
║  Пара:      {config.trading.symbol:<29}║
║  Стратегия: Long DCA ({config.trading.leverage}x){' ' * 18}║
║  Депозит:   ${config.trading.working_deposit:<28,.2f}║
╚══════════════════════════════════════════╝
{Style.RESET_ALL}""")


def print_check(name: str, ok: bool, detail: str = ""):
    """Вывод результата проверки."""
    if ok:
        icon = f"{Fore.GREEN}✅{Style.RESET_ALL}"
    else:
        icon = f"{Fore.RED}❌{Style.RESET_ALL}"
    detail_str = f" ({detail})" if detail else ""
    print(f"  {icon} {name}{detail_str}")


def cmd_start(args):
    """Запуск бота."""
    from config import load_config, validate_config
    from bot_engine import BotEngine

    # Загрузка конфигурации
    config = load_config()

    # Override testnet из аргументов
    if args.testnet:
        config.bybit_testnet = True

    # Баннер
    print_banner(config)

    # Валидация
    errors = validate_config(config)
    if errors:
        print(f"\n{Fore.RED}╔══════════════════════════════════════════╗")
        print(f"║  ❌ ОШИБКА КОНФИГУРАЦИИ                 ║")
        print(f"╠══════════════════════════════════════════╣{Style.RESET_ALL}")
        for err in errors:
            print(f"  {err}")
        print(f"{Fore.RED}╚══════════════════════════════════════════╝{Style.RESET_ALL}")
        print(f"\nИсправьте ошибки и перезапустите бот.")
        sys.exit(1)

    # Запуск
    engine = BotEngine(config)

    # Graceful shutdown по Ctrl+C
    try:
        asyncio.run(engine.start())
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}🛑 Остановка по Ctrl+C...{Style.RESET_ALL}")
        asyncio.run(engine.stop("Ручная остановка (Ctrl+C)"))


def cmd_status(args):
    """Показать статус бота."""
    from config import load_config
    from exchange.client import BybitClient
    from storage.database import Database

    config = load_config()
    client = BybitClient(
        api_key=config.bybit_api_key,
        api_secret=config.bybit_api_secret,
        testnet=config.bybit_testnet,
    )

    # Баланс
    wallet = client.get_wallet_balance()
    balance = wallet.get("totalEquity", 0) if wallet else 0

    # Позиция
    position = client.get_position(config.trading.symbol)

    # Статистика из БД
    db = Database()
    stats = db.get_total_stats()
    open_trade = db.get_open_trade()
    db.close()

    print(f"""{Fore.CYAN}
┌─ Статус ─────────────────────────────────┐
│ 💼 Баланс: ${balance:,.2f}{' ' * max(0, 27 - len(f'${balance:,.2f}'))}│{Style.RESET_ALL}""")

    if position:
        side = position.get("side", "?")
        size = position.get("size", 0)
        avg = position.get("avgPrice", 0)
        pnl = position.get("unrealisedPnl", 0)
        color = Fore.GREEN if pnl >= 0 else Fore.RED
        print(f"""{Fore.CYAN}├─ Текущая позиция ─────────────────────────┤
│ {config.trading.symbol}  {side}  {f'Вход {open_trade.entries_count}/5' if open_trade else ''}{' ' * 20}│
│ Средняя: ${avg:,.2f}  PnL: {color}${pnl:+,.2f}{Fore.CYAN}{' ' * 10}│{Style.RESET_ALL}""")
    else:
        print(f"{Fore.CYAN}├─ Позиция ─────────────────────────────────┤")
        print(f"│ Нет открытых позиций{' ' * 21}│{Style.RESET_ALL}")

    print(f"""{Fore.CYAN}├─ Статистика ──────────────────────────────┤
│ Сделок:  {stats['total_trades']}  (винрейт {stats['win_rate']:.0f}%){' ' * 15}│
│ PnL:     ${stats['total_profit']:+,.2f}{' ' * max(0, 28 - len(f"${stats['total_profit']:+,.2f}"))}│
└───────────────────────────────────────────┘{Style.RESET_ALL}""")


def cmd_stats(args):
    """Показать статистику сделок."""
    from storage.database import Database

    db = Database()
    stats = db.get_total_stats()
    trades = db.get_closed_trades(limit=10)
    db.close()

    print(f"\n{Fore.CYAN}📊 Статистика{Style.RESET_ALL}\n")
    print(f"  Всего сделок:    {stats['total_trades']}")
    print(f"  Прибыльных:      {stats['winning_trades']}")
    print(f"  Винрейт:         {stats['win_rate']:.1f}%")
    print(f"  Общий PnL:       {Fore.GREEN}${stats['total_profit']:+,.2f}{Style.RESET_ALL}")
    print(f"  Средний PnL:     ${stats['avg_profit']:+,.2f}")

    if trades:
        print(f"\n{Fore.CYAN}Последние сделки:{Style.RESET_ALL}")
        print(f"  {'#':<5} {'Дата':<12} {'Входов':<8} {'PnL':<12} {'Статус'}")
        print(f"  {'-'*5} {'-'*12} {'-'*8} {'-'*12} {'-'*8}")
        for t in trades:
            date_str = t.closed_at.strftime("%d.%m %H:%M") if t.closed_at else "—"
            pnl_color = Fore.GREEN if (t.net_pnl or 0) >= 0 else Fore.RED
            print(
                f"  {t.id:<5} {date_str:<12} {t.entries_count:<8} "
                f"{pnl_color}${t.net_pnl or 0:+,.2f}{Style.RESET_ALL}{'':>4} ✅"
            )


def cmd_check_config(args):
    """Проверить конфигурацию."""
    from config import load_config, validate_config

    config = load_config()
    print(f"\n{Fore.CYAN}⚙️ Проверка конфигурации{Style.RESET_ALL}\n")

    # .env
    print_check("BYBIT_API_KEY", bool(config.bybit_api_key and config.bybit_api_key != "your_api_key_here"))
    print_check("BYBIT_API_SECRET", bool(config.bybit_api_secret and config.bybit_api_secret != "your_api_secret_here"))
    print_check("BYBIT_TESTNET", True, "testnet" if config.bybit_testnet else "MAINNET")
    print_check("TELEGRAM_BOT_TOKEN", bool(config.telegram_bot_token and config.telegram_bot_token != "your_bot_token_here"))
    print_check("TELEGRAM_CHAT_ID", bool(config.telegram_chat_id and config.telegram_chat_id != "your_chat_id_here"))

    # config.json
    print(f"\n  Торговля:")
    print(f"    Пара:         {config.trading.symbol}")
    print(f"    Плечо:        {config.trading.leverage}x")
    print(f"    Тейк-профит:  {config.trading.take_profit_pct}%")
    print(f"    Макс. входов: {config.trading.max_entries}")
    print(f"    Шаг усредн.:  {config.trading.entry_step_pct}%")
    print(f"    Размер входа: {config.trading.position_size_pct}%")
    print(f"    Раб. депозит: ${config.trading.working_deposit:,.2f}")

    errors = validate_config(config)
    if errors:
        print(f"\n{Fore.RED}Найдено ошибок: {len(errors)}{Style.RESET_ALL}")
    else:
        print(f"\n{Fore.GREEN}✅ Конфигурация валидна{Style.RESET_ALL}")


def main():
    """Парсинг аргументов CLI."""
    parser = argparse.ArgumentParser(
        description="🤖 Crypto Trader Bot — автоматическая торговля на Bybit",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Команда")

    # start
    start_parser = subparsers.add_parser("start", help="Запустить бота")
    start_parser.add_argument("--testnet", action="store_true", help="Использовать тестовую сеть")

    # status
    subparsers.add_parser("status", help="Показать статус")

    # stats
    subparsers.add_parser("stats", help="Показать статистику сделок")

    # check-config
    subparsers.add_parser("check-config", help="Проверить конфигурацию")

    args = parser.parse_args()

    if args.command == "start":
        cmd_start(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "stats":
        cmd_stats(args)
    elif args.command == "check-config":
        cmd_check_config(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
