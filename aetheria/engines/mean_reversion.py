"""
engines/mean_reversion.py
=========================

محرك الارتداد إلى المتوسط (Mean Reversion Engine).

الأساس النظري
-------------
يجسّد هذا المحرك **النظرية 18 (تذبذب الجاذبية الإحصائية / Mean Reversion)**
المستندة إلى قانون هوك للمرونة: كلما ابتعد السعر عن "قيمته العادلة"
(المتوسط) زادت قوة شدّه للعودة. ندمج أداتين كلاسيكيتين:

    1) Bollinger Bands  : لقياس مدى ابتعاد السعر عن المتوسط (الانحراف المعياري).
    2) RSI              : لتأكيد حالة التشبع (Overbought / Oversold).

وتُحسب إدارة المخاطر عبر **ATR** تجسيداً لـ **النظرية 23 (صمّام الأمان)**:
وقف خسارة ديناميكي يتّسع في الأسواق عالية التقلّب.

المعادلات المستخدمة (موثّقة)
----------------------------
• Bollinger Bands (المرجع: John Bollinger, 1980s):
      MB    = SMA(close, N)
      σ     = الانحراف المعياري للسعر خلال N (population, ddof=0)
      Upper = MB + k·σ
      Lower = MB − k·σ
      %B    = (close − Lower) / (Upper − Lower)

• RSI (المرجع: J. Welles Wilder, 1978):
      ΔP        = close.diff()
      Gain      = max(ΔP, 0) ,  Loss = max(−ΔP, 0)
      AvgGain   = RMA(Gain, N)   (تنعيم وايلدر: α = 1/N)
      AvgLoss   = RMA(Loss, N)
      RS        = AvgGain / AvgLoss
      RSI       = 100 − 100 / (1 + RS)

• ATR (المرجع: Wilder, 1978):
      TR  = max(High−Low, |High−prevClose|, |Low−prevClose|)
      ATR = RMA(TR, N)

منطق الإشارة
------------
    BUY  : close ≤ LowerBand  و  RSI ≤ oversold   (تشبّع بيعي + تمدّد سفلي)
    SELL : close ≥ UpperBand  و  RSI ≥ overbought (تشبّع شرائي + تمدّد علوي)
    HOLD : غير ذلك.
الهدف (TP) = العودة إلى المتوسط (MB)، ووقف الخسارة (SL) = ATR ديناميكي،
مع فرض حدّ أدنى لنسبة العائد/المخاطرة (R:R).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from config import settings
from .engine_base import EngineBase, Signal, SignalType

logger = logging.getLogger(__name__)


class MeanReversionEngine(EngineBase):
    """
    محرك الارتداد للمتوسط (Bollinger Bands + RSI) مع SL/TP ديناميكي بالـ ATR.

    Attributes:
        bb_period     : فترة متوسط بولينجر.
        bb_std        : عدد الانحرافات المعيارية للنطاقات.
        rsi_period    : فترة RSI.
        rsi_oversold  : حد التشبّع البيعي (إشارة شراء).
        rsi_overbought: حد التشبّع الشرائي (إشارة بيع).
        atr_period    : فترة ATR لإدارة المخاطر.
        symbol        : رمز الزوج (افتراضياً من الإعدادات).
    """

    def __init__(
        self,
        bb_period: Optional[int] = None,
        bb_std: Optional[float] = None,
        rsi_period: Optional[int] = None,
        rsi_oversold: Optional[float] = None,
        rsi_overbought: Optional[float] = None,
        atr_period: Optional[int] = None,
        symbol: Optional[str] = None,
    ) -> None:
        super().__init__()
        # نقرأ القيم الافتراضية من الإعدادات، مع السماح بتجاوزها عند الإنشاء.
        p = settings.MEAN_REVERSION_PARAMS
        self.bb_period = int(bb_period if bb_period is not None else p["bb_period"])
        self.bb_std = float(bb_std if bb_std is not None else p["bb_std"])
        self.rsi_period = int(rsi_period if rsi_period is not None else p["rsi_period"])
        self.rsi_oversold = float(
            rsi_oversold if rsi_oversold is not None else p["rsi_oversold"]
        )
        self.rsi_overbought = float(
            rsi_overbought if rsi_overbought is not None else p["rsi_overbought"]
        )
        self.atr_period = int(atr_period if atr_period is not None else settings.ATR_PERIOD)
        self.symbol = symbol or settings.DEFAULT_SYMBOL

        # نحتاج بيانات كافية لأطول مؤشر (بولينجر/RSI/ATR) مع هامش.
        self.min_rows = max(self.bb_period, self.rsi_period, self.atr_period) + 5

    # --------------------------- الخصائص الإلزامية -------------------------- #
    @property
    def name(self) -> str:
        return "MeanReversion"

    @property
    def version(self) -> str:
        return "1.0.0"

    # ----------------------------- حساب المؤشرات --------------------------- #
    @staticmethod
    def _rma(series: "pd.Series", period: int) -> "pd.Series":
        """
        متوسط وايلدر المتحرك (Wilder's RMA) — أساس RSI و ATR.

        يكافئ تنعيماً أسياً بمعامل α = 1/period (مع adjust=False ليطابق
        صيغة وايلدر الأصلية تماماً).
        """
        return series.ewm(alpha=1.0 / period, adjust=False).mean()

    def _rsi(self, close: "pd.Series") -> "pd.Series":
        """حساب مؤشر القوة النسبية RSI وفق صيغة وايلدر."""
        delta = close.diff()
        gain = delta.clip(lower=0.0)          # الأرباح: التغيّرات الموجبة فقط
        loss = (-delta).clip(lower=0.0)       # الخسائر: القيمة المطلقة للسالبة
        avg_gain = self._rma(gain, self.rsi_period)
        avg_loss = self._rma(loss, self.rsi_period)
        # نتجنّب القسمة على صفر: حيث avg_loss=0 يكون RSI=100.
        rs = avg_gain / avg_loss.replace(0.0, np.nan)
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return rsi.fillna(100.0)              # لا خسائر ⇒ تشبّع شرائي تام

    def _atr(self, df: "pd.DataFrame") -> "pd.Series":
        """حساب المدى الحقيقي المتوسط ATR (تقلّب السوق)."""
        high, low, close = df["high"], df["low"], df["close"]
        prev_close = close.shift(1)
        # المدى الحقيقي TR = أكبر القيم الثلاث.
        tr = pd.concat(
            [
                (high - low),
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        return self._rma(tr, self.atr_period)

    def compute_indicators(self, df: "pd.DataFrame") -> "pd.DataFrame":
        """
        حساب كل المؤشرات وإلحاقها كأعمدة جديدة (دالة قابلة لإعادة الاستخدام
        في محرك الباكتيست أيضاً).

        Returns:
            نسخة من df مضافاً إليها: mb, upper, lower, pct_b, rsi, atr.
        """
        out = df.copy()
        close = out["close"]

        # --- Bollinger Bands ---
        out["mb"] = close.rolling(self.bb_period).mean()
        # ddof=0 ⇒ انحراف معياري للمجتمع (يطابق صيغة بولينجر الشائعة).
        sigma = close.rolling(self.bb_period).std(ddof=0)
        out["upper"] = out["mb"] + self.bb_std * sigma
        out["lower"] = out["mb"] - self.bb_std * sigma
        # %B: موضع السعر داخل النطاق (0=عند السفلي، 1=عند العلوي).
        band_range = (out["upper"] - out["lower"]).replace(0.0, np.nan)
        out["pct_b"] = (close - out["lower"]) / band_range

        # --- RSI & ATR ---
        out["rsi"] = self._rsi(close)
        out["atr"] = self._atr(out)
        return out

    # ------------------------------- التحليل ------------------------------- #
    def analyze(self, df: "pd.DataFrame") -> Dict[str, Any]:
        """
        تحليل آخر شمعة وإصدار إشارة BUY/SELL/HOLD.

        Args:
            df: DataFrame بأعمدة open/high/low/close/volume وفهرس زمني.

        Returns:
            قاموس الإشارة الموحّد (Signal.to_dict()). لا يرفع استثناءً عند
            خطأ منطقي بل يُرجع HOLD مع السبب (تحقيقاً لمعيار معالجة الأخطاء).
        """
        try:
            self.validate_data(df)
            ind = self.compute_indicators(df)
            last = ind.iloc[-1]  # آخر شمعة مكتملة

            close = float(last["close"])
            mb = float(last["mb"])
            upper = float(last["upper"])
            lower = float(last["lower"])
            rsi = float(last["rsi"])
            atr = float(last["atr"])
            pct_b = float(last["pct_b"])

            # إن لم تكتمل المؤشرات بعد (NaN في بداية السلسلة) ⇒ انتظار.
            if any(np.isnan(v) for v in (mb, upper, lower, rsi, atr)):
                return self.hold(self.symbol, "المؤشرات غير مكتملة بعد (بيانات قليلة).")

            indicators = {
                "close": round(close, 3),
                "mb": round(mb, 3),
                "upper": round(upper, 3),
                "lower": round(lower, 3),
                "rsi": round(rsi, 2),
                "atr": round(atr, 3),
                "pct_b": round(pct_b, 3),
            }

            # ---------- شرط الشراء: تشبّع بيعي + لمس النطاق السفلي ----------
            if close <= lower and rsi <= self.rsi_oversold:
                return self._build_signal(
                    SignalType.BUY, close, mb, atr, rsi, pct_b, indicators
                )

            # ---------- شرط البيع: تشبّع شرائي + لمس النطاق العلوي ----------
            if close >= upper and rsi >= self.rsi_overbought:
                return self._build_signal(
                    SignalType.SELL, close, mb, atr, rsi, pct_b, indicators
                )

            # ---------- غير ذلك: انتظار ----------
            sig = self.hold(self.symbol, "لا تشبّع/تمدّد كافٍ للدخول.")
            sig["indicators"] = indicators
            return sig

        except Exception as exc:  # noqa: BLE001 - نُرجع HOLD بدل إيقاف البوت
            self.log.error("خطأ في تحليل MeanReversion: %s", exc)
            return self.hold(self.symbol, f"خطأ تحليلي: {exc}")

    def _build_signal(
        self,
        side: SignalType,
        entry: float,
        mb: float,
        atr: float,
        rsi: float,
        pct_b: float,
        indicators: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        بناء إشارة قابلة للتنفيذ مع SL ديناميكي (ATR) و TP نحو المتوسط،
        مع فرض حدّ أدنى لنسبة العائد/المخاطرة (R:R).
        """
        # مضاعف ATR يتغيّر حسب نظام التقلّب (النظرية 23):
        # نعتبر السوق "عالي التقلّب" إذا تجاوز ATR نسبة من السعر.
        high_vol = atr > (entry * 0.004)  # ~0.4% من السعر كعتبة تقريبية
        mult = (
            settings.ATR_SL_MULTIPLIER_HIGH_VOL if high_vol else settings.ATR_SL_MULTIPLIER
        )
        sl_dist = atr * mult
        min_rr = settings.MIN_RISK_REWARD

        if side == SignalType.BUY:
            sl = entry - sl_dist
            tp = mb  # الهدف: العودة إلى المتوسط
            # نضمن أن يحقق الهدف حدّ R:R الأدنى، وإلا نمدّده.
            if (tp - entry) < min_rr * sl_dist:
                tp = entry + min_rr * sl_dist
        else:  # SELL
            sl = entry + sl_dist
            tp = mb
            if (entry - tp) < min_rr * sl_dist:
                tp = entry - min_rr * sl_dist

        # المسافات بالنقاط (pips) للعرض والتحقق من حدود الهدف.
        tp_pips = abs(tp - entry) / settings.PIP_SIZE
        sl_pips = abs(entry - sl) / settings.PIP_SIZE

        # درجة الثقة [0.5 - 0.95]: تمزج شدّة RSI مع مدى تجاوز النطاق (%B).
        if side == SignalType.BUY:
            rsi_strength = max(0.0, (self.rsi_oversold - rsi) / max(self.rsi_oversold, 1))
            band_strength = float(np.clip(-pct_b, 0.0, 1.0))  # %B سالب = تحت السفلي
        else:
            rsi_strength = max(
                0.0, (rsi - self.rsi_overbought) / max(100 - self.rsi_overbought, 1)
            )
            band_strength = float(np.clip(pct_b - 1.0, 0.0, 1.0))  # %B>1 = فوق العلوي
        confidence = float(np.clip(0.5 + 0.45 * (0.5 * rsi_strength + 0.5 * band_strength), 0.5, 0.95))

        reason = (
            f"{'تشبّع بيعي' if side == SignalType.BUY else 'تشبّع شرائي'} "
            f"(RSI={rsi:.1f}) ولمس النطاق "
            f"{'السفلي' if side == SignalType.BUY else 'العلوي'} لبولينجر "
            f"→ ارتداد متوقع نحو المتوسط ({mb:.2f}). "
            f"TP≈{tp_pips:.0f} نقطة | SL≈{sl_pips:.0f} نقطة"
            f"{' | تقلّب عالٍ' if high_vol else ''}"
        )

        indicators = {**indicators, "tp_pips": round(tp_pips, 1), "sl_pips": round(sl_pips, 1)}

        return Signal(
            signal_type=side,
            symbol=self.symbol,
            entry=round(entry, 3),
            sl=round(sl, 3),
            tp=round(tp, 3),
            confidence=confidence,
            reason=reason,
            engine=self.name,
            indicators=indicators,
        ).to_dict()


# --------------------------------------------------------------------------- #
# اختبار مستقل على بيانات وهمية: python -m engines.mean_reversion
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("=" * 60)
    print("اختبار MeanReversionEngine على بيانات وهمية (dummy data)")
    print("=" * 60)

    # نولّد سلسلة سعرية وهمية: اتجاه جيبي (mean-reverting) + ضوضاء عشوائية.
    rng = np.random.default_rng(42)
    n = 300
    t = np.arange(n)
    base = 2300 + 40 * np.sin(2 * np.pi * t / 50)          # موجة حول 2300
    noise = rng.normal(0, 5, n).cumsum() * 0.3             # ضوضاء ممشّاة
    close = base + noise

    # بناء OHLC منطقي حول سعر الإغلاق.
    high = close + rng.uniform(1, 6, n)
    low = close - rng.uniform(1, 6, n)
    open_ = close + rng.uniform(-3, 3, n)
    volume = rng.integers(50, 500, n)

    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    dummy = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )

    engine = MeanReversionEngine()
    print(f"\nالمحرك: {engine!r}")
    print(f"الحد الأدنى للصفوف: {engine.min_rows}")

    # 1) إشارة على آخر شمعة من البيانات الوهمية.
    result = engine.analyze(dummy)
    print("\n--- نتيجة التحليل على آخر شمعة ---")
    for k, v in result.items():
        print(f"  {k}: {v}")

    # 2) اختبار حالة شراء مفتعَلة (سعر منخفض جداً ⇒ تشبّع بيعي).
    forced = dummy.copy()
    forced.iloc[-1, forced.columns.get_loc("close")] = float(forced["low"].min()) - 50
    forced.iloc[-1, forced.columns.get_loc("low")] = float(forced["low"].min()) - 55
    buy_test = engine.analyze(forced)
    print("\n--- اختبار حالة شراء مفتعلة ---")
    print(f"  الإشارة: {buy_test['signal']} | السبب: {buy_test['reason']}")

    # 3) فحص المؤشرات الأخيرة للتأكد من صحة الحساب.
    ind = engine.compute_indicators(dummy)
    print("\n--- آخر 3 صفوف من المؤشرات ---")
    print(ind[["close", "mb", "upper", "lower", "rsi", "atr", "pct_b"]].tail(3).round(2))

    print("\n✅ انتهى الاختبار بنجاح.")
