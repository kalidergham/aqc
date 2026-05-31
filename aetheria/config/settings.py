"""
config/settings.py
==================

الإعدادات المركزية لبوت أثيريا (Aetheria v1) — نسخة سطح المكتب (Windows).

البوت يعمل على الحاسوب (Windows) عبر مكتبة MetaTrader5 الرسمية مباشرةً
(بدون MetaApi)، وواجهة Telegram عبر pyTelegramBotAPI (telebot).

كل الثوابت ومفاتيح الـ API تُجمع هنا في مكان واحد. القيم الحسّاسة تُقرأ من
*متغيّرات البيئة* أولاً ثم تسقط على placeholder افتراضي — أأمن من كتابة
الأسرار داخل الكود.

طريقة الضبط على Windows (PowerShell):
    setx AETHERIA_TG_TOKEN        "123456:ABC..."
    setx AETHERIA_ADMIN_IDS       "123456789,987654321"
    setx AETHERIA_MT5_LOGIN       "51234567"
    setx AETHERIA_MT5_PASSWORD    "كلمة_سر_التداول"
    setx AETHERIA_MT5_SERVER      "MetaQuotes-Demo"
    setx AETHERIA_MT5_PATH        "C:\\Program Files\\MetaTrader 5\\terminal64.exe"
(أعد فتح نافذة الأوامر بعد setx حتى تُحمّل المتغيّرات.)
"""

from __future__ import annotations

import os

# =========================================================================== #
#  معلومات عامة
# =========================================================================== #
APP_NAME: str = "Aetheria"
APP_VERSION: str = "1.1.0"  # نسخة سطح المكتب (MetaTrader5 + telebot)


def _get_int_list(env_key: str, default: str = "") -> list[int]:
    """قراءة قائمة أعداد صحيحة من متغيّر بيئة مفصول بفواصل (للأدمن)."""
    raw = os.getenv(env_key, default)
    ids: list[int] = []
    for part in raw.replace(" ", "").split(","):
        if part.isdigit():
            ids.append(int(part))
    return ids


# =========================================================================== #
#  1) إعدادات Telegram
# =========================================================================== #
# توكن البوت من BotFather. الأفضل ضبطه عبر متغيّر البيئة AETHERIA_TG_TOKEN.
# ⚠️ أمان: تجنّب وضع التوكن هنا مباشرةً ورفعه إلى GitHub. لو تسرّب، أعد توليده
#          من BotFather عبر /revoke. القيمة أدناه افتراضية ويتجاوزها متغيّر البيئة.
TELEGRAM_TOKEN: str = os.getenv(
    "AETHERIA_TG_TOKEN",
    "8634789358:AAFBFxlcxacJpjCG3XgWfzs_tQANPaf2lgQ",  # افتراضي — يُفضّل استخدام env
)

# قائمة معرّفات الأدمن (المصرّح لهم بالتحكم الكامل ولوحة الأدمن).
# تُضبط عبر AETHERIA_ADMIN_IDS = "111,222" (مفصولة بفواصل).
ADMIN_IDS: list[int] = _get_int_list("AETHERIA_ADMIN_IDS", "6521892266")

# توافق رجعي: أول أدمن يُعتبر صاحب تنبيهات الأخطاء (0 = غير محدد).
ADMIN_CHAT_ID: int = ADMIN_IDS[0] if ADMIN_IDS else int(
    os.getenv("AETHERIA_ADMIN_CHAT_ID", "0")
)

# نمط تنسيق الرسائل الافتراضي ("Markdown" / "HTML" / None).
TELEGRAM_PARSE_MODE: str = "Markdown"

# الحد الأقصى لطول رسالة تلكرام (قيد المنصة الرسمي).
TELEGRAM_MAX_MESSAGE_LEN: int = 4096

# =========================================================================== #
#  2) إعدادات MetaTrader 5 (الاتصال المباشر عبر المكتبة الرسمية)
# =========================================================================== #
# رقم حساب التداول (Login). يُفضّل ضبطه عبر AETHERIA_MT5_LOGIN.
MT5_LOGIN: int = int(os.getenv("AETHERIA_MT5_LOGIN", "0"))
# كلمة سرّ التداول (Trader password).
MT5_PASSWORD: str = os.getenv("AETHERIA_MT5_PASSWORD", "")
# اسم خادم الوسيط (مثل "MetaQuotes-Demo" أو "ICMarkets-Demo").
MT5_SERVER: str = os.getenv("AETHERIA_MT5_SERVER", "")
# مسار ملف terminal64.exe (اختياري — يُترك فارغاً لاكتشافه تلقائياً).
MT5_PATH: str = os.getenv("AETHERIA_MT5_PATH", "")

# خريطة فريم أثيريا → اسم ثابت الفريم في مكتبة MetaTrader5.
# نُخزّن الاسم كنص ونحوّله لاحقاً عبر getattr(mt5, name) داخل live_fetcher،
# حتى لا نضطر لاستيراد MetaTrader5 هنا (فهي تعمل على Windows فقط).
MT5_TIMEFRAME_MAP: dict[str, str] = {
    "1m": "TIMEFRAME_M1",
    "5m": "TIMEFRAME_M5",
    "15m": "TIMEFRAME_M15",
    "30m": "TIMEFRAME_M30",
    "1h": "TIMEFRAME_H1",
    "4h": "TIMEFRAME_H4",
    "1d": "TIMEFRAME_D1",
}

