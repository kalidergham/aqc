"""
data/live_fetcher.py
====================

جلب البيانات اللحظية (Live) من منصة MetaTrader 5 عبر المكتبة الرسمية
``MetaTrader5`` مباشرةً (تعمل على Windows). لا حاجة لـ MetaApi إطلاقاً.

المسؤوليات:
    - فتح/إغلاق الاتصال بحساب MT5 (initialize + login).
    - جلب آخر N شمعة لزوج وفريم محددين كـ pandas.DataFrame موحّد
      (نفس صيغة csv_fetcher: open/high/low/close/volume بفهرس زمني).
    - جلب آخر سعر (tick) ومعلومات الحساب والرمز (يستخدمها محرك التداول).

ملاحظة تقنية: نستورد MetaTrader5 بأسلوب "دفاعي" (try/except) حتى يبقى هذا
الملف قابلاً للاستيراد والفحص على أنظمة غير Windows (مثل بيئة التطوير/CI)،
بينما يعمل فعلياً عند توفّر المكتبة + المنصة على Windows.
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from config import settings

logger = logging.getLogger(__name__)

# --- استيراد دفاعي لمكتبة MetaTrader5 (Windows فقط) ---
try:
    import MetaTrader5 as mt5  # type: ignore

    MT5_AVAILABLE = True
except Exception as _exc:  # noqa: BLE001 - قد تغيب المكتبة على لينكس
    mt5 = None  # type: ignore
    MT5_AVAILABLE = False
    logger.warning("مكتبة MetaTrader5 غير متاحة هنا (%s). التداول اللحظي معطّل.", _exc)

# الأعمدة الموحّدة المسلّمة للمحركات.
STANDARD_COLUMNS = ["open", "high", "low", "close", "volume"]


class MT5NotAvailableError(RuntimeError):
    """يُرفع عند محاولة استخدام MT5 بينما المكتبة غير متاحة/غير متصلة."""


class LiveFetcher:
    """
    موصل البيانات اللحظية مع MetaTrader 5.

    Attributes:
        connected: هل الاتصال مفتوح حالياً؟
    """

    def __init__(self) -> None:
        self.connected: bool = False

    # ------------------------------ الاتصال ------------------------------- #
    def connect(
        self,
        login: Optional[int] = None,
        password: Optional[str] = None,
        server: Optional[str] = None,
        path: Optional[str] = None,
    ) -> bool:
        """
        فتح اتصال بحساب MT5 (initialize ثم login).

        يقرأ القيم من الإعدادات افتراضياً مع السماح بتجاوزها.

        Returns:
            True عند نجاح الاتصال، وإلا False (مع تسجيل السبب).
        """
        if not MT5_AVAILABLE:
            logger.error("لا يمكن الاتصال: مكتبة MetaTrader5 غير مثبّتة (Windows فقط).")
            return False

        login = login if login is not None else settings.MT5_LOGIN
        password = password if password is not None else settings.MT5_PASSWORD
        server = server if server is not None else settings.MT5_SERVER
        path = path if path is not None else settings.MT5_PATH

        try:
            # initialize: نمرّر المسار فقط إن حُدِّد (وإلا اكتشاف تلقائي).
            ok = mt5.initialize(path) if path else mt5.initialize()
            if not ok:
                logger.error("فشل mt5.initialize(): %s", mt5.last_error())
                return False

            # login: مطلوب لربط الحساب المحدد بالخادم.
            if login and password and server:
                if not mt5.login(login, password=password, server=server):
                    logger.error("فشل mt5.login(): %s", mt5.last_error())
                    mt5.shutdown()
                    return False

            self.connected = True
            info = mt5.account_info()
            who = f"#{info.login} ({info.server})" if info else "(غير معروف)"
            logger.info("تم الاتصال بـ MetaTrader5: %s", who)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("استثناء أثناء الاتصال بـ MT5: %s", exc)
            return False

    def disconnect(self) -> None:
        """إغلاق الاتصال بالمنصة."""
        if MT5_AVAILABLE and self.connected:
            try:
                mt5.shutdown()
            except Exception as exc:  # noqa: BLE001
                logger.error("خطأ أثناء إغلاق MT5: %s", exc)
        self.connected = False

    def is_connected(self) -> bool:
        """فحص حالة الاتصال الفعلية (يتأكد من terminal_info)."""
        if not (MT5_AVAILABLE and self.connected):
            return False
        try:
            return mt5.terminal_info() is not None
        except Exception:  # noqa: BLE001
            return False

    # ------------------------------ البيانات ------------------------------ #
    def _resolve_timeframe(self, timeframe: str):
        """تحويل فريم أثيريا (مثل '15m') إلى ثابت MT5 المقابل."""
        name = settings.MT5_TIMEFRAME_MAP.get(timeframe)
        if not name:
            raise ValueError(f"فريم غير مدعوم: '{timeframe}'")
        tf_const = getattr(mt5, name, None)
        if tf_const is None:
            raise ValueError(f"ثابت الفريم '{name}' غير موجود في MetaTrader5.")
        return tf_const

    def get_candles(
        self, symbol: str, timeframe: str, count: int = 300
    ) -> pd.DataFrame:
        """
        جلب آخر ``count`` شمعة لزوج وفريم محددين كـ DataFrame موحّد.

        Args:
            symbol: رمز الزوج (مثل XAUUSD).
            timeframe: فريم أثيريا (15m/1h/4h...).
            count: عدد الشموع المطلوبة.

        Returns:
            DataFrame بأعمدة STANDARD_COLUMNS وفهرس زمني تصاعدي.

        Raises:
            MT5NotAvailableError: إن لم يكن MT5 متاحاً/متصلاً.
        """
        if not self.is_connected():
            raise MT5NotAvailableError("MT5 غير متصل — استدعِ connect() أولاً.")

        tf_const = self._resolve_timeframe(timeframe)
        # نتأكد أن الرمز مرئي في نافذة Market Watch قبل طلب البيانات.
        if not mt5.symbol_select(symbol, True):
            logger.warning("تعذّر تفعيل الرمز %s في Market Watch.", symbol)

        rates = mt5.copy_rates_from_pos(symbol, tf_const, 0, count)
        if rates is None or len(rates) == 0:
            raise MT5NotAvailableError(
                f"لم تُرجع MT5 أي بيانات لـ {symbol}/{timeframe}: {mt5.last_error()}"
            )

        df = pd.DataFrame(rates)
        # 'time' بصيغة ثوانٍ Unix (UTC) — نحوّلها إلى فهرس زمني.
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df = df.set_index("time").sort_index()
        # 'tick_volume' هو حجم التداول المتاح غالباً على الفوركس/الذهب.
        df = df.rename(columns={"tick_volume": "volume"})
        for col in STANDARD_COLUMNS:
            if col not in df.columns:
                df[col] = 0.0
        return df[STANDARD_COLUMNS]

    def get_tick(self, symbol: str) -> Optional[dict]:
        """جلب آخر سعر (bid/ask) للرمز كقاموس، أو None عند الفشل."""
        if not self.is_connected():
            return None
        try:
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                return None
            return {"bid": tick.bid, "ask": tick.ask, "time": tick.time}
        except Exception as exc:  # noqa: BLE001
            logger.error("خطأ في جلب tick لـ %s: %s", symbol, exc)
            return None

    def account_info(self) -> Optional[dict]:
        """جلب ملخّص حساب التداول (الرصيد، حقوق الملكية، الربح) كقاموس."""
        if not self.is_connected():
            return None
        try:
            info = mt5.account_info()
            if info is None:
                return None
            return {
                "login": info.login,
                "server": info.server,
                "balance": info.balance,
                "equity": info.equity,
                "profit": info.profit,
                "margin_free": info.margin_free,
                "currency": info.currency,
                "leverage": info.leverage,
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("خطأ في جلب معلومات الحساب: %s", exc)
            return None


# --------------------------------------------------------------------------- #
# اختبار مستقل: python -m data.live_fetcher
# (لا يتصل فعلياً إلا على Windows + MT5 — هنا يتحقق من سلامة التحميل فقط)
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(f"MetaTrader5 متاح؟ {MT5_AVAILABLE}")
    fetcher = LiveFetcher()
    if not MT5_AVAILABLE:
        print("ℹ️ هذه البيئة لا تملك MetaTrader5 (Windows فقط).")
        print("   على حاسوبك: شغّل MT5، اضبط الإعدادات، ثم:")
        print("   fetcher.connect(); df = fetcher.get_candles('XAUUSD', '15m', 300)")
    else:
        if fetcher.connect():
            print("✅ متصل. جلب آخر 5 شموع XAUUSD/15m:")
            print(fetcher.get_candles("XAUUSD", "15m", 5))
            print("معلومات الحساب:", fetcher.account_info())
            fetcher.disconnect()
        else:
            print("❌ فشل الاتصال — راجع إعدادات MT5.")
