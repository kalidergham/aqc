"""
utils/auth.py
=============

التحكم في الصلاحيات (Authorization) لواجهة Telegram.

يوفّر:
    - استخراج معرّف المستخدم من رسالة أو نقرة زر.
    - مُصنّع ديكوريترات (admin_only / authorized_only) يلفّ معالجات البوت
      ويمنع غير المصرّح لهم، مع ردّ تلقائي مهذّب.

لا يستورد telebot مباشرةً (يتعامل مع الكائنات بأسلوب duck-typing) ليبقى
قابلاً للاختبار المستقل دون تثبيت المكتبة.
"""

from __future__ import annotations

import logging
from functools import wraps
from typing import Any, Callable, Optional

from config import settings

logger = logging.getLogger(__name__)


def get_user_id(obj: Any) -> Optional[int]:
    """استخراج معرّف المستخدم من رسالة (Message) أو نقرة (CallbackQuery)."""
    try:
        return int(obj.from_user.id)
    except Exception:  # noqa: BLE001
        return None


def get_chat_id(obj: Any) -> Optional[int]:
    """استخراج معرّف المحادثة من رسالة أو نقرة زر."""
    # رسالة عادية.
    chat = getattr(obj, "chat", None)
    if chat is not None:
        return getattr(chat, "id", None)
    # نقرة زر: obj.message.chat.id
    msg = getattr(obj, "message", None)
    if msg is not None and getattr(msg, "chat", None) is not None:
        return msg.chat.id
    return None


def _deny(bot: Any, obj: Any, admin: bool = False) -> None:
    """ردّ مهذّب عند رفض الوصول (يدعم الرسائل والنقرات)."""
    text = (
        "⛔ هذا الإجراء مخصّص للأدمن فقط."
        if admin
        else "⛔ غير مصرّح لك باستخدام هذا البوت.\nتواصل مع الأدمن لإضافتك."
    )
    try:
        # إن كانت نقرة زر، نُجيب الـ callback أولاً.
        if hasattr(obj, "id") and hasattr(obj, "message"):
            bot.answer_callback_query(obj.id, text, show_alert=True)
        else:
            chat_id = get_chat_id(obj)
            if chat_id is not None:
                bot.send_message(chat_id, text)
    except Exception as exc:  # noqa: BLE001
        logger.error("فشل إرسال رسالة الرفض: %s", exc)


def make_auth_decorators(bot: Any, state: Any):
    """
    إنشاء ديكوريترات التصريح مربوطةً بكائن البوت والحالة.

    Returns:
        (authorized_only, admin_only) — ديكوريتران لتغليف المعالجات.
    """

    def authorized_only(func: Callable) -> Callable:
        """يسمح فقط للمستخدمين المصرّح لهم (الأدمن + المُضافون)."""

        @wraps(func)
        def wrapper(obj: Any, *args, **kwargs):
            uid = get_user_id(obj)
            if uid is None or not state.is_authorized(uid):
                logger.warning("رفض وصول غير مصرّح: user_id=%s", uid)
                _deny(bot, obj)
                return None
            return func(obj, *args, **kwargs)

        return wrapper

    def admin_only(func: Callable) -> Callable:
        """يسمح فقط للأدمن (لوحة التحكم والإجراءات الحسّاسة)."""

        @wraps(func)
        def wrapper(obj: Any, *args, **kwargs):
            uid = get_user_id(obj)
            if uid is None or not settings.is_admin(uid):
                logger.warning("رفض وصول لوحة أدمن: user_id=%s", uid)
                _deny(bot, obj, admin=True)
                return None
            return func(obj, *args, **kwargs)

        return wrapper

    return authorized_only, admin_only


# --------------------------------------------------------------------------- #
# اختبار مستقل: python -m utils.auth
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # كائنات وهمية تحاكي رسالة Telegram.
    class _User:
        def __init__(self, uid):
            self.id = uid

    class _Chat:
        def __init__(self, cid):
            self.id = cid

    class _Msg:
        def __init__(self, uid):
            self.from_user = _User(uid)
            self.chat = _Chat(uid)

    class _FakeBot:
        def send_message(self, chat_id, text, **k):
            print(f"[bot→{chat_id}] {text}")

        def answer_callback_query(self, *a, **k):
            print("[answer_callback]", a, k)

    class _FakeState:
        def is_authorized(self, uid):
            return uid == 111

    bot = _FakeBot()
    authorized_only, admin_only = make_auth_decorators(bot, _FakeState())

    @authorized_only
    def handler(msg):
        print(f"✅ نُفّذ المعالج للمستخدم {msg.from_user.id}")

    print("مستخدم مصرّح (111):")
    handler(_Msg(111))
    print("مستخدم غير مصرّح (999):")
    handler(_Msg(999))
    print("✅ انتهى اختبار التصريح.")