# =========================================================================== #
#  3) روابط البيانات التاريخية (CSV على GitHub) — للباكتيست
# =========================================================================== #
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
SUPPORTED_SYMBOLS: list[str] = ["XAUUSD"]
DEFAULT_SYMBOL: str = "XAUUSD"

# =========================================================================== #
#  5) إعدادات المخاطر والأهداف (SL / TP)
# =========================================================================== #
# قيمة النقطة الواحدة للذهب (pip) — على معظم الوسطاء حركة 0.1$ = نقطة واحدة.
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
#  6) إعدادات التشغيل اللحظي (Live Trading)
# =========================================================================== #
# فترة فحص السوق بالثواني في وضع المراقبة اللحظية.
LIVE_POLL_INTERVAL: int = int(os.getenv("AETHERIA_POLL_INTERVAL", "60"))

# وضع التنفيذ:
#   False = شبه أوتوماتيكي (يرسل الإشارة وينتظر زر تأكيد) — موصى به للأمان.
#   True  = أوتوماتيكي كامل (ينفّذ الصفقة فور الإشارة دون تأكيد).
AUTO_TRADE: bool = os.getenv("AETHERIA_AUTO_TRADE", "false").lower() == "true"

# حجم اللوت الافتراضي عند التنفيذ (يُستخدم إن تعذّر حساب الحجم من المخاطرة).
DEFAULT_LOT: float = float(os.getenv("AETHERIA_DEFAULT_LOT", "0.01"))

# الرقم السحري (Magic Number) لتمييز صفقات البوت في MT5.
MAGIC_NUMBER: int = int(os.getenv("AETHERIA_MAGIC", "20240615"))

# أقصى انزلاق سعري مسموح (deviation) بالنقاط عند تنفيذ أمر السوق.
ORDER_DEVIATION: int = int(os.getenv("AETHERIA_DEVIATION", "20"))

# الفريم الافتراضي للتحليل اللحظي.
DEFAULT_LIVE_TIMEFRAME: str = "15m"

# =========================================================================== #
#  7) إعدادات الباكتيست
# =========================================================================== #
SPREAD_PIPS: float = 2.0           # السبريد التقديري للذهب بالنقاط
COMMISSION_PER_LOT: float = 0.0    # عمولة لكل لوت (إن وُجدت)
INITIAL_BALANCE: float = 10_000.0  # رأس المال الابتدائي للباكتيست
RISK_FREE_RATE: float = 0.0        # معدل خالٍ من المخاطر (لحساب Sharpe)

# نطاق السنوات المتاحة للاختيار في أزرار الباكتيست (البيانات: 2004→2026).
BACKTEST_MIN_YEAR: int = 2004
BACKTEST_MAX_YEAR: int = 2026

# =========================================================================== #
#  8) معاملات المحركات الافتراضية
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
    "adx_period": 14,       # فترة ADX لتأكيد قوة الاتجاه
    "adx_threshold": 20,    # أدنى قيمة ADX لاعتبار الاتجاه قوياً
}

# المحركات المفعّلة افتراضياً عند الإقلاع (يمكن تبديلها من قائمة الإعدادات).
DEFAULT_ENABLED_ENGINES: list[str] = ["MeanReversion"]

# =========================================================================== #
#  9) إعدادات التسجيل (Logging)
# =========================================================================== #
LOG_LEVEL: str = os.getenv("AETHERIA_LOG_LEVEL", "INFO")
LOG_FORMAT: str = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
LOG_FILE: str = os.getenv("AETHERIA_LOG_FILE", "aetheria.log")


def is_admin(user_id: int) -> bool:
    """هل المستخدم ضمن قائمة الأدمن المصرّح لهم؟"""
    return user_id in ADMIN_IDS


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
    if not ADMIN_IDS:
        warnings.append("⚠️ ADMIN_IDS غير محدد (لوحة الأدمن لن تعمل لأحد).")
    if MT5_LOGIN == 0 or not MT5_PASSWORD or not MT5_SERVER:
        warnings.append(
            "⚠️ إعدادات MetaTrader5 ناقصة (LOGIN/PASSWORD/SERVER) — "
            "التداول اللحظي معطّل، لكن الباكتيست يعمل."
        )
    if MIN_TP_PIPS > MAX_TP_PIPS:
        warnings.append("⚠️ MIN_TP_PIPS أكبر من MAX_TP_PIPS — راجع الإعدادات.")
    return warnings


# --------------------------------------------------------------------------- #
# اختبار مستقل: python -m config.settings
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    print(f"{APP_NAME} v{APP_VERSION} — فحص الإعدادات (نسخة Windows / MT5)")
    print("-" * 55)
    print(f"الأزواج المدعومة : {SUPPORTED_SYMBOLS}")
    print(f"الفريمات         : {SUPPORTED_TIMEFRAMES}")
    print(f"عدد الأدمن        : {len(ADMIN_IDS)}")
    print(f"وضع التنفيذ       : {'أوتوماتيكي' if AUTO_TRADE else 'شبه أوتوماتيكي (تأكيد يدوي)'}")
    print(f"الهدف الافتراضي  : {DEFAULT_TP_PIPS} نقطة (مدى {MIN_TP_PIPS}-{MAX_TP_PIPS})")
    print(f"وقف الخسارة      : {DEFAULT_SL_PIPS} نقطة")
    print(f"خريطة فريمات MT5 : {MT5_TIMEFRAME_MAP}")
    print("-" * 55)
    issues = validate_settings()
    if issues:
        print("تحذيرات:")
        for w in issues:
            print("  " + w)
    else:
        print("✅ كل الإعدادات الحرجة مضبوطة.")
