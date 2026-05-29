"""
main.py
=======

[قيد التطوير — يُستكمل بعد الخطوة 4]

نقطة الدخول الرئيسية لبوت أثيريا: تربط المحركات (engines) بواجهة Telegram
(telebot)، وتبني القوائم التفاعلية (InlineKeyboardMarkup) لاختيار:
    - الوضع: باكتيست / تداول لحظي.
    - الفريم الزمني: 15m / 1h / 4h.
    - السنة (للباكتيست).

التدفّق المخطّط:
    1. /start  → عرض القائمة الرئيسية بالأزرار.
    2. اختيار "باكتيست" → اختيار الفريم → السنة → تشغيل المحرك وإرسال التقرير
       (مقسّماً عبر utils.telegram_utils.safe_send).
    3. اختيار "تداول لحظي" → الاتصال بـ MetaApi، تحليل آخر كاندل، وإرسال
       الإشارة مع زر تأكيد يدوي قبل أي تنفيذ.

معيار إلزامي: كل المعالجات (handlers) تُحاط بـ try/except وتُبلّغ المستخدم
بالخطأ عبر Telegram بدل إيقاف البوت.
"""

from __future__ import annotations

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("aetheria.main")


def build_bot():
    """
    إنشاء وتهيئة كائن telebot وربط المعالجات.

    TODO (بعد الخطوة 4):
        import telebot
        from config import settings
        bot = telebot.TeleBot(settings.TELEGRAM_TOKEN, parse_mode="Markdown")
        ... تسجيل المعالجات وأزرار InlineKeyboardMarkup ...
        return bot
    """
    raise NotImplementedError("build_bot — يُستكمل بعد إنجاز الخطوات 1→4")


def main() -> None:
    """نقطة التشغيل: تبني البوت وتبدأ الاستماع (polling)."""
    logger.info("Aetheria v1 — نقطة الدخول (هيكل أولي قيد التطوير).")
    # bot = build_bot()
    # bot.infinity_polling(skip_pending=True)


if __name__ == "__main__":
    main()
