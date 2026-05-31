"""
main.py
=======

نقطة الدخول الرئيسية لبوت أثيريا (Aetheria v1) — نسخة سطح المكتب (Windows).

يربط:
    - واجهة Telegram (telebot) مع أزرار تفاعلية كاملة.
    - محركات التحليل (engines) عبر السجلّ ENGINE_REGISTRY.
    - محرك الباكتيست (core.backtester) على بيانات CSV.
    - التداول اللحظي عبر MetaTrader5 (data.live_fetcher + core.trader).
    - لوحة أدمن كاملة (مستخدمون/إحصاءات/حالة MT5/إغلاق طوارئ/سجلّات).

التحكّم 100% عبر الأزرار. كل المعالجات محاطة بمعالجة أخطاء، وكل العمليات
الثقيلة (باكتيست/مراقبة) تعمل في خيوط منفصلة حتى لا تُجمّد البوت.

التشغيل:
    python main.py
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

import telebot

from config import settings
from core.backtester import BacktestEngine
from core.state import STATE
from core.trader import Trader
from data import csv_fetcher
from data.live_fetcher import LiveFetcher
from engines import build_engine, ENGINE_REGISTRY
from engines.engine_base import SignalType
from utils import auth, keyboards, telegram_utils

# --------------------------- إعداد التسجيل (Logging) ------------------------ #
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format=settings.LOG_FORMAT,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(settings.LOG_FILE, encoding="utf-8"),
    ],
)
logger = logging.getLogger("aetheria.main")


class AetheriaBot:
    """التطبيق الرئيسي: يجمع البوت والحالة والمحركات وأدوات التنفيذ."""

    def __init__(self, token: str) -> None:
        self.bot = telebot.TeleBot(token, parse_mode=settings.TELEGRAM_PARSE_MODE)
        self.state = STATE
        self.fetcher = LiveFetcher()
        self.trader = Trader()
        # ديكوريترات التصريح مربوطة بالبوت والحالة.
        self.authorized_only, self.admin_only = auth.make_auth_decorators(
            self.bot, self.state
        )
        # تتبّع آخر إشارة لكل محرك لتفادي التكرار في كل دورة مراقبة.
        self._last_sig: dict[str, str] = {}
        self._register_handlers()

    # ====================================================================== #
    #  أدوات مساعدة للرسائل
    # ====================================================================== #
    def _edit_or_send(
        self, call_or_chat: Any, text: str, markup: Optional[Any] = None
    ) -> None:
        """تعديل رسالة القائمة إن أمكن، وإلا إرسال رسالة جديدة."""
        try:
            if hasattr(call_or_chat, "message"):  # CallbackQuery
                self.bot.edit_message_text(
                    text,
                    call_or_chat.message.chat.id,
                    call_or_chat.message.message_id,
                    reply_markup=markup,
                )
            else:  # chat_id مباشر
                self.bot.send_message(call_or_chat, text, reply_markup=markup)
        except Exception as exc:  # noqa: BLE001 - قد تفشل edit إن لم يتغيّر النص
            logger.debug("edit_or_send سقط على الإرسال: %s", exc)
            chat_id = (
                call_or_chat.message.chat.id
                if hasattr(call_or_chat, "message")
                else call_or_chat
            )
            telegram_utils.safe_send(self.bot, chat_id, text, reply_markup=markup)

    def _broadcast(self, text: str, markup: Optional[Any] = None) -> None:
        """إرسال رسالة لكل الأدمن (للتنبيهات والإشارات)."""
        for admin_id in settings.ADMIN_IDS:
            telegram_utils.safe_send(self.bot, admin_id, text, reply_markup=markup)

    # ====================================================================== #
    #  تسجيل المعالجات
    # ====================================================================== #
    def _register_handlers(self) -> None:
        bot = self.bot

        @bot.message_handler(commands=["start", "menu"])
        @self.authorized_only
        def cmd_start(message):
            is_admin = settings.is_admin(message.from_user.id)
            text = (
                f"🏛️ *{settings.APP_NAME} v{settings.APP_VERSION}*\n"
                "بوت التداول الكمي للذهب (XAUUSD).\n\n"
                "اختر من القائمة بالأسفل 👇"
            )
            telegram_utils.safe_send(
                bot, message.chat.id, text, reply_markup=keyboards.main_menu(is_admin)
            )

        @bot.message_handler(commands=["id"])
        def cmd_id(message):
            # متاح للجميع: يساعد المستخدم على معرفة معرّفه لإضافته كأدمن/مصرّح.
            bot.send_message(
                message.chat.id,
                f"🆔 معرّفك: `{message.from_user.id}`\n"
                f"معرّف المحادثة: `{message.chat.id}`",
            )

        @bot.message_handler(commands=["help"])
        @self.authorized_only
        def cmd_help(message):
            text = (
                "📖 *دليل سريع*\n\n"
                "/start أو /menu — القائمة الرئيسية\n"
                "/id — معرّفك في تلكرام\n"
                "/help — هذا الدليل\n\n"
                "كل التحكّم عبر الأزرار: باكتيست، تداول لحظي، إعدادات، "
                "ولوحة أدمن (للمصرّح لهم)."
            )
            telegram_utils.safe_send(bot, message.chat.id, text, reply_markup=keyboards.back_to_main())

        @bot.callback_query_handler(func=lambda c: True)
        @self.authorized_only
        def on_callback(call):
            try:
                self._dispatch_callback(call)
            except Exception as exc:  # noqa: BLE001
                logger.error("خطأ في معالجة الزر '%s': %s", call.data, exc)
                self.state.last_error = str(exc)
                try:
                    bot.answer_callback_query(call.id, f"⚠️ خطأ: {exc}", show_alert=True)
                except Exception:  # noqa: BLE001
                    pass

    # ====================================================================== #
    #  موزّع الأزرار (Callback Dispatcher)
    # ====================================================================== #
    def _dispatch_callback(self, call) -> None:
        data = call.data or ""
        uid = call.from_user.id
        # نُجيب النقرة فوراً لإيقاف مؤشّر التحميل.
        try:
            self.bot.answer_callback_query(call.id)
        except Exception:  # noqa: BLE001
            pass

        # --- التنقّل بين القوائم ---
        if data == "m:main":
            self._edit_or_send(call, "🏛️ القائمة الرئيسية:", keyboards.main_menu(settings.is_admin(uid)))
        elif data == "m:bt":
            self._edit_or_send(call, "📊 اختر المحرك للباكتيست:", keyboards.engines_choice_menu("bt:eng"))
        elif data == "m:live":
            self._show_live(call)
        elif data == "m:set":
            self._edit_or_send(call, "⚙️ الإعدادات:", keyboards.settings_menu(self.state))
        elif data == "m:status":
            self._show_status(call)
        elif data == "m:admin":
            self._guard_admin(call, lambda: self._edit_or_send(call, "🛡️ لوحة الأدمن:", keyboards.admin_menu()))

        # --- تدفّق الباكتيست ---
        elif data.startswith("bt:eng:"):
            engine_name = data.split(":", 2)[2]
            self._edit_or_send(call, f"📊 {engine_name} — اختر الفريم:", keyboards.timeframe_menu(engine_name))
        elif data.startswith("bt:tf:"):
            _, _, engine_name, tf = data.split(":", 3)
            self._edit_or_send(call, f"📊 {engine_name}/{tf} — اختر السنة:", keyboards.years_menu(engine_name, tf))
        elif data.startswith("bt:go:"):
            _, _, engine_name, tf, year = data.split(":", 4)
            self._start_backtest(call, engine_name, tf, int(year))

        # --- التداول اللحظي ---
        elif data == "live:start":
            self._start_live(call)
        elif data == "live:stop":
            self._stop_live(call)
        elif data == "live:scan":
            self._manual_scan(call)
        elif data == "live:positions":
            self._show_positions(call)

        # --- الإعدادات ---
        elif data == "set:auto":
            self.state.auto_trade = not self.state.auto_trade
            self._edit_or_send(call, "⚙️ الإعدادات:", keyboards.settings_menu(self.state))
        elif data in ("set:risk+", "set:risk-"):
            delta = 0.5 if data.endswith("+") else -0.5
            self.state.risk_pct = max(0.1, round(self.state.risk_pct + delta, 1))
            self._edit_or_send(call, "⚙️ الإعدادات:", keyboards.settings_menu(self.state))
        elif data in ("set:trades+", "set:trades-"):
            delta = 1 if data.endswith("+") else -1
            self.state.max_trades_day = max(1, self.state.max_trades_day + delta)
            self._edit_or_send(call, "⚙️ الإعدادات:", keyboards.settings_menu(self.state))
        elif data == "set:tf":
            self._edit_or_send(call, "⏱️ اختر الفريم اللحظي:", keyboards.live_tf_menu())
        elif data.startswith("set:settf:"):
            self.state.timeframe = data.split(":", 2)[2]
            self._edit_or_send(call, "⚙️ الإعدادات:", keyboards.settings_menu(self.state))
        elif data == "set:engines":
            self._edit_or_send(call, "🔧 المحركات (اضغط للتبديل):", keyboards.engines_toggle_menu(self.state))
        elif data.startswith("eng:tg:"):
            name = data.split(":", 2)[2]
            self.state.toggle_engine(name)
            self._edit_or_send(call, "🔧 المحركات (اضغط للتبديل):", keyboards.engines_toggle_menu(self.state))
        elif data == "set:noop":
            pass  # زر عرض فقط

        # --- لوحة الأدمن ---
        elif data.startswith("adm:"):
            self._guard_admin(call, lambda: self._handle_admin(call, data))

        # --- تأكيد/إلغاء الإشارات ---
        elif data.startswith("sig:ok:"):
            self._confirm_signal(call, data.split(":", 2)[2])
        elif data.startswith("sig:no:"):
            sid = data.split(":", 2)[2]
            self.state.pop_pending(sid)
            self._edit_or_send(call, "❌ تم تجاهل الإشارة.", keyboards.back_to_main())

        # --- إغلاق مركز محدّد ---
        elif data.startswith("pos:close:"):
            self._guard_admin(call, lambda: self._close_one(call, int(data.split(":", 2)[2])))

    def _guard_admin(self, call, action) -> None:
        """تنفيذ إجراء أدمن فقط إن كان المستخدم أدمن."""
        if not settings.is_admin(call.from_user.id):
            self.bot.answer_callback_query(call.id, "⛔ للأدمن فقط.", show_alert=True)
            return
        action()

    # ====================================================================== #
    #  الباكتيست
    # ====================================================================== #
    def _get_backtest_data(self, timeframe: str):
        """جلب بيانات الباكتيست: GitHub أولاً ثم الملف المحلي كحلّ بديل."""
        try:
            return csv_fetcher.fetch_from_github(timeframe)
        except Exception as exc:  # noqa: BLE001
            logger.warning("فشل جلب CSV من GitHub (%s)، نجرّب محلياً.", exc)
            import os

            here = os.path.dirname(os.path.abspath(__file__))
            path = os.path.join(here, "..", settings.CSV_LOCAL_PATHS[timeframe])
            return csv_fetcher.fetch_from_local(path)

    def _start_backtest(self, call, engine_name: str, tf: str, year: int) -> None:
        """تشغيل الباكتيست في خيط منفصل وإرسال النتائج."""
        chat_id = call.message.chat.id
        self._edit_or_send(call, f"⏳ جاري تشغيل الباكتيست: {engine_name} / {tf} / {year} ...")

        def worker():
            try:
                df = self._get_backtest_data(tf)
                df_year = csv_fetcher.filter_by_year(df, year)
                if df_year is None or len(df_year) == 0:
                    telegram_utils.safe_send(self.bot, chat_id, f"⚠️ لا توجد بيانات لسنة {year}.")
                    return
                engine = build_engine(engine_name, symbol=self.state.symbol)
                bt = BacktestEngine(engine)
                stats = bt.run(df_year, {"symbol": self.state.symbol, "timeframe": tf, "period": str(year)})
                report = telegram_utils.format_backtest_report(stats)
                # نُضيف مقاييس إضافية للتقرير.
                report += (
                    f"\n📊 العائد: {stats.get('return_pct', 0)}%"
                    f"\n💵 الرصيد النهائي: {stats.get('final_balance', 0)}"
                    f"\n🎯 متوسط الربح: {stats.get('avg_win', 0)} | "
                    f"متوسط الخسارة: {stats.get('avg_loss', 0)}"
                    f"\n📐 التوقّع/صفقة: {stats.get('expectancy', 0)}"
                )
                if stats.get("note"):
                    report += f"\nℹ️ {stats['note']}"
                telegram_utils.safe_send(
                    self.bot, chat_id, report, reply_markup=keyboards.back_to_main()
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("خطأ في الباكتيست: %s", exc)
                telegram_utils.safe_send(self.bot, chat_id, f"⚠️ فشل الباكتيست: {exc}")

        threading.Thread(target=worker, daemon=True).start()

    # ====================================================================== #
    #  التداول اللحظي
    # ====================================================================== #
    def _show_live(self, call) -> None:
        status = "🟢 شغّالة" if self.state.live_running else "🔴 متوقّفة"
        mode = "أوتوماتيكي" if self.state.auto_trade else "تأكيد يدوي"
        text = (
            "📡 *التداول اللحظي*\n"
            f"الحالة: {status}\n"
            f"الزوج: {self.state.symbol} | الفريم: {self.state.timeframe}\n"
            f"الوضع: {mode}\n"
            f"المحركات: {', '.join(self.state.enabled_engines) or 'لا شيء'}"
        )
        self._edit_or_send(call, text, keyboards.live_menu(self.state))

    def _ensure_mt5(self) -> bool:
        """ضمان اتصال MT5 (محاولة الاتصال إن لم يكن متصلاً)."""
        if self.fetcher.is_connected():
            return True
        return self.fetcher.connect()

    def _start_live(self, call) -> None:
        if self.state.live_running:
            self.bot.answer_callback_query(call.id, "المراقبة شغّالة أصلاً.")
            return
        if not self._ensure_mt5():
            self._edit_or_send(call, "⚠️ تعذّر الاتصال بـ MT5 — راجع الإعدادات.", keyboards.live_menu(self.state))
            return

        thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.state.start_monitor(thread)
        thread.start()
        self._edit_or_send(call, "▶️ بدأت المراقبة اللحظية.", keyboards.live_menu(self.state))
        logger.info("بدأت المراقبة اللحظية.")

    def _stop_live(self, call) -> None:
        self.state.stop_monitor()
        self._edit_or_send(call, "⏹️ تم إيقاف المراقبة.", keyboards.live_menu(self.state))
        logger.info("تم إيقاف المراقبة اللحظية.")

    def _monitor_loop(self) -> None:
        """حلقة المراقبة في الخلفية: تفحص السوق دورياً وتُطلق الإشارات."""
        while not self.state.stop_requested():
            try:
                self._scan(notify_chat=None)
            except Exception as exc:  # noqa: BLE001
                logger.error("خطأ في حلقة المراقبة: %s", exc)
                self.state.last_error = str(exc)
            # نوم مُجزّأ يسمح بالإيقاف السريع.
            for _ in range(max(1, settings.LIVE_POLL_INTERVAL)):
                if self.state.stop_requested():
                    break
                time.sleep(1)

    def _scan(self, notify_chat: Optional[int]) -> None:
        """فحص واحد لكل المحركات المفعّلة وإطلاق/عرض الإشارات."""
        if not self._ensure_mt5():
            if notify_chat:
                telegram_utils.safe_send(self.bot, notify_chat, "⚠️ MT5 غير متصل.")
            return

        for name in list(self.state.enabled_engines):
            try:
                engine = build_engine(name, symbol=self.state.symbol)
                count = max(engine.min_rows + 50, 300)
                df = self.fetcher.get_candles(self.state.symbol, self.state.timeframe, count)
                result = engine.analyze(df)

                if result.get("signal") in (SignalType.BUY.value, SignalType.SELL.value):
                    # توقيع فريد لتفادي تكرار نفس الإشارة كل دورة.
                    sig_key = f"{name}:{result['signal']}:{round(result.get('entry', 0), 1)}"
                    if self._last_sig.get(name) == sig_key:
                        continue
                    self._last_sig[name] = sig_key
                    self._handle_signal(result, notify_chat)
                elif notify_chat:
                    telegram_utils.safe_send(
                        self.bot, notify_chat, f"🔍 {name}: لا إشارة الآن.\n{result.get('reason', '')}"
                    )
            except Exception as exc:  # noqa: BLE001
                logger.error("خطأ في فحص المحرك %s: %s", name, exc)
                if notify_chat:
                    telegram_utils.safe_send(self.bot, notify_chat, f"⚠️ خطأ في {name}: {exc}")

    def _manual_scan(self, call) -> None:
        """تحليل فوري عند الطلب (يعرض النتيجة للطالب)."""
        chat_id = call.message.chat.id
        self._edit_or_send(call, "🔍 جاري التحليل الفوري ...")
        threading.Thread(target=lambda: self._scan(notify_chat=chat_id), daemon=True).start()

    def _handle_signal(self, signal: dict, notify_chat: Optional[int]) -> None:
        """التعامل مع إشارة قابلة للتنفيذ: تنفيذ آلي أو طلب تأكيد."""
        text = telegram_utils.format_signal(signal)

        # وضع أوتوماتيكي: ننفّذ مباشرةً إن سمح الحدّ اليومي.
        if self.state.auto_trade:
            if not self.state.can_trade_today():
                self._broadcast(f"⚠️ تجاوزنا حدّ الصفقات اليومي.\n{text}")
                return
            res = self.trader.place_market_order(signal)
            if res["ok"]:
                self.state.record_trade()
                self._broadcast(f"✅ تنفيذ آلي.\n{text}\n\n{res['message']}")
            else:
                self._broadcast(f"⚠️ فشل التنفيذ الآلي: {res['message']}\n{text}")
            return

        # وضع يدوي: نرسل الإشارة مع أزرار تأكيد.
        sid = self.state.register_pending(signal)
        markup = keyboards.confirm_signal_menu(sid)
        full = f"{text}\n\n⏳ بانتظار تأكيدك للتنفيذ:"
        if notify_chat:
            telegram_utils.safe_send(self.bot, notify_chat, full, reply_markup=markup)
        else:
            self._broadcast(full, markup)

    def _confirm_signal(self, call, sid: str) -> None:
        """تنفيذ إشارة معلّقة بعد تأكيد المستخدم."""
        signal = self.state.pop_pending(sid)
        if signal is None:
            self._edit_or_send(call, "⚠️ انتهت صلاحية الإشارة أو نُفّذت سابقاً.", keyboards.back_to_main())
            return
        if not self._ensure_mt5():
            self._edit_or_send(call, "⚠️ MT5 غير متصل — تعذّر التنفيذ.", keyboards.back_to_main())
            return
        res = self.trader.place_market_order(signal)
        if res["ok"]:
            self.state.record_trade()
            self._edit_or_send(call, f"✅ {res['message']}", keyboards.back_to_main())
        else:
            self._edit_or_send(call, f"⚠️ فشل التنفيذ: {res['message']}", keyboards.back_to_main())

    # ====================================================================== #
    #  الحالة والمراكز
    # ====================================================================== #
    def _show_status(self, call) -> None:
        s = self.state.summary()
        acc = self.fetcher.account_info() if self.fetcher.is_connected() else None
        lines = [
            "📈 *حالة البوت*",
            "──────────────────",
            f"⏱️ مدة التشغيل: {s['uptime']}",
            f"🔧 المحركات: {', '.join(s['engines']) or 'لا شيء'}",
            f"💱 الزوج/الفريم: {s['symbol']} / {s['timeframe']}",
            f"⚙️ الوضع: {'أوتوماتيكي' if s['auto_trade'] else 'تأكيد يدوي'}",
            f"📡 المراقبة: {'شغّالة' if s['live_running'] else 'متوقّفة'}",
            f"📨 إشارات مُرسلة: {s['signals_sent']}",
            f"💼 صفقات منفّذة: {s['trades_executed']} (اليوم: {s['trades_today']})",
        ]
        if acc:
            lines += [
                "──────────────────",
                f"🏦 الحساب: #{acc['login']} ({acc['server']})",
                f"💰 الرصيد: {acc['balance']} {acc['currency']}",
                f"📊 حقوق الملكية: {acc['equity']} | الربح: {acc['profit']}",
            ]
        else:
            lines.append("🔌 MT5: غير متصل")
        self._edit_or_send(call, "\n".join(lines), keyboards.back_to_main())

    def _show_positions(self, call) -> None:
        if not self._ensure_mt5():
            self._edit_or_send(call, "⚠️ MT5 غير متصل.", keyboards.back_to_main())
            return
        positions = self.trader.get_open_positions(self.state.symbol)
        if not positions:
            self._edit_or_send(call, "📋 لا مراكز مفتوحة حالياً.", keyboards.back_to_main())
            return
        lines = ["📋 *المراكز المفتوحة*", "──────────────────"]
        for p in positions:
            lines.append(
                f"#{p['ticket']} {p['type']} {p['volume']} @ {p['price_open']} "
                f"| الربح: {p['profit']:+.2f}"
            )
        self._edit_or_send(call, "\n".join(lines), keyboards.positions_menu(positions))

    def _close_one(self, call, ticket: int) -> None:
        res = self.trader.close_position(ticket)
        self._edit_or_send(call, ("✅ " if res["ok"] else "⚠️ ") + res["message"], keyboards.back_to_main())

    # ====================================================================== #
    #  لوحة الأدمن
    # ====================================================================== #
    def _handle_admin(self, call, data: str) -> None:
        if data == "adm:users":
            users = ", ".join(str(u) for u in self.state.authorized_users) or "لا أحد"
            text = (
                "👥 *المستخدمون المصرّح لهم*\n"
                f"{users}\n\n"
                "لإضافة مستخدم: أرسل `/adduser <id>`\n"
                "لإزالة مستخدم: أرسل `/deluser <id>`"
            )
            self._edit_or_send(call, text, keyboards.admin_menu())
        elif data == "adm:stats":
            s = self.state.summary()
            text = (
                "📊 *إحصاءات التشغيل*\n"
                f"⏱️ مدة التشغيل: {s['uptime']}\n"
                f"📨 إشارات: {s['signals_sent']}\n"
                f"💼 صفقات: {s['trades_executed']} (اليوم: {s['trades_today']})\n"
                f"👥 مستخدمون مصرّح لهم: {s['authorized_users']}\n"
                f"⚠️ آخر خطأ: {s['last_error'] or 'لا شيء'}"
            )
            self._edit_or_send(call, text, keyboards.admin_menu())
        elif data == "adm:mt5":
            connected = self.fetcher.is_connected() or self._ensure_mt5()
            acc = self.fetcher.account_info() if connected else None
            if acc:
                text = (
                    "🔌 *حالة MetaTrader5*: متصل ✅\n"
                    f"#{acc['login']} ({acc['server']})\n"
                    f"الرصيد: {acc['balance']} {acc['currency']}\n"
                    f"الرافعة: 1:{acc['leverage']}"
                )
            else:
                text = "🔌 *حالة MetaTrader5*: غير متصل ❌\nراجع إعدادات MT5_LOGIN/PASSWORD/SERVER."
            self._edit_or_send(call, text, keyboards.admin_menu())
        elif data == "adm:positions":
            self._show_positions(call)
        elif data == "adm:closeall":
            res = self.trader.close_all(self.state.symbol)
            self._edit_or_send(call, f"🛑 {res['message']}", keyboards.admin_menu())
        elif data == "adm:logs":
            self._edit_or_send(call, self._tail_logs(), keyboards.admin_menu())
        elif data == "adm:reload":
            issues = settings.validate_settings()
            text = "🔄 *فحص الإعدادات*\n" + ("\n".join(issues) if issues else "✅ كل شيء مضبوط.")
            self._edit_or_send(call, text, keyboards.admin_menu())

    def _tail_logs(self, lines: int = 20) -> str:
        """قراءة آخر أسطر ملف السجلّ."""
        try:
            with open(settings.LOG_FILE, "r", encoding="utf-8") as fh:
                tail = fh.readlines()[-lines:]
            return "📜 *آخر السجلّات*\n```\n" + "".join(tail)[-3500:] + "\n```"
        except Exception as exc:  # noqa: BLE001
            return f"⚠️ تعذّر قراءة السجلّ: {exc}"

    # ====================================================================== #
    #  أوامر إدارة المستخدمين (نصّية، للأدمن)
    # ====================================================================== #
    def _register_admin_commands(self) -> None:
        bot = self.bot

        @bot.message_handler(commands=["adduser"])
        @self.admin_only
        def add_user(message):
            parts = message.text.split()
            if len(parts) != 2 or not parts[1].isdigit():
                bot.send_message(message.chat.id, "الاستخدام: /adduser <id>")
                return
            self.state.add_user(int(parts[1]))
            bot.send_message(message.chat.id, f"✅ أُضيف المستخدم {parts[1]}.")

        @bot.message_handler(commands=["deluser"])
        @self.admin_only
        def del_user(message):
            parts = message.text.split()
            if len(parts) != 2 or not parts[1].isdigit():
                bot.send_message(message.chat.id, "الاستخدام: /deluser <id>")
                return
            ok = self.state.remove_user(int(parts[1]))
            bot.send_message(
                message.chat.id,
                f"✅ أُزيل المستخدم {parts[1]}." if ok else "⚠️ لا يمكن إزالة هذا المستخدم (أدمن؟).",
            )

    # ====================================================================== #
    #  التشغيل
    # ====================================================================== #
    def start(self) -> None:
        """بدء البوت (يسجّل أوامر الأدمن ثم يبدأ الاستماع)."""
        self._register_admin_commands()
        issues = settings.validate_settings()
        if issues:
            logger.warning("تحذيرات الإعدادات:\n%s", "\n".join(issues))
            self._broadcast("⚠️ تحذيرات عند الإقلاع:\n" + "\n".join(issues))
        logger.info("بدء تشغيل %s v%s", settings.APP_NAME, settings.APP_VERSION)
        self.bot.infinity_polling(skip_pending=True, timeout=30)


def main() -> None:
    """نقطة الدخول: التحقق من التوكن ثم تشغيل البوت."""
    if "PUT_YOUR" in settings.TELEGRAM_TOKEN:
        logger.error(
            "TELEGRAM_TOKEN غير مضبوط! اضبط متغيّر البيئة AETHERIA_TG_TOKEN ثم أعد التشغيل."
        )
        return
    if not ENGINE_REGISTRY:
        logger.error("لا توجد محركات مسجّلة!")
        return
    app = AetheriaBot(settings.TELEGRAM_TOKEN)
    app.start()


if __name__ == "__main__":
    main()
