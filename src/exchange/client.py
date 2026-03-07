"""
Bybit REST API клиент — Crypto Trader Bot

Обёртка над pybit для работы с Bybit API v5.
Поддерживает: баланс, позиции, ордера, плечо, проверка API-ключа.
"""

import time
from typing import Optional

from pybit.unified_trading import HTTP

from utils.logger import get_logger

logger = get_logger("exchange")


class BybitClient:
    """
    Клиент для работы с биржей Bybit через REST API v5.

    Attributes:
        session: Авторизованная HTTP-сессия pybit
        testnet: Флаг тестовой сети
    """

    def __init__(self, api_key: str, api_secret: str, testnet: bool = True):
        """
        Инициализация клиента Bybit.

        Args:
            api_key: API-ключ Bybit
            api_secret: Секретный ключ Bybit
            testnet: True = тестовая сеть, False = основная сеть
        """
        self.testnet = testnet
        self.session = HTTP(
            testnet=testnet,
            api_key=api_key,
            api_secret=api_secret,
        )
        mode = "TESTNET" if testnet else "MAINNET"
        logger.info(f"Bybit клиент инициализирован ({mode})")

    # ── Аккаунт и баланс ─────────────────────────

    def get_wallet_balance(self) -> dict:
        """
        Получить баланс кошелька (Unified Trading Account).

        Returns:
            dict с полями: totalEquity, totalAvailableBalance, coin list
        """
        try:
            result = self.session.get_wallet_balance(accountType="UNIFIED")
            if result["retCode"] == 0:
                account = result["result"]["list"][0]
                total = float(account.get("totalEquity", 0))
                available = float(account.get("totalAvailableBalance", 0))
                logger.info(f"Баланс: ${total:,.2f} (доступно: ${available:,.2f})")
                return {
                    "totalEquity": total,
                    "totalAvailableBalance": available,
                    "coins": account.get("coin", []),
                    "raw": account,
                }
            else:
                logger.error(f"Ошибка получения баланса: {result['retMsg']}")
                return {}
        except Exception as e:
            logger.error(f"Исключение при получении баланса: {e}")
            return {}

    def check_api_permissions(self) -> dict:
        """
        Проверить права API-ключа.

        Returns:
            dict с правами и флагом безопасности
        """
        try:
            result = self.session.get_api_key_information()
            if result["retCode"] == 0:
                info = result["result"]
                permissions = info.get("permissions", {})

                # Проверяем наличие прав на вывод
                withdraw_perms = permissions.get("Wallet", [])
                has_withdraw = "AccountTransfer" in withdraw_perms or len(withdraw_perms) > 0

                # Проверяем торговые права
                trade_perms = permissions.get("ContractTrade", [])
                can_trade = "Order" in trade_perms and "Position" in trade_perms

                if has_withdraw:
                    logger.warning(
                        "⚠️ API-ключ имеет права на вывод/перевод! "
                        "Рекомендуется создать ключ ТОЛЬКО для торговли."
                    )

                if can_trade:
                    logger.info("✅ API-ключ имеет торговые права")
                else:
                    logger.error("❌ API-ключ НЕ имеет торговых прав!")

                return {
                    "can_trade": can_trade,
                    "has_withdraw": has_withdraw,
                    "is_safe": can_trade and not has_withdraw,
                    "permissions": permissions,
                    "note": info.get("note", ""),
                }
            else:
                logger.error(f"Ошибка проверки API-ключа: {result['retMsg']}")
                return {"can_trade": False, "has_withdraw": False, "is_safe": False}
        except Exception as e:
            logger.error(f"Исключение при проверке API-ключа: {e}")
            return {"can_trade": False, "has_withdraw": False, "is_safe": False}

    # ── Позиции ───────────────────────────────────

    def get_position(self, symbol: str = "ETHUSDT") -> dict:
        """
        Получить информацию о текущей позиции.

        Args:
            symbol: Торговая пара

        Returns:
            dict с данными позиции или пустой dict
        """
        try:
            result = self.session.get_positions(
                category="linear",
                symbol=symbol,
            )
            if result["retCode"] == 0:
                positions = result["result"]["list"]
                if positions:
                    pos = positions[0]
                    size = float(pos.get("size", 0))
                    if size > 0:
                        avg_price = float(pos.get("avgPrice", 0))
                        liq_price = pos.get("liqPrice", "")
                        unrealised_pnl = float(pos.get("unrealisedPnl", 0))
                        side = pos.get("side", "")

                        logger.info(
                            f"Позиция: {side} {size} {symbol} @ ${avg_price:,.2f}, "
                            f"PnL: ${unrealised_pnl:,.2f}"
                        )

                        return {
                            "side": side,
                            "size": size,
                            "avgPrice": avg_price,
                            "liqPrice": float(liq_price) if liq_price else None,
                            "unrealisedPnl": unrealised_pnl,
                            "leverage": pos.get("leverage", "1"),
                            "raw": pos,
                        }

                logger.info(f"Нет открытых позиций по {symbol}")
                return {}
            else:
                logger.error(f"Ошибка получения позиции: {result['retMsg']}")
                return {}
        except Exception as e:
            logger.error(f"Исключение при получении позиции: {e}")
            return {}

    # ── Плечо ─────────────────────────────────────

    def set_leverage(self, symbol: str, leverage: int) -> bool:
        """
        Установить кредитное плечо для торговой пары.

        Args:
            symbol: Торговая пара
            leverage: Значение плеча (1–10)

        Returns:
            True если успешно
        """
        try:
            result = self.session.set_leverage(
                category="linear",
                symbol=symbol,
                buyLeverage=str(leverage),
                sellLeverage=str(leverage),
            )
            if result["retCode"] == 0 or result["retCode"] == 110043:
                # 110043 = leverage not modified (уже установлено)
                logger.info(f"Плечо установлено: {leverage}x для {symbol}")
                return True
            else:
                logger.error(f"Ошибка установки плеча: {result['retMsg']}")
                return False
        except Exception as e:
            # pybit v5.8+ выбрасывает исключение для 110043 вместо возврата dict
            if "110043" in str(e):
                logger.info(f"Плечо уже установлено: {leverage}x для {symbol}")
                return True
            logger.error(f"Исключение при установке плеча: {e}")
            return False

    # ── Ордера ────────────────────────────────────

    def place_order(
        self,
        symbol: str,
        side: str,
        qty: str,
        order_type: str = "Market",
        reduce_only: bool = False,
    ) -> Optional[str]:
        """
        Разместить ордер на бирже.

        Args:
            symbol: Торговая пара (ETHUSDT)
            side: Направление (Buy / Sell)
            qty: Объём в монетах (строка, напр. "0.5")
            order_type: Тип ордера (Market / Limit)
            reduce_only: Только закрытие позиции (для SELL без открытия шорта)

        Returns:
            ID ордера (str) или None при ошибке

        Raises:
            ValueError: Если side="Sell" и reduce_only=False (защита от шорта)
        """
        # ── Защита от шорта ──
        if side == "Sell" and not reduce_only:
            logger.error("🛑 ЗАПРЕТ: нельзя открывать SELL без reduce_only (защита от шорта)")
            raise ValueError("Шорт запрещён! Для закрытия позиции используйте reduce_only=True")

        try:
            params = {
                "category": "linear",
                "symbol": symbol,
                "side": side,
                "orderType": order_type,
                "qty": qty,
                "timeInForce": "GTC",
            }
            if reduce_only:
                params["reduceOnly"] = True

            result = self.session.place_order(**params)

            if result["retCode"] == 0:
                order_id = result["result"]["orderId"]
                logger.info(
                    f"✅ Ордер размещён: {side} {qty} {symbol} "
                    f"({order_type}, reduce_only={reduce_only}) "
                    f"ID: {order_id}"
                )
                return order_id
            else:
                logger.error(f"Ошибка размещения ордера: {result['retMsg']}")
                return None
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Исключение при размещении ордера: {e}")
            return None

    def get_execution_details(self, symbol: str, order_id: str) -> dict:
        """
        Получить детали исполнения ордера (реальная цена и комиссия).

        Args:
            symbol: Торговая пара
            order_id: ID ордера

        Returns:
            dict с полями avg_price, commission, qty или пустой dict
        """
        try:
            result = self.session.get_executions(
                category="linear",
                symbol=symbol,
                orderId=order_id,
            )
            if result["retCode"] == 0:
                executions = result["result"]["list"]
                if not executions:
                    logger.warning(f"Нет данных исполнения для ордера {order_id}")
                    return {}

                # Суммируем все fills для этого ордера
                total_qty = 0.0
                total_cost = 0.0
                total_commission = 0.0

                for ex in executions:
                    qty = float(ex.get("execQty", 0))
                    price = float(ex.get("execPrice", 0))
                    fee = float(ex.get("execFee", 0))
                    total_qty += qty
                    total_cost += qty * price
                    total_commission += abs(fee)  # Комиссия может быть отрицательной (rebate)

                avg_price = total_cost / total_qty if total_qty > 0 else 0
                logger.info(
                    f"📊 Исполнение ордера {order_id[:8]}...: "
                    f"цена ${avg_price:,.2f}, комиссия ${total_commission:,.4f}"
                )
                return {
                    "avg_price": avg_price,
                    "commission": total_commission,
                    "qty": total_qty,
                }
            else:
                logger.error(f"Ошибка получения исполнения: {result['retMsg']}")
                return {}
        except Exception as e:
            logger.error(f"Исключение при получении исполнения: {e}")
            return {}

    def cancel_order(self, symbol: str, order_id: str) -> bool:
        """
        Отменить ордер.

        Args:
            symbol: Торговая пара
            order_id: ID ордера для отмены

        Returns:
            True если успешно отменён
        """
        try:
            result = self.session.cancel_order(
                category="linear",
                symbol=symbol,
                orderId=order_id,
            )
            if result["retCode"] == 0:
                logger.info(f"Ордер отменён: {order_id}")
                return True
            else:
                logger.error(f"Ошибка отмены ордера: {result['retMsg']}")
                return False
        except Exception as e:
            logger.error(f"Исключение при отмене ордера: {e}")
            return False

    # ── Рыночные данные ───────────────────────────

    def get_ticker(self, symbol: str = "ETHUSDT") -> Optional[float]:
        """
        Получить текущую цену актива.

        Args:
            symbol: Торговая пара

        Returns:
            Текущая цена (float) или None
        """
        try:
            result = self.session.get_tickers(
                category="linear",
                symbol=symbol,
            )
            if result["retCode"] == 0:
                price = float(result["result"]["list"][0]["lastPrice"])
                return price
            else:
                logger.error(f"Ошибка получения тикера: {result['retMsg']}")
                return None
        except Exception as e:
            logger.error(f"Исключение при получении тикера: {e}")
            return None

    def get_min_order_qty(self, symbol: str = "ETHUSDT") -> Optional[float]:
        """
        Получить минимальный объём ордера для пары.

        Args:
            symbol: Торговая пара

        Returns:
            Минимальный объём (float) или None
        """
        try:
            result = self.session.get_instruments_info(
                category="linear",
                symbol=symbol,
            )
            if result["retCode"] == 0:
                info = result["result"]["list"][0]
                min_qty = float(info["lotSizeFilter"]["minOrderQty"])
                qty_step = float(info["lotSizeFilter"]["qtyStep"])
                logger.debug(f"{symbol}: min_qty={min_qty}, qty_step={qty_step}")
                return min_qty
            return None
        except Exception as e:
            logger.error(f"Исключение при получении min_qty: {e}")
            return None
