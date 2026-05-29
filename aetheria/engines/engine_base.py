"""
engines/engine_base.py
======================

الكلاس المجرّد الأساس (Abstract Base Class) لكل محركات التداول في أثيريا،
بالإضافة إلى الهياكل الموحّدة للإشارة (Signal / SignalType).

فلسفة التصميم (Engine Pattern):
    كل استراتيجية = محرك يرث ``EngineBase`` ويُلزَم بتنفيذ:
        - الخاصية ``name``    : اسم المحرك.
        - الخاصية ``version`` : إصدار المحرك.
        - الدالة  ``analyze`` : تحليل DataFrame وإرجاع dict موحّد للإشارة.
    وبهذا يصبح كل محرك قابلاً للتبديل (polymorphism) داخل البوت.

ملاحظة تقنية: نستورد pandas فقط عند فحص الأنواع (TYPE_CHECKING) ولا نعتمد
عليه وقت التشغيل داخل هذا الملف — ليبقى الأساس خفيفاً وقابلاً للاختبار
المستقل، بينما تستورد المحركات الفعلية pandas/numpy فعلياً.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:  # تُقيَّم فقط أثناء فحص الأنواع، لا وقت التشغيل
    import pandas as pd

logger = logging.getLogger(__name__)

# الأعمدة الإلزامية في أي DataFrame يُمرّر للمحركات (بأحرف صغيرة).
REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")


class SignalType(str, Enum):
    """نوع الإشارة الصادرة عن المحرك."""

    BUY = "BUY"     # إشارة شراء
    SELL = "SELL"   # إشارة بيع
    HOLD = "HOLD"   # لا صفقة (انتظار)


@dataclass
class Signal:
    """
    تمثيل موحّد لإشارة تداول صادرة عن أي محرك.

    Attributes:
        signal_type : نوع الإشارة (BUY/SELL/HOLD).
        symbol      : رمز الزوج (مثل XAUUSD).
        entry       : سعر الدخول المقترح.
        sl          : وقف الخسارة (Stop Loss).
        tp          : جني الأرباح (Take Profit).
        confidence  : درجة الثقة [0.0 - 1.0].
        reason      : شرح نصّي مختصر لسبب الإشارة.
        engine      : اسم المحرك المُصدِر.
        timestamp   : وقت توليد الإشارة.
        indicators  : قاموس بقيم المؤشرات الداعمة (للشفافية والتدقيق).
    """

    signal_type: SignalType = SignalType.HOLD
    symbol: str = ""
    entry: Optional[float] = None
    sl: Optional[float] = None
    tp: Optional[float] = None
    confidence: float = 0.0
    reason: str = ""
    engine: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)
    indicators: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """
        تحويل الإشارة إلى قاموس موحّد — وهو الصيغة التي تُرجعها analyze().

        المفاتيح متوافقة مع utils.telegram_utils.format_signal().
        """
        return {
            "signal": self.signal_type.value,
            "symbol": self.symbol,
            "entry": self.entry,
            "sl": self.sl,
            "tp": self.tp,
            "confidence": self.confidence,
            "reason": self.reason,
            "engine": self.engine,
            "timestamp": self.timestamp.isoformat(),
            "indicators": self.indicators,
        }

    @property
    def is_actionable(self) -> bool:
        """هل الإشارة قابلة للتنفيذ (شراء/بيع وليست انتظاراً)؟"""
        return self.signal_type in (SignalType.BUY, SignalType.SELL)


class EngineBase(ABC):
    """
    الكلاس المجرّد الأساس لكل محركات التداول.

    على كل محرك فرعي تنفيذ ``name`` و ``version`` و ``analyze``. توفّر هذه
    الفئة منطقاً مشتركاً: التحقق من صحة البيانات (validate_data) وبناء
    إشارة انتظار (hold).

    Attributes:
        min_rows: أقل عدد صفوف مطلوب لتحليل موثوق (يُضبط من المحرك الفرعي).
    """

    #: أقل عدد شموع لازم لإجراء تحليل ذي معنى (قابل للتجاوز في الأبناء).
    min_rows: int = 50

    def __init__(self) -> None:
        """تهيئة أساسية مشتركة (مسجّل خاص باسم المحرك)."""
        # logger فرعي يحمل اسم المحرك لتسهيل تتبّع السجلات.
        self.log = logging.getLogger(f"aetheria.engine.{self.__class__.__name__}")

    # ----------------------------- خصائص مجرّدة ---------------------------- #
    @property
    @abstractmethod
    def name(self) -> str:
        """الاسم المقروء للمحرك (يجب تنفيذه في الأبناء)."""
        raise NotImplementedError

    @property
    @abstractmethod
    def version(self) -> str:
        """إصدار المحرك (يجب تنفيذه في الأبناء)."""
        raise NotImplementedError

    # ----------------------------- دالة مجرّدة ----------------------------- #
    @abstractmethod
    def analyze(self, df: "pd.DataFrame") -> Dict[str, Any]:
        """
        تحليل البيانات السعرية وإصدار إشارة.

        Args:
            df: DataFrame بأعمدة REQUIRED_COLUMNS وفهرس زمني تصاعدي.

        Returns:
            قاموس الإشارة الموحّد (مخرجات Signal.to_dict()).
        """
        raise NotImplementedError

    # --------------------------- منطق مشترك مساعد -------------------------- #
    def validate_data(self, df: "pd.DataFrame") -> bool:
        """
        التحقق من صحة الـ DataFrame المُدخل قبل التحليل.

        يفحص: عدم الفراغ، وجود الأعمدة الإلزامية، كفاية عدد الصفوف، وخلوّ
        أعمدة الأسعار من القيم المفقودة (NaN) — مع التحقق بأسلوب duck-typing
        حتى لا يعتمد الأساس على pandas مباشرةً.

        Args:
            df: البيانات المراد فحصها.

        Returns:
            True إذا كانت البيانات صالحة.

        Raises:
            ValueError: مع رسالة واضحة عند أي خلل في البيانات.
        """
        # 1) فحص عدم كون المدخل None.
        if df is None:
            raise ValueError("البيانات المُدخلة فارغة (None).")

        # 2) فحص أنّ الكائن يشبه DataFrame (يملك columns وطولاً).
        if not hasattr(df, "columns") or not hasattr(df, "__len__"):
            raise ValueError("المدخل ليس DataFrame صالحاً.")

        # 3) فحص الطول (كفاية عدد الصفوف).
        n = len(df)
        if n < self.min_rows:
            raise ValueError(
                f"عدد الصفوف ({n}) أقل من الحد الأدنى المطلوب ({self.min_rows})."
            )

        # 4) فحص وجود الأعمدة الإلزامية (مع توحيد الأحرف الصغيرة).
        cols = {str(c).lower() for c in df.columns}
        missing = [c for c in REQUIRED_COLUMNS if c not in cols]
        if missing:
            raise ValueError(f"أعمدة مفقودة في البيانات: {missing}")

        # 5) فحص القيم المفقودة في أعمدة الأسعار (إن كان الكائن يدعم isna).
        try:
            for col in ("open", "high", "low", "close"):
                series = df[col]
                if hasattr(series, "isna") and bool(series.isna().any()):
                    raise ValueError(f"العمود '{col}' يحتوي قيماً مفقودة (NaN).")
        except ValueError:
            raise
        except Exception as exc:  # noqa: BLE001 - فحص NaN اختياري ولا يوقف العمل
            self.log.debug("تخطّي فحص NaN (الكائن لا يدعمه): %s", exc)

        return True

    def hold(self, symbol: str = "", reason: str = "لا توجد إشارة") -> Dict[str, Any]:
        """
        بناء إشارة انتظار (HOLD) جاهزة كقاموس.

        تُستخدم كقيمة إرجاع افتراضية عندما لا تتوفّر شروط الدخول.
        """
        return Signal(
            signal_type=SignalType.HOLD,
            symbol=symbol,
            reason=reason,
            engine=self.name,
            confidence=0.0,
        ).to_dict()

    def __repr__(self) -> str:  # تمثيل نصّي مفيد عند التصحيح
        return f"<{self.__class__.__name__} name='{self.name}' v{self.version}>"


# --------------------------------------------------------------------------- #
# اختبار مستقل: python -m engines.engine_base
# (يعمل دون pandas — يستخدم كائناً وهمياً يحاكي DataFrame)
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # كائن وهمي خفيف يحاكي الحد الأدنى من واجهة DataFrame للاختبار.
    class _FakeDF:
        def __init__(self, columns, rows):
            self._columns = columns
            self._rows = rows

        @property
        def columns(self):
            return self._columns

        def __len__(self):
            return self._rows

    # محرك تجريبي ملموس لاختبار آليات الأساس.
    class _DummyEngine(EngineBase):
        min_rows = 10

        @property
        def name(self) -> str:
            return "DummyEngine"

        @property
        def version(self) -> str:
            return "0.0.1"

        def analyze(self, df):
            self.validate_data(df)
            # إشارة شراء وهمية لإثبات بناء Signal.
            return Signal(
                signal_type=SignalType.BUY,
                symbol="XAUUSD",
                entry=2300.0,
                sl=2296.0,
                tp=2306.0,
                confidence=0.75,
                reason="اختبار",
                engine=self.name,
            ).to_dict()

    engine = _DummyEngine()
    print(f"إنشاء المحرك: {engine!r}")

    # 1) منع إنشاء الكلاس المجرّد مباشرةً.
    try:
        EngineBase()  # type: ignore[abstract]
        print("❌ خطأ: تم إنشاء ABC (يُفترض أن يُمنع)")
    except TypeError:
        print("✅ مُنع إنشاء EngineBase المجرّد مباشرةً (صحيح).")

    # 2) بيانات صالحة.
    good = _FakeDF(["Open", "High", "Low", "Close", "Volume"], 100)
    assert engine.validate_data(good) is True
    print("✅ validate_data نجح على بيانات صالحة.")

    # 3) أعمدة ناقصة.
    try:
        engine.validate_data(_FakeDF(["Open", "Close"], 100))
        print("❌ خطأ: لم يكتشف الأعمدة الناقصة")
    except ValueError as e:
        print(f"✅ كشف الأعمدة الناقصة: {e}")

    # 4) صفوف غير كافية.
    try:
        engine.validate_data(_FakeDF(["Open", "High", "Low", "Close", "Volume"], 3))
        print("❌ خطأ: لم يكتشف نقص الصفوف")
    except ValueError as e:
        print(f"✅ كشف نقص الصفوف: {e}")

    # 5) إشارة HOLD وإشارة BUY.
    print("\nإشارة انتظار:", engine.hold("XAUUSD"))
    print("إشارة تحليل  :", engine.analyze(good))
