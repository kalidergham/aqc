"""
config/settings.py
==================

الإعدادات المركزية لبوت أثيريا (Aetheria v1).

كل الثوابت ومفاتيح الـ API تُجمع هنا في مكان واحد لسهولة الصيانة. القيم
الحسّاسة (التوكنات) تُقرأ من *متغيّرات البيئة* أولاً، ثم تسقط على قيمة
placeholder افتراضية — هذا أأمن من كتابة الأسرار داخل الكود (خصوصاً عند
رفع المشروع إلى GitHub).

طريقة الضبط على Termux (موصى بها):
    export AETHERIA_TG_TOKEN="123456:ABC..."
    export AETHERIA_METAAPI_TOKEN="eyJ..."
    export AETHERIA_METAAPI_ACCOUNT_ID="xxxxxxxx-xxxx-..."
    export AETHERIA_ADMIN_CHAT_ID="123456789"
"""

from __future__ import annotations

import os

# =========================================================================== #
#  معلومات عامة
# =========================================================================== #
APP_NAME: str = "Aetheria"
APP_VERSION: str = "1.0.0"

# =========================================================================== #
#  1) إعدادات Telegram
# =========================================================================== #
# توكن البوت من BotFather. الأفضل ضبطه عبر متغيّر البيئة AETHERIA_TG_TOKEN.
TELEGRAM_TOKEN: str = os.getenv(
    "AETHERIA_TG_TOKEN",
    "PUT_YOUR_TELEGRAM_BOT_TOKEN_HERE",  # placeholder — غيّره أو استخدم env
)

# معرّف محادثة المدير (لاستقبال تنبيهات الأخطاء والإشارات). 0 = غير محدد.
ADMIN_CHAT_ID: int = int(os.getenv("AETHERIA_ADMIN_CHAT_ID", "0"))

# نمط تنسيق الرسائل الافتراضي ("Markdown" / "HTML" / None).
TELEGRAM_PARSE_MODE: str = "Markdown"

# الحد الأقصى لطول رسالة تلكرام (قيد المنصة الرسمي).
TELEGRAM_MAX_MESSAGE_LEN: int = 4096

# =========================================================================== #
#  2) إعدادات MetaApi (الجسر إلى MetaTrader 5)
# =========================================================================== #
# نستخدم MetaApi لأن مكتبة MetaTrader5 الرسمية تعمل على Windows فقط،
# بينما MetaApi SDK متوافق مع Linux/Termux عبر REST/WebSocket.
METAAPI_TOKEN: str = os.getenv(
    "AETHERIA_METAAPI_TOKEN",
    "PUT_YOUR_METAAPI_TOKEN_HERE",  # placeholder
)
# معرّف حساب MT5 المُجهّز داخل لوحة تحكم MetaApi.
METAAPI_ACCOUNT_ID: str = os.getenv(
    "AETHERIA_METAAPI_ACCOUNT_ID",
    "PUT_YOUR_METAAPI_ACCOUNT_ID_HERE",  # placeholder
)
# منطقة الخادم الأقرب (latency). أمثلة: "new-york", "london", "singapore".
METAAPI_REGION: str = os.getenv("AETHERIA_METAAPI_REGION", "new-york")
# نطاق MetaApi (يُترك افتراضياً إلا إذا طلب الدعم خلاف ذلك).
METAAPI_DOMAIN: str = os.getenv("AETHERIA_METAAPI_DOMAIN", "agiliumtrade.agiliumtrade.ai")

# =========================================================================== #
#  3) روابط البيانات التاريخية (CSV على GitHub)
# =========================================================================== #
# قاعدة الرابط الخام لملفات المستودع. عدّلها لو غيّرت المستخدم/المستودع/الفرع.
GITHUB_OWNER: str = "kalidergham"
GITHUB_REPO: str = "aqc"
GITHUB_BRANCH: str = "main"
GITHUB_RAW_BASE: str = (
    f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/{GITHUB_BRANCH}"
)

# خريطة الفريم الزمني → رابط ملف CSV المقابل.
CSV_URLS: dict[str, str] = {
    "15m": f"{GITHUB_RAW_BASE}/XAU_15m_data.csv",
    "1h": f"{GITHUB_RAW_BASE}/XAU_1h_data.csv",
    "4h": f"{GITHUB_RAW_BASE}/XAU_4h_data.csv",
}

# مسارات الملفات المحلية (للاختبار دون إنترنت) — نسبةً لجذر المستودع.
CSV_LOCAL_PATHS: dict[str, str] = {
    "15m": "XAU_15m_data.csv",
    "1h": "XAU_1h_data.csv",
    "4h": "XAU_4h_data.csv",
}

# الفريمات المدعومة (تُستخدم لبناء أزرار inline في البوت).
SUPPORTED_TIMEFRAMES: list[str] = ["15m", "1h", "4h"]

# =========================================================================== #
#  4) الأزواج المدعومة
# =========================================================================== #
# الزوج الأساسي حالياً هو الذهب. القائمة قابلة للتوسعة لاحقاً.
SUPPORTED_SYMBOLS: list[str] = ["XAUUSD"]
DEFAULT_SYMBOL: str = "XAUUSD"

# =========================================================================== #
#  5) إعدادات المخاطر والأهداف (SL / TP)
# =========================================================================== #
# قيمة النقطة الواحدة للذهب (pip) — على معظم الوسطاء حركة 0.1$ = نقطة واحدة.
# عدّلها بما يطابق تعريف وسيطك.
PIP_SIZE: float = 0.1

