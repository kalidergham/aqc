"""
حزمة المحركات (engines)
========================

كل محرك (Engine) هو استراتيجية تداول مستقلة ترث من EngineBase.
المحركات المتوفرة:
    - EngineBase        : الكلاس المجرّد الأساس لكل المحركات.
    - MeanReversionEngine : محرك الارتداد إلى المتوسط (Bollinger Bands + RSI).
    - TrendFollowingEngine: محرك اتباع الاتجاه (EMA متعدد الفريمات) [قيد التطوير].
"""

from .engine_base import EngineBase, Signal, SignalType

__all__ = ["EngineBase", "Signal", "SignalType"]
