"""
core/state.py
=============

إدارة حالة البوت أثناء التشغيل (State Management).

يحتفظ بكل ما يتغيّر زمن التشغيل في مكان واحد (Single Source of Truth):
    - المحركات المفعّلة، وضع التنفيذ (يدوي/أوتوماتيكي).
    - إعدادات قابلة للتعديل من الأزرار (الزوج، الفريم، المخاطرة...).
    - المستخدمون المصرّح لهم (الأدمن + المُضافون).
    - الإشارات المعلّقة بانتظار تأكيد المستخدم.
    - إحصاءات التشغيل (عدد الإشارات/الصفقات، وقت الإقلاع).
    - حالة المراقبة اللحظية (شغّالة/متوقفة) مع قفل آمن للخيوط.

الكائن مصمّم ليُنشأ مرة واحدة ويُمرَّر لكل المعالجات (handlers).
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

from config import settings


class BotState:
    """حاوية حالة البوت المركزية (thread-safe عبر قفل بسيط)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()

        # --- المحركات وإعدادات الاستراتيجية ---
        self.enabled_engines: List[str] = list(settings.DEFAULT_ENABLED_ENGINES)
        self.symbol: str = settings.DEFAULT_SYMBOL
        self.timeframe: str = settings.DEFAULT_LIVE_TIMEFRAME
        self.auto_trade: bool = settings.AUTO_TRADE

        # --- إعدادات المخاطر القابلة للتعديل من الأزرار ---
        self.risk_pct: float = settings.RISK_PER_TRADE_PCT
        self.max_trades_day: int = settings.MAX_TRADES_PER_DAY
        self.default_lot: float = settings.DEFAULT_LOT

        # --- التصريح (الأدمن مصرّح لهم تلقائياً) ---
        self.authorized_users: set[int] = set(settings.ADMIN_IDS)

        # --- المراقبة اللحظية ---
        self.live_running: bool = False
        self._stop_event = threading.Event()
        self.monitor_thread: Optional[threading.Thread] = None

        # --- الإشارات المعلّقة (id → signal dict) ---
        self.pending_signals: Dict[str, Dict[str, Any]] = {}
        self._signal_counter: int = 0

        # --- الإحصاءات ---
        self.start_time: float = time.time()
        self.signals_sent: int = 0
        self.trades_executed: int = 0
        self.trades_today: int = 0
        self._today: Optional[str] = None
        self.last_error: Optional[str] = None

    # ------------------------------ المحركات ------------------------------ #
    def toggle_engine(self, name: str) -> bool:
        """تفعيل/تعطيل محرك. يُرجع True إن أصبح مفعّلاً بعد التبديل."""
        with self._lock:
            if name in self.enabled_engines:
                self.enabled_engines.remove(name)
                return False
            self.enabled_engines.append(name)
            return True

    def is_engine_enabled(self, name: str) -> bool:
        with self._lock:
            return name in self.enabled_engines

    # ------------------------------ التصريح ------------------------------- #
    def is_authorized(self, user_id: int) -> bool:
        """هل المستخدم مصرّح له باستخدام البوت؟ (الأدمن دائماً مصرّح)."""
        return settings.is_admin(user_id) or user_id in self.authorized_users

    def add_user(self, user_id: int) -> None:
        with self._lock:
            self.authorized_users.add(user_id)

    def remove_user(self, user_id: int) -> bool:
        """إزالة مستخدم مصرّح (لا يمكن إزالة الأدمن)."""
        with self._lock:
            if settings.is_admin(user_id):
                return False
            self.authorized_users.discard(user_id)
            return True

    # -------------------------- الإشارات المعلّقة -------------------------- #
    def register_pending(self, signal: Dict[str, Any]) -> str:
        """تسجيل إشارة معلّقة بانتظار التأكيد، وإرجاع معرّفها الفريد."""
        with self._lock:
            self._signal_counter += 1
            sid = f"sig{self._signal_counter}"
            self.pending_signals[sid] = signal
            self.signals_sent += 1
            return sid

    def pop_pending(self, sid: str) -> Optional[Dict[str, Any]]:
        """سحب إشارة معلّقة (وإزالتها) حسب معرّفها."""
        with self._lock:
            return self.pending_signals.pop(sid, None)

    # ------------------------------ العدّادات ----------------------------- #
    def can_trade_today(self) -> bool:
        """هل ما زال بالإمكان فتح صفقات اليوم (ضمن الحد الأقصى)؟"""
        with self._lock:
            today = time.strftime("%Y-%m-%d")
            if today != self._today:
                self._today = today
                self.trades_today = 0
            return self.trades_today < self.max_trades_day

    def record_trade(self) -> None:
        with self._lock:
            self.trades_executed += 1
            self.trades_today += 1

    # ------------------------------- المراقبة ----------------------------- #
    def stop_requested(self) -> bool:
        return self._stop_event.is_set()

    def start_monitor(self, thread: threading.Thread) -> None:
        with self._lock:
            self._stop_event.clear()
            self.monitor_thread = thread
            self.live_running = True

    def stop_monitor(self) -> None:
        with self._lock:
            self._stop_event.set()
            self.live_running = False

    # ------------------------------ الإحصاءات ----------------------------- #
    def uptime_str(self) -> str:
        """مدة تشغيل البوت كنص مقروء."""
        secs = int(time.time() - self.start_time)
        h, rem = divmod(secs, 3600)
        m, s = divmod(rem, 60)
        return f"{h}س {m}د {s}ث"

    def summary(self) -> Dict[str, Any]:
        """ملخّص حالة البوت (لعرض الحالة/لوحة الأدمن)."""
        with self._lock:
            return {
                "engines": list(self.enabled_engines),
                "symbol": self.symbol,
                "timeframe": self.timeframe,
                "auto_trade": self.auto_trade,
                "risk_pct": self.risk_pct,
                "max_trades_day": self.max_trades_day,
                "live_running": self.live_running,
                "authorized_users": len(self.authorized_users),
                "signals_sent": self.signals_sent,
                "trades_executed": self.trades_executed,
                "trades_today": self.trades_today,
                "uptime": self.uptime_str(),
                "last_error": self.last_error,
            }


# نسخة عامة واحدة يستخدمها البوت بالكامل.
STATE = BotState()


if __name__ == "__main__":
    print("اختبار BotState...")
    s = BotState()
    print("المحركات المفعّلة:", s.enabled_engines)
    print("تبديل TrendFollowing →", s.toggle_engine("TrendFollowing"))
    print("المحركات بعد التبديل:", s.enabled_engines)
    sid = s.register_pending({"signal": "BUY", "symbol": "XAUUSD"})
    print("سجّل إشارة معلّقة:", sid, "| سحبها:", s.pop_pending(sid))
    print("الملخّص:", s.summary())
    print("✅ انتهى اختبار الحالة.")
