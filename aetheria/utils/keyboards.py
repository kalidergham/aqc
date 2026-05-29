"""
utils/keyboards.py
==================

بنّاؤو لوحات الأزرار التفاعلية (InlineKeyboardMarkup) لكل قوائم البوت.

مخطّط بيانات الأزرار (callback_data) — مختصر ليبقى ضمن حدّ 64 بايت:
    m:<x>                      → التنقّل بين القوائم (main/bt/live/set/status/admin)
    bt:eng:<Name>              → اختيار محرك للباكتيست
    bt:tf:<Name>:<tf>          → اختيار فريم (يحمل المحرك)
    bt:go:<Name>:<tf>:<year>   → تشغيل الباكتيست
    live:<start|stop|status>   → التحكم بالتداول اللحظي
    set:<auto|risk+|risk-|...> → الإعدادات
    eng:tg:<Name>              → تبديل تفعيل محرك
    adm:<users|stats|mt5|...>  → لوحة الأدمن
    sig:<ok|no>:<sid>          → تأكيد/إلغاء إشارة

ملاحظة: يعتمد على telebot.types (يُثبَّت ضمن pyTelegramBotAPI).
"""

from __future__ import annotations

from typing import Any

from telebot import types

from config import settings


def _btn(text: str, data: str) -> "types.InlineKeyboardButton":
    """اختصار لإنشاء زر inline."""
    return types.InlineKeyboardButton(text, callback_data=data)


def main_menu(is_admin: bool = False) -> "types.InlineKeyboardMarkup":
    """القائمة الرئيسية."""
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        _btn("📊 باكتيست", "m:bt"),
        _btn("📡 تداول لحظي", "m:live"),
    )
    kb.add(
        _btn("⚙️ الإعدادات", "m:set"),
        _btn("📈 الحالة", "m:status"),
    )
    if is_admin:
        kb.add(_btn("🛡️ لوحة الأدمن", "m:admin"))
    return kb


def back_to_main() -> "types.InlineKeyboardMarkup":
    """زر رجوع للقائمة الرئيسية."""
    kb = types.InlineKeyboardMarkup()
    kb.add(_btn("🔙 القائمة الرئيسية", "m:main"))
    return kb


def engines_choice_menu(action: str) -> "types.InlineKeyboardMarkup":
    """
    قائمة اختيار محرك (تُستخدم في الباكتيست).

    Args:
        action: بادئة الإجراء، مثل "bt:eng".
    """
    kb = types.InlineKeyboardMarkup(row_width=1)
    for name in settings_engine_names():
        kb.add(_btn(f"🔧 {name}", f"{action}:{name}"))
    kb.add(_btn("🔙 رجوع", "m:main"))
    return kb


def settings_engine_names() -> list[str]:
    """أسماء المحركات المتاحة (نقرؤها من السجلّ لتفادي الاستيراد الدائري)."""
    from engines import ENGINE_REGISTRY

    return list(ENGINE_REGISTRY.keys())


def timeframe_menu(engine_name: str) -> "types.InlineKeyboardMarkup":
    """اختيار الفريم الزمني للباكتيست (يحمل اسم المحرك في البيانات)."""
    kb = types.InlineKeyboardMarkup(row_width=3)
    kb.add(*[_btn(tf, f"bt:tf:{engine_name}:{tf}") for tf in settings.SUPPORTED_TIMEFRAMES])
    kb.add(_btn("🔙 رجوع", "m:bt"))
    return kb


def years_menu(engine_name: str, timeframe: str) -> "types.InlineKeyboardMarkup":
    """اختيار سنة الباكتيست (شبكة سنوات بصفوف من 4)."""
    kb = types.InlineKeyboardMarkup(row_width=4)
    years = list(range(settings.BACKTEST_MAX_YEAR, settings.BACKTEST_MIN_YEAR - 1, -1))
    buttons = [_btn(str(y), f"bt:go:{engine_name}:{timeframe}:{y}") for y in years]
    # نُضيفها صفوفاً من 4 أزرار.
    for i in range(0, len(buttons), 4):
        kb.row(*buttons[i : i + 4])
    kb.add(_btn("🔙 رجوع", "m:bt"))
    return kb


