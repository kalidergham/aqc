"""
data/csv_fetcher.py
===================

جلب وتحضير البيانات السعرية التاريخية من ملفات CSV — سواء من القرص المحلي
أو من GitHub (الروابط الخام raw.githubusercontent.com).

صيغة ملفات CSV المتوقّعة (كما في مستودع kalidergham/aqc):
    Date;Open;High;Low;Close;Volume
    2004.06.11 07:15;384;384.3;383.8;384.3;12
    - الفاصل: فاصلة منقوطة ";"
    - صيغة التاريخ: "YYYY.MM.DD HH:MM"

المخرجات الموحّدة: pandas.DataFrame بفهرس زمني (DatetimeIndex) وأعمدة صغيرة
الأحرف: open, high, low, close, volume — وهي الصيغة التي تتوقعها المحركات.
"""

from __future__ import annotations

import io
import logging

import pandas as pd
import requests

from config import settings

logger = logging.getLogger(__name__)

# الأعمدة الموحّدة التي تُسلّم للمحركات (بأحرف صغيرة).
STANDARD_COLUMNS = ["open", "high", "low", "close", "volume"]


def _parse_raw_csv(raw_text: str) -> pd.DataFrame:
    """
    تحويل نص CSV الخام إلى DataFrame موحّد.

    تتولّى: الفصل بـ ";"، تفسير عمود التاريخ، توحيد أسماء الأعمدة،
    وضبط الفهرس الزمني وترتيبه تصاعدياً.

    Args:
        raw_text: محتوى ملف CSV كنص.

    Returns:
        DataFrame بفهرس DatetimeIndex وأعمدة STANDARD_COLUMNS.
    """
    df = pd.read_csv(
        io.StringIO(raw_text),
        sep=";",
        # نفسّر التاريخ يدوياً بعد القراءة لضمان توافق الصيغة.
    )

    # توحيد أسماء الأعمدة (إزالة المسافات وتصغير الأحرف).
    df.columns = [c.strip().lower() for c in df.columns]

    if "date" not in df.columns:
        raise ValueError("عمود 'Date' غير موجود في ملف CSV")

    # تفسير التاريخ بالصيغة المعروفة "YYYY.MM.DD HH:MM".
    df["date"] = pd.to_datetime(df["date"], format="%Y.%m.%d %H:%M", errors="coerce")
    df = df.dropna(subset=["date"])
    df = df.set_index("date").sort_index()

    # ضمان وجود كل الأعمدة القياسية وتحويلها إلى أرقام.
    missing = [c for c in STANDARD_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"أعمدة مفقودة في CSV: {missing}")
    for col in STANDARD_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["open", "high", "low", "close"])
    return df[STANDARD_COLUMNS]


def fetch_from_local(path: str) -> pd.DataFrame:
    """
    قراءة ملف CSV من القرص المحلي (مفيد للاختبار دون إنترنت).

    Args:
        path: مسار الملف المحلي.

    Returns:
        DataFrame موحّد. يرفع استثناءً عند الفشل (يُلتقط في الطبقة الأعلى).
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return _parse_raw_csv(fh.read())
    except Exception as exc:  # noqa: BLE001
        logger.error("فشل قراءة CSV المحلي '%s': %s", path, exc)
        raise


def fetch_from_github(timeframe: str, timeout: int = 30) -> pd.DataFrame:
    """
    تنزيل ملف CSV الخاص بفريم زمني معيّن من GitHub.

    يعتمد على الروابط المعرّفة في ``settings.CSV_URLS``.

    Args:
        timeframe: أحد "15m" / "1h" / "4h".
        timeout: مهلة الطلب الشبكي بالثواني.

    Returns:
        DataFrame موحّد للبيانات التاريخية.
    """
    url = settings.CSV_URLS.get(timeframe)
    if not url:
        raise ValueError(
            f"فريم غير مدعوم: '{timeframe}'. المتاح: {list(settings.CSV_URLS)}"
        )
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        return _parse_raw_csv(resp.text)
    except Exception as exc:  # noqa: BLE001
        logger.error("فشل تنزيل CSV من GitHub (%s): %s", url, exc)
        raise


def filter_by_year(df: pd.DataFrame, year: int) -> pd.DataFrame:
    """
    تصفية الـ DataFrame للاحتفاظ بسنة محددة فقط (لاختيارات الباكتيست).

    Args:
        df: بيانات بفهرس زمني.
        year: السنة المطلوبة (مثل 2023).

    Returns:
        DataFrame مقتصر على تلك السنة.
    """
    return df[df.index.year == year]


# --------------------------------------------------------------------------- #
# اختبار مستقل: python -m data.csv_fetcher
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import os

    logging.basicConfig(level=logging.INFO)

    # نختبر على الملف المحلي إن وُجد بجذر المستودع (../XAU_1h_data.csv).
    here = os.path.dirname(os.path.abspath(__file__))
    candidate = os.path.join(here, "..", "..", "XAU_1h_data.csv")
    if os.path.exists(candidate):
        print(f"قراءة الملف المحلي: {candidate}")
        data = fetch_from_local(candidate)
        print(data.head())
        print(f"\nعدد الصفوف: {len(data):,}")
        print(f"المدى الزمني: {data.index.min()} → {data.index.max()}")
        print(f"الأعمدة: {list(data.columns)}")
    else:
        print("لم يُعثر على ملف CSV محلي للاختبار. جرّب fetch_from_github('1h').")
