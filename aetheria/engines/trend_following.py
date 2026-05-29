"""
engines/trend_following.py
==========================

محرك اتباع الاتجاه (Trend Following Engine).

الأساس النظري
-------------
يجسّد **النظرية 21 (التوافق/الزخم الاتجاهي)** عبر تقاطعات المتوسطات الأسية
(EMA) مع تأكيد قوة الاتجاه بمؤشر **ADX** (لتفادي الإشارات في الأسواق
العرضية الميتة — وهو ما يتقاطع مع منطق إنتروبيا النظرية 11).

المعادلات المستخدمة (موثّقة)
----------------------------
• EMA (Exponential Moving Average):
      EMA_t = α·Price_t + (1−α)·EMA_(t−1) ,  α = 2/(N+1)

• ADX (المرجع: J. Welles Wilder, 1978):
      +DM = max(High−prevHigh, 0)  إن تجاوز (prevLow−Low)، وإلا 0
      −DM = max(prevLow−Low, 0)    إن تجاوز (High−prevHigh)، وإلا 0
      +DI = 100·RMA(+DM)/ATR ,  −DI = 100·RMA(−DM)/ATR
      DX  = 100·|+DI − −DI| / (+DI + −DI)
      ADX = RMA(DX, N)

منطق الإشارة
------------
    BUY  : تقاطع EMA السريع فوق البطيء (Golden cross) و ADX ≥ العتبة.
    SELL : تقاطع EMA السريع تحت البطيء (Death cross) و ADX ≥ العتبة.
    HOLD : غير ذلك.
SL/TP يُحسبان ديناميكياً بالـ ATR (نسبة عائد/مخاطرة ثابتة).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd

from config import settings
from .engine_base import EngineBase, Signal, SignalType

logger = logging.getLogger(__name__)


class TrendFollowingEngine(EngineBase):
    """
    محرك اتباع الاتجاه عبر تقاطعات EMA مع فلتر ADX.

    Attributes:
        fast_period, slow_period : فترتا المتوسط السريع/البطيء.
        adx_period, adx_threshold: فترة ADX وعتبة قوة الاتجاه.
        atr_period               : فترة ATR لإدارة المخاطر.
        rr                       : نسبة العائد/المخاطرة للهدف.
        symbol                   : رمز الزوج.
    """

    def __init__(
        self,
        fast_period: Optional[int] = None,
        slow_period: Optional[int] = None,
        adx_period: Optional[int] = None,
        adx_threshold: Optional[float] = None,
        atr_period: Optional[int] = None,
        rr: float = 2.0,
        symbol: Optional[str] = None,
    ) -> None:
        super().__init__()
        p = settings.TREND_FOLLOWING_PARAMS
        self.fast_period = int(fast_period if fast_period is not None else p["ema_fast"])
        self.slow_period = int(slow_period if slow_period is not None else p["ema_slow"])
        self.adx_period = int(adx_period if adx_period is not None else p["adx_period"])
        self.adx_threshold = float(
            adx_threshold if adx_threshold is not None else p["adx_threshold"]
        )
        self.atr_period = int(atr_period if atr_period is not None else settings.ATR_PERIOD)
        self.rr = float(rr)
        self.symbol = symbol or settings.DEFAULT_SYMBOL

        # نحتاج بيانات كافية لأبطأ متوسط + ADX مع هامش.
        self.min_rows = self.slow_period + self.adx_period + 5

    # --------------------------- الخصائص الإلزامية -------------------------- #
    @property
    def name(self) -> str:
        return "TrendFollowing"

    @property
    def version(self) -> str:
        return "1.0.0"

    # ----------------------------- حساب المؤشرات --------------------------- #
    @staticmethod
    def _rma(series: "pd.Series", period: int) -> "pd.Series":
        """متوسط وايلدر المتحرك (RMA) — أساس ATR و ADX."""
        return series.ewm(alpha=1.0 / period, adjust=False).mean()

    def _atr(self, df: "pd.DataFrame") -> "pd.Series":
        """حساب ATR (يُستخدم في ADX وإدارة المخاطر)."""
        high, low, close = df["high"], df["low"], df["close"]
        prev_close = close.shift(1)
        tr = pd.concat(
            [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
            axis=1,
        ).max(axis=1)
        return self._rma(tr, self.atr_period)

    def _adx(self, df: "pd.DataFrame", atr: "pd.Series") -> "pd.Series":
        """حساب مؤشر متوسط الحركة الاتجاهية ADX (قوة الاتجاه)."""
        high, low = df["high"], df["low"]
        up_move = high.diff()
        down_move = -low.diff()
        # +DM و −DM وفق قواعد وايلدر.
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
        plus_dm = pd.Series(plus_dm, index=df.index)
        minus_dm = pd.Series(minus_dm, index=df.index)

        atr_safe = atr.replace(0.0, np.nan)
        plus_di = 100.0 * self._rma(plus_dm, self.adx_period) / atr_safe
        minus_di = 100.0 * self._rma(minus_dm, self.adx_period) / atr_safe
        di_sum = (plus_di + minus_di).replace(0.0, np.nan)
        dx = 100.0 * (plus_di - minus_di).abs() / di_sum
        return self._rma(dx.fillna(0.0), self.adx_period)

    def compute_indicators(self, df: "pd.DataFrame") -> "pd.DataFrame":
        """
        حساب EMA السريع/البطيء + ATR + ADX + إشارة التقاطع.

        Returns:
            نسخة من df مضافاً إليها: ema_fast, ema_slow, atr, adx, cross.
            (cross: +1 تقاطع صعودي، -1 تقاطع هبوطي، 0 لا تقاطع)
        """
        out = df.copy()
        close = out["close"]

        out["ema_fast"] = close.ewm(span=self.fast_period, adjust=False).mean()
        out["ema_slow"] = close.ewm(span=self.slow_period, adjust=False).mean()
        out["atr"] = self._atr(out)
        out["adx"] = self._adx(out, out["atr"])

        # كشف التقاطع: تغيّر إشارة الفرق (ema_fast − ema_slow).
        diff = out["ema_fast"] - out["ema_slow"]
        prev_diff = diff.shift(1)
        cross_up = (diff > 0) & (prev_diff <= 0)
        cross_dn = (diff < 0) & (prev_diff >= 0)
        out["cross"] = np.where(cross_up, 1, np.where(cross_dn, -1, 0))
        return out

    # --------------------- خطّافات الباكتيست (مُعاد استخدامها) --------------- #
    def generate_entry(self, row: Any) -> Optional[SignalType]:
        """تقييم صفّ مؤشرات واحد وإرجاع BUY/SELL/None."""
        try:
            cross = int(row["cross"])
            adx = float(row["adx"])
        except (KeyError, TypeError, ValueError):
            return None
        if np.isnan(adx) or adx < self.adx_threshold:
            return None  # اتجاه ضعيف/عرضي ⇒ تجاهل
        if cross == 1:
            return SignalType.BUY
        if cross == -1:
            return SignalType.SELL
        return None

    def compute_sl_tp(self, side: SignalType, entry: float, row: Any) -> Tuple[float, float]:
        """خطّاف الباكتيست: SL/TP ديناميكي بالـ ATR ونسبة عائد ثابتة."""
        atr = float(row["atr"])
        high_vol = atr > (entry * 0.004)
        mult = (
            settings.ATR_SL_MULTIPLIER_HIGH_VOL if high_vol else settings.ATR_SL_MULTIPLIER
        )
        sl_dist = atr * mult
        if side == SignalType.BUY:
            return entry - sl_dist, entry + self.rr * sl_dist
        return entry + sl_dist, entry - self.rr * sl_dist

    # ------------------------------- التحليل ------------------------------- #
    def analyze(self, df: "pd.DataFrame") -> Dict[str, Any]:
        """تحليل آخر شمعة وإصدار إشارة (للتداول الحي)."""
        try:
            self.validate_data(df)
            ind = self.compute_indicators(df)
            last = ind.iloc[-1]

            close = float(last["close"])
            ema_fast = float(last["ema_fast"])
            ema_slow = float(last["ema_slow"])
            adx = float(last["adx"])
            atr = float(last["atr"])

            if any(np.isnan(v) for v in (ema_fast, ema_slow, adx, atr)):
                return self.hold(self.symbol, "المؤشرات غير مكتملة بعد.")

            indicators = {
                "close": round(close, 3),
                "ema_fast": round(ema_fast, 3),
                "ema_slow": round(ema_slow, 3),
                "adx": round(adx, 2),
                "atr": round(atr, 3),
            }

            side = self.generate_entry(last)
            if side is None:
                sig = self.hold(self.symbol, f"لا تقاطع/اتجاه قوي (ADX={adx:.1f}).")
                sig["indicators"] = indicators
                return sig

            sl, tp = self.compute_sl_tp(side, close, last)
            tp_pips = abs(tp - close) / settings.PIP_SIZE
            sl_pips = abs(close - sl) / settings.PIP_SIZE
            # الثقة تعتمد على قوة الاتجاه (ADX) منسوبة لنطاق 20→50.
            confidence = float(np.clip(0.5 + (adx - self.adx_threshold) / 60.0, 0.5, 0.95))

            reason = (
                f"تقاطع EMA {'صعودي' if side == SignalType.BUY else 'هبوطي'} "
                f"(سريع={ema_fast:.2f}, بطيء={ema_slow:.2f}) مع اتجاه قوي "
                f"(ADX={adx:.1f}). TP≈{tp_pips:.0f} نقطة | SL≈{sl_pips:.0f} نقطة"
            )
            indicators = {**indicators, "tp_pips": round(tp_pips, 1), "sl_pips": round(sl_pips, 1)}

            return Signal(
                signal_type=side,
                symbol=self.symbol,
                entry=round(close, 3),
                sl=round(sl, 3),
                tp=round(tp, 3),
                confidence=confidence,
                reason=reason,
                engine=self.name,
                indicators=indicators,
            ).to_dict()

        except Exception as exc:  # noqa: BLE001
            self.log.error("خطأ في تحليل TrendFollowing: %s", exc)
            return self.hold(self.symbol, f"خطأ تحليلي: {exc}")


# --------------------------------------------------------------------------- #
# اختبار مستقل: python -m engines.trend_following
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("اختبار TrendFollowingEngine على بيانات وهمية...")

    rng = np.random.default_rng(7)
    n = 400
    # اتجاه صاعد ثم هابط لاختبار التقاطعات.
    trend = np.concatenate([np.linspace(2300, 2400, n // 2), np.linspace(2400, 2280, n - n // 2)])
    close = trend + rng.normal(0, 4, n)
    high = close + rng.uniform(1, 5, n)
    low = close - rng.uniform(1, 5, n)
    open_ = close + rng.uniform(-2, 2, n)
    volume = rng.integers(50, 500, n)
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    dummy = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )

    engine = TrendFollowingEngine(fast_period=20, slow_period=50)
    print(f"المحرك: {engine!r} | min_rows={engine.min_rows}")
    res = engine.analyze(dummy)
    print("نتيجة آخر شمعة:", res["signal"], "|", res["reason"])

    ind = engine.compute_indicators(dummy)
    crosses = int((ind["cross"] != 0).sum())
    print(f"عدد التقاطعات المكتشفة: {crosses}")
    print("✅ انتهى الاختبار.")