def live_menu(state: Any) -> "types.InlineKeyboardMarkup":
    """قائمة التحكم بالتداول اللحظي."""
    kb = types.InlineKeyboardMarkup(row_width=2)
    if state.live_running:
        kb.add(_btn("⏹️ إيقاف المراقبة", "live:stop"))
    else:
        kb.add(_btn("▶️ بدء المراقبة", "live:start"))
    kb.add(
        _btn("🔍 تحليل فوري", "live:scan"),
        _btn("📋 المراكز المفتوحة", "live:positions"),
    )
    kb.add(_btn("🔙 القائمة الرئيسية", "m:main"))
    return kb


def settings_menu(state: Any) -> "types.InlineKeyboardMarkup":
    """قائمة الإعدادات القابلة للتعديل."""
    kb = types.InlineKeyboardMarkup(row_width=2)
    auto = "🟢 أوتوماتيكي" if state.auto_trade else "🟡 تأكيد يدوي"
    kb.add(_btn(f"وضع التنفيذ: {auto}", "set:auto"))
    kb.add(
        _btn("➖ مخاطرة", "set:risk-"),
        _btn(f"مخاطرة: {state.risk_pct}%", "set:noop"),
        _btn("➕ مخاطرة", "set:risk+"),
    )
    kb.add(
        _btn("➖ صفقات/يوم", "set:trades-"),
        _btn(f"حد: {state.max_trades_day}", "set:noop"),
        _btn("➕ صفقات/يوم", "set:trades+"),
    )
    kb.add(_btn(f"⏱️ فريم لحظي: {state.timeframe}", "set:tf"))
    kb.add(_btn("🔧 تفعيل/تعطيل المحركات", "set:engines"))
    kb.add(_btn("🔙 القائمة الرئيسية", "m:main"))
    return kb


def engines_toggle_menu(state: Any) -> "types.InlineKeyboardMarkup":
    """قائمة تبديل تفعيل المحركات (✅ مفعّل / ⬜ معطّل)."""
    kb = types.InlineKeyboardMarkup(row_width=1)
    for name in settings_engine_names():
        mark = "✅" if state.is_engine_enabled(name) else "⬜"
        kb.add(_btn(f"{mark} {name}", f"eng:tg:{name}"))
    kb.add(_btn("🔙 رجوع للإعدادات", "m:set"))
    return kb


def live_tf_menu() -> "types.InlineKeyboardMarkup":
    """اختيار الفريم الزمني للتحليل اللحظي."""
    kb = types.InlineKeyboardMarkup(row_width=3)
    kb.add(*[_btn(tf, f"set:settf:{tf}") for tf in settings.SUPPORTED_TIMEFRAMES])
    kb.add(_btn("🔙 رجوع للإعدادات", "m:set"))
    return kb


def admin_menu() -> "types.InlineKeyboardMarkup":
    """لوحة تحكم الأدمن."""
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        _btn("👥 المستخدمون", "adm:users"),
        _btn("📊 إحصاءات", "adm:stats"),
    )
    kb.add(
        _btn("🔌 حالة MT5", "adm:mt5"),
        _btn("📋 المراكز", "adm:positions"),
    )
    kb.add(_btn("🛑 إغلاق كل الصفقات (طوارئ)", "adm:closeall"))
    kb.add(
        _btn("📜 آخر السجلّات", "adm:logs"),
        _btn("🔄 إعادة فحص الإعدادات", "adm:reload"),
    )
    kb.add(_btn("🔙 القائمة الرئيسية", "m:main"))
    return kb


def confirm_signal_menu(sid: str) -> "types.InlineKeyboardMarkup":
    """أزرار تأكيد/إلغاء تنفيذ إشارة معلّقة."""
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        _btn("✅ تنفيذ الصفقة", f"sig:ok:{sid}"),
        _btn("❌ تجاهل", f"sig:no:{sid}"),
    )
    return kb


def positions_menu(positions: list) -> "types.InlineKeyboardMarkup":
    """أزرار إغلاق المراكز المفتوحة (زر لكل مركز)."""
    kb = types.InlineKeyboardMarkup(row_width=1)
    for p in positions:
        label = f"❌ إغلاق #{p['ticket']} {p['type']} ({p['profit']:+.2f})"
        kb.add(_btn(label, f"pos:close:{p['ticket']}"))
    if positions:
        kb.add(_btn("🛑 إغلاق الكل", "adm:closeall"))
    kb.add(_btn("🔙 القائمة الرئيسية", "m:main"))
    return kb
