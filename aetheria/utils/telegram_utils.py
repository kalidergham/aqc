"""
utils/telegram_utils.py
=======================

أدوات مساعدة لواجهة Telegram:
    1. تقطيع الرسائل الطويلة إلى أجزاء لا تتجاوز حدّ تلكرام (4096 حرفاً).
    2. تنسيق نتائج الباكتيست وإشارات التداول كنصوص جاهزة للإرسال.
    3. إرسال آمن (safe_send) يلتقط الأخطاء بدل إيقاف البوت.

كل الدوال هنا تعتمد على المكتبة القياسية فقط (عدا الإرسال الذي يأخذ كائن
البوت كوسيط) لتبقى خفيفة ومتوافقة تماماً مع Termux.
"""

from __future__ import annotations

import logging
from typing import List, Optional, Any

logger = logging.getLogger(__name__)

# الحد الأقصى لطول رسالة تلكرام الواحدة (قيد المنصة الرسمي).
TELEGRAM_MAX_LEN: int = 4096
# هامش أمان بسيط لتجنّب تجاوز الحد بسبب رموز التنسيق (Markdown/HTML).
SAFE_CHUNK_LEN: int = 4000


def split_message(text: str, max_len: int = SAFE_CHUNK_LEN) -> List[str]:
    """
    تقطيع نص طويل إلى قائمة أجزاء، كل جزء ≤ ``max_len`` حرفاً.

    تحاول الدالة القطع عند حدود الأسطر (\\n) للحفاظ على القراءة، وإذا وُجد
    سطر واحد أطول من ``max_len`` يُقطَّع قسراً على مستوى الأحرف.

    Args:
        text: النص الكامل المراد تقطيعه.
        max_len: أقصى طول للجزء الواحد (افتراضياً 4000 كهامش أمان دون 4096).

    Returns:
        قائمة من السلاسل النصية، كل واحدة جاهزة للإرسال كرسالة مستقلة.
    """
    if text is None:
        return []
    if max_len <= 0:
        raise ValueError("max_len يجب أن يكون عدداً موجباً")

    # إن كان النص ضمن الحد، نُعيده كجزء واحد مباشرةً.
    if len(text) <= max_len:
        return [text]

    chunks: List[str] = []
    current: List[str] = []
    current_len = 0

    # نقطّع سطراً سطراً ونجمع الأسطر ما دامت ضمن الحد.
    for line in text.split("\n"):
        # سطر أطول من الحد بمفرده: نُفرّغ المتراكم ثم نقطّعه قسراً.
        if len(line) > max_len:
            if current:
                chunks.append("\n".join(current))
                current, current_len = [], 0
            for i in range(0, len(line), max_len):
                chunks.append(line[i : i + max_len])
            continue

        # +1 يحسب فاصل السطر "\n" الذي سيُضاف بين الأسطر.
        projected = current_len + len(line) + (1 if current else 0)
        if projected > max_len:
            chunks.append("\n".join(current))
            current, current_len = [line], len(line)
        else:
            current.append(line)
            current_len = projected

    if current:
        chunks.append("\n".join(current))

    return chunks


def safe_send(
    bot: Any,
    chat_id: int | str,
    text: str,
    parse_mode: Optional[str] = None,
    reply_markup: Optional[Any] = None,
) -> bool:
    """
    إرسال رسالة (أو رسائل مقسّمة) بأمان عبر كائن telebot.

    تلتقط أي استثناء وتسجّله بدل أن توقف البوت (تحقيقاً لمعيار "معالجة
    الأخطاء" الإلزامي). الأزرار (reply_markup) تُرفق بآخر جزء فقط.

    Args:
        bot: كائن telebot.TeleBot.
        chat_id: معرّف المحادثة.
        text: النص (قد يكون أطول من 4096 وسيُقسَّم تلقائياً).
        parse_mode: "Markdown" أو "HTML" أو None.
        reply_markup: لوحة أزرار اختيارية تُرفق بالجزء الأخير.

    Returns:
        True إذا أُرسلت كل الأجزاء بنجاح، وإلا False.
    """
    chunks = split_message(text)
    ok = True
    for idx, chunk in enumerate(chunks):
        is_last = idx == len(chunks) - 1
        try:
            bot.send_message(
                chat_id,
                chunk,
                parse_mode=parse_mode,
                # نرفق الأزرار بالجزء الأخير فقط لتجنّب تكرارها.
                reply_markup=reply_markup if is_last else None,
            )
        except Exception as exc:  # noqa: BLE001 - نلتقط كل شيء عمداً للأمان
            ok = False
            logger.error("فشل إرسال رسالة تلكرام: %s", exc)
    return ok