# أهداف الصفقة الافتراضية بالنقاط (وفق متطلب المستخدم: 40–100 نقطة).
DEFAULT_TP_PIPS: int = 60          # الهدف الافتراضي
MIN_TP_PIPS: int = 40              # أدنى هدف مقبول
MAX_TP_PIPS: int = 100             # أقصى هدف
DEFAULT_SL_PIPS: int = 40          # وقف الخسارة الافتراضي

# إدارة المخاطر الديناميكية (تجسيد النظرية 23 — صمّام الأمان):
ATR_PERIOD: int = 14               # فترة حساب ATR
ATR_SL_MULTIPLIER: float = 2.0     # مضاعف ATR لوقف الخسارة (أسواق هادئة)
ATR_SL_MULTIPLIER_HIGH_VOL: float = 3.5  # مضاعف في الأسواق عالية التقلب
MIN_RISK_REWARD: float = 1.3       # أدنى نسبة عائد/مخاطرة مقبولة (R:R)

RISK_PER_TRADE_PCT: float = 1.0    # نسبة المخاطرة من رأس المال لكل صفقة (%)
MAX_TRADES_PER_DAY: int = 10       # حد أقصى لعدد الصفقات اليومية
MAX_DAILY_LOSS_PCT: float = 5.0    # حد الخسارة اليومي — يوقف البوت لو تجاوزناه

# =========================================================================== #
#  6) إعدادات الباكتيست
# =========================================================================== #
# التكاليف الواقعية (مهمة جداً لتقييم صادق للأداء).
SPREAD_PIPS: float = 2.0           # السبريد التقديري للذهب بالنقاط
COMMISSION_PER_LOT: float = 0.0    # عمولة لكل لوت (إن وُجدت)
INITIAL_BALANCE: float = 10_000.0  # رأس المال الابتدائي للباكتيست
RISK_FREE_RATE: float = 0.0        # معدل خالٍ من المخاطر (لحساب Sharpe)

# نطاق السنوات المتاحة للاختيار في أزرار الباكتيست (البيانات: 2004→2026).
BACKTEST_MIN_YEAR: int = 2004
BACKTEST_MAX_YEAR: int = 2026

# =========================================================================== #
#  7) معاملات المحركات الافتراضية
# =========================================================================== #
# محرك الارتداد للمتوسط (Bollinger Bands + RSI).
MEAN_REVERSION_PARAMS: dict[str, float] = {
    "bb_period": 20,        # فترة المتوسط المتحرك لبولينجر
    "bb_std": 2.0,          # عدد الانحرافات المعيارية للنطاقات
    "rsi_period": 14,       # فترة مؤشر RSI
    "rsi_oversold": 30.0,   # حد التشبع البيعي (إشارة شراء)
    "rsi_overbought": 70.0, # حد التشبع الشرائي (إشارة بيع)
}

# محرك اتباع الاتجاه (EMA).
TREND_FOLLOWING_PARAMS: dict[str, int] = {
    "ema_fast": 50,
    "ema_slow": 200,
}

# =========================================================================== #
#  8) إعدادات التسجيل (Logging)
# =========================================================================== #
LOG_LEVEL: str = os.getenv("AETHERIA_LOG_LEVEL", "INFO")
LOG_FORMAT: str = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def validate_settings() -> list[str]:
    """
    فحص بسيط للإعدادات الحرجة قبل التشغيل.

    Returns:
        قائمة بالتحذيرات (فارغة = كل شيء جاهز). لا ترفع استثناءً حتى لا
        توقف البوت، بل تُبلّغ المستخدم بما ينقصه.
    """
    warnings: list[str] = []
    if "PUT_YOUR" in TELEGRAM_TOKEN:
        warnings.append("⚠️ TELEGRAM_TOKEN غير مضبوط (استخدم AETHERIA_TG_TOKEN).")
    if ADMIN_CHAT_ID == 0:
        warnings.append("⚠️ ADMIN_CHAT_ID غير محدد (لن تصل تنبيهات الأخطاء).")
    if "PUT_YOUR" in METAAPI_TOKEN:
        warnings.append("⚠️ METAAPI_TOKEN غير مضبوط (التداول اللحظي معطّل).")
    if MIN_TP_PIPS > MAX_TP_PIPS:
        warnings.append("⚠️ MIN_TP_PIPS أكبر من MAX_TP_PIPS — راجع الإعدادات.")
    return warnings


# --------------------------------------------------------------------------- #
# اختبار مستقل: python -m config.settings
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    print(f"{APP_NAME} v{APP_VERSION} — فحص الإعدادات")
    print("-" * 50)
    print(f"الأزواج المدعومة : {SUPPORTED_SYMBOLS}")
    print(f"الفريمات         : {SUPPORTED_TIMEFRAMES}")
    print(f"روابط CSV        :")
    for tf, url in CSV_URLS.items():
        print(f"   {tf}: {url}")
    print(f"الهدف الافتراضي  : {DEFAULT_TP_PIPS} نقطة (مدى {MIN_TP_PIPS}-{MAX_TP_PIPS})")
    print(f"وقف الخسارة      : {DEFAULT_SL_PIPS} نقطة")
    print("-" * 50)
    issues = validate_settings()
    if issues:
        print("تحذيرات:")
        for w in issues:
            print("  " + w)
    else:
        print("✅ كل الإعدادات الحرجة مضبوطة.")
