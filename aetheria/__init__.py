"""
Aetheria Quant Capital (AQC) - بوت التداول الكمي "أثيريا"
=========================================================

حزمة Python لبوت تداول شبه أوتوماتيكي (Semi-Automated) يعتمد على التحليل
الكمي البحت (Pure Quantitative Analysis). مصمّم للعمل على بيئة Termux (Android)
عبر واجهة Telegram، ويتصل بـ MetaTrader 5 من خلال MetaApi (REST/SDK).

البنية الهندسية: نمط "المحركات المستقلة" (Engine Pattern) - كل استراتيجية
تداول هي محرك مستقل يرث من EngineBase ويُختبر بشكل منفصل.

المؤلف : Aetheria Quant Capital
الإصدار: 1.0.0 (v1)
"""

__version__ = "1.0.0"
__author__ = "Aetheria Quant Capital (AQC)"