def format_backtest_report(stats: dict) -> str:
    """
    تنسيق قاموس نتائج الباكتيست كنص عربي مقروء جاهز للإرسال.

    Args:
        stats: قاموس يحوي مفاتيح مثل win_rate, profit_factor,
               max_drawdown, sharpe_ratio, total_trades ... إلخ.

    Returns:
        نص منسّق (قد يُمرّر لاحقاً إلى split_message عند الإرسال).
    """
    lines = [
        "📊 *تقرير الباكتيست*",
        "──────────────────",
        f"🔧 المحرك      : {stats.get('engine', '—')}",
        f"💱 الزوج       : {stats.get('symbol', '—')}",
        f"⏱️ الفريم      : {stats.get('timeframe', '—')}",
        f"📅 الفترة      : {stats.get('period', '—')}",
        "──────────────────",
        f"🔢 عدد الصفقات : {stats.get('total_trades', 0)}",
        f"✅ نسبة الربح  : {stats.get('win_rate', 0.0):.2f}%",
        f"📈 Profit Factor: {stats.get('profit_factor', 0.0):.2f}",
        f"📉 Max Drawdown : {stats.get('max_drawdown', 0.0):.2f}%",
        f"⚖️ Sharpe Ratio : {stats.get('sharpe_ratio', 0.0):.2f}",
        f"💰 صافي الربح   : {stats.get('net_profit', 0.0):.2f}",
        "──────────────────",
    ]
    return "\n".join(lines)


def format_signal(signal: dict) -> str:
    """
    تنسيق قاموس إشارة تداول كنص تنبيه جاهز للإرسال للمستخدم.

    Args:
        signal: قاموس الإشارة (مخرجات Engine.analyze) — يحوي
                signal/entry/sl/tp/confidence/reason ... إلخ.

    Returns:
        نص التنبيه المنسّق.
    """
    direction = str(signal.get("signal", "HOLD")).upper()
    emoji = {"BUY": "🟢", "SELL": "🔴"}.get(direction, "⚪")
    lines = [
        f"{emoji} *إشارة تداول جديدة*",
        "──────────────────",
        f"🔧 المحرك     : {signal.get('engine', '—')}",
        f"💱 الزوج      : {signal.get('symbol', '—')}",
        f"📍 الاتجاه    : {direction}",
        f"🎯 الدخول     : {signal.get('entry', '—')}",
        f"🛑 وقف الخسارة: {signal.get('sl', '—')}",
        f"🏁 الهدف      : {signal.get('tp', '—')}",
        f"📊 الثقة      : {signal.get('confidence', 0.0):.0%}",
        f"📝 السبب      : {signal.get('reason', '—')}",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# اختبار مستقل: python -m utils.telegram_utils
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    print("اختبار تقطيع الرسائل الطويلة...")
    long_text = "\n".join(f"سطر رقم {i}: " + "x" * 50 for i in range(300))
    parts = split_message(long_text)
    print(f"الطول الكلي: {len(long_text)} حرفاً")
    print(f"عدد الأجزاء: {len(parts)}")
    assert all(len(p) <= SAFE_CHUNK_LEN for p in parts), "جزء تجاوز الحد!"
    print("✅ كل الأجزاء ضمن الحد المسموح.")

    print("\nاختبار تنسيق تقرير وهمي:")
    print(
        format_backtest_report(
            {
                "engine": "MeanReversion",
                "symbol": "XAUUSD",
                "timeframe": "1h",
                "period": "2023",
                "total_trades": 142,
                "win_rate": 56.3,
                "profit_factor": 1.48,
                "max_drawdown": 12.7,
                "sharpe_ratio": 1.21,
                "net_profit": 3820.5,
            }
        )
    )
