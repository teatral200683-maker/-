"""
Технические индикаторы — Crypto Trader Bot

ATR, EMA, RSI для адаптивного управления позицией.
"""

from collections import deque
from typing import Optional

from utils.logger import get_logger

logger = get_logger("indicators")


class Indicators:
    """
    Расчёт технических индикаторов на основе потока цен.

    Накапливает тиковые данные, формирует 1-минутные свечи,
    и рассчитывает:
    - ATR (Average True Range) — волатильность
    - EMA (Exponential Moving Average) — тренд
    - RSI (Relative Strength Index) — перекупленность/перепроданность
    """

    def __init__(self, atr_period: int = 14, ema_period: int = 50, rsi_period: int = 14):
        self.atr_period = atr_period
        self.ema_period = ema_period
        self.rsi_period = rsi_period

        # Хранение свечей (макс 500)
        self._highs: deque = deque(maxlen=500)
        self._lows: deque = deque(maxlen=500)
        self._closes: deque = deque(maxlen=500)

        # Кэш последних значений
        self._last_atr: Optional[float] = None
        self._last_ema: Optional[float] = None
        self._last_rsi: Optional[float] = None

        # Свечка в процессе формирования (1-минутная)
        self._candle_high: float = 0
        self._candle_low: float = float('inf')
        self._candle_close: float = 0
        self._candle_ticks: int = 0
        self._candle_size: int = 60  # тиков на свечу

        logger.info(
            f"Индикаторы: ATR({atr_period}), EMA({ema_period}), RSI({rsi_period})"
        )

    def update(self, price: float):
        """
        Обновить индикаторы новой ценой (тиком).

        На каждом тике обновляем текущую свечу.
        Каждые 60 тиков — закрываем свечу и пересчитываем.
        """
        # Обновление формируемой свечи
        if price > self._candle_high:
            self._candle_high = price
        if price < self._candle_low:
            self._candle_low = price
        self._candle_close = price
        self._candle_ticks += 1

        # Закрытие свечи
        if self._candle_ticks >= self._candle_size:
            self._highs.append(self._candle_high)
            self._lows.append(self._candle_low)
            self._closes.append(self._candle_close)

            # Пересчёт индикаторов
            self._recalculate()

            # Сброс свечи
            self._candle_high = price
            self._candle_low = price
            self._candle_close = price
            self._candle_ticks = 0

    def _recalculate(self):
        """Пересчитать все индикаторы."""
        closes = list(self._closes)

        if len(closes) >= self.atr_period + 1:
            self._last_atr = self._calc_atr()

        if len(closes) >= self.ema_period:
            self._last_ema = self._calc_ema(closes, self.ema_period)

        if len(closes) >= self.rsi_period + 1:
            self._last_rsi = self._calc_rsi(closes, self.rsi_period)

    def _calc_atr(self) -> Optional[float]:
        """
        ATR (Average True Range).
        True Range = max(high-low, |high-prev_close|, |low-prev_close|)
        ATR = SMA(TR, period)
        """
        highs = list(self._highs)
        lows = list(self._lows)
        closes = list(self._closes)

        if len(closes) < self.atr_period + 1:
            return None

        true_ranges = []
        for i in range(1, len(closes)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            true_ranges.append(tr)

        if len(true_ranges) < self.atr_period:
            return None

        recent_tr = true_ranges[-self.atr_period:]
        return sum(recent_tr) / len(recent_tr)

    def _calc_ema(self, prices: list, period: int) -> Optional[float]:
        """
        EMA (Exponential Moving Average).
        EMA = price * k + EMA_prev * (1-k), k = 2/(period+1)
        """
        if len(prices) < period:
            return None

        k = 2 / (period + 1)
        ema = sum(prices[:period]) / period

        for price in prices[period:]:
            ema = price * k + ema * (1 - k)

        return ema

    def _calc_rsi(self, prices: list, period: int) -> Optional[float]:
        """
        RSI (Relative Strength Index).
        RSI = 100 - 100/(1+RS), RS = avg_gain / avg_loss
        """
        if len(prices) < period + 1:
            return None

        gains = []
        losses = []

        for i in range(1, len(prices)):
            change = prices[i] - prices[i - 1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))

        if len(gains) < period:
            return None

        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        return round(100 - (100 / (1 + rs)), 2)

    # ── Публичные методы ──

    def get_atr(self) -> Optional[float]:
        """Текущий ATR (None если мало данных)."""
        return self._last_atr

    def get_ema(self) -> Optional[float]:
        """Текущий EMA (None если мало данных)."""
        return self._last_ema

    def get_rsi(self) -> Optional[float]:
        """Текущий RSI 0-100 (None если мало данных)."""
        return self._last_rsi

    def get_volatility_factor(self, base_atr: float = 50.0) -> float:
        """
        Коэффициент волатильности для адаптивного размера.

        Возвращает 0.3–1.5:
        - ATR низкий → > 1.0 (увеличить позицию)
        - ATR высокий → < 1.0 (уменьшить позицию)
        """
        atr = self._last_atr
        if atr is None or atr <= 0:
            return 1.0

        factor = base_atr / atr
        return round(max(0.3, min(1.5, factor)), 3)

    def is_ready(self) -> bool:
        """Достаточно ли данных для расчётов."""
        return len(self._closes) >= max(self.atr_period + 1, self.rsi_period + 1)

    def get_summary(self) -> dict:
        """Сводка по всем индикаторам."""
        return {
            "atr": self._last_atr,
            "ema": self._last_ema,
            "rsi": self._last_rsi,
            "volatility_factor": self.get_volatility_factor(),
            "candles_collected": len(self._closes),
            "ready": self.is_ready(),
        }
