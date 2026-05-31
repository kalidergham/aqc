"""
حزمة المحركات (engines)
========================

كل محرك (Engine) هو استراتيجية تداول مستقلة ترث من EngineBase.

المحركات المتوفرة:
    - EngineBase            : الكلاس المجرّد الأساس لكل المحركات.
    - MeanReversionEngine   : محرك الارتداد للمتوسط (Bollinger Bands + RSI).
    - TrendFollowingEngine  : محرك اتباع الاتجاه (EMA + ADX).

ENGINE_REGISTRY: خريطة الاسم → كلاس المحرك، تُستخدم لبناء المحركات ديناميكياً
من واجهة البوت (أزرار اختيار/تفعيل المحركات).
"""

from .engine_base import EngineBase, Signal, SignalType
from .mean_reversion import MeanReversionEngine
from .trend_following import TrendFollowingEngine

# سجلّ المحركات: الاسم (كما تعرضه الأزرار) → الكلاس.
ENGINE_REGISTRY: dict[str, type[EngineBase]] = {
    "MeanReversion": MeanReversionEngine,
    "TrendFollowing": TrendFollowingEngine,
}


def build_engine(name: str, **kwargs) -> EngineBase:
    """
    إنشاء نسخة من محرك حسب اسمه.

    Args:
        name: اسم المحرك (مفتاح في ENGINE_REGISTRY).
        **kwargs: معاملات تُمرَّر لمُنشئ المحرك.

    Returns:
        نسخة محرك جاهزة.

    Raises:
        KeyError: إذا كان الاسم غير معروف.
    """
    if name not in ENGINE_REGISTRY:
        raise KeyError(f"محرك غير معروف: '{name}'. المتاح: {list(ENGINE_REGISTRY)}")
    return ENGINE_REGISTRY[name](**kwargs)


__all__ = [
    "EngineBase",
    "Signal",
    "SignalType",
    "MeanReversionEngine",
    "TrendFollowingEngine",
    "ENGINE_REGISTRY",
    "build_engine",
]
