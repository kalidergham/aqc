"""
core/trader.py
==============

محرك التنفيذ اللحظي عبر MetaTrader 5 (المكتبة الرسمية، Windows).

المسؤوليات:
    - حساب حجم اللوت بناءً على نسبة المخاطرة ومواصفات الرمز.
    - تنفيذ أوامر السوق (شراء/بيع) مع SL/TP.
    - استعراض المراكز المفتوحة وإغلاقها (فردياً أو جماعياً — صمّام أمان).

ملاحظة: استيراد MetaTrader5 دفاعي ليبقى الملف قابلاً للفحص على غير Windows.
كل دالة تُعيد قاموساً واضح النتيجة بدل رفع استثناءات توقف البوت.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from config import settings
from engines.engine_base import SignalType

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5  # type: ignore

    MT5_AVAILABLE = True
except Exception as _exc:  # noqa: BLE001
    mt5 = None  # type: ignore
    MT5_AVAILABLE = False
    logger.warning("MetaTrader5 غير متاحة في Trader (%s).", _exc)


class Trader:
    """مُنفّذ الصفقات عبر MetaTrader 5."""

    def __init__(self) -> None:
        self.log = logging.getLogger("aetheria.trader")

    # ------------------------------------------------------------------ #
    def _ensure(self) -> bool:
        """التأكد من توفّر MT5 واتصال المنصة."""
        if not MT5_AVAILABLE:
            return False
        try:
            return mt5.terminal_info() is not None
        except Exception:  # noqa: BLE001
            return False

    def compute_lot(self, symbol: str, entry: float, sl: float, risk_amount: float) -> float:
        """
        حساب حجم اللوت بحيث تساوي الخسارة عند SL مبلغ المخاطرة المحدّد.

        الصيغة:
            الخسارة لكل لوت = (مسافة SL ÷ حجم النقطة) × قيمة النقطة
            اللوت = مبلغ المخاطرة ÷ الخسارة لكل لوت
        مع تقريبها لأقرب خطوة حجم وتقييدها بين الحد الأدنى/الأقصى للرمز.

        Returns:
            حجم اللوت (يسقط على DEFAULT_LOT عند تعذّر الحساب).
        """
        if not self._ensure():
            return settings.DEFAULT_LOT
        try:
            info = mt5.symbol_info(symbol)
            if info is None:
                return settings.DEFAULT_LOT

            tick_size = info.trade_tick_size or info.point
            tick_value = info.trade_tick_value
            sl_distance = abs(entry - sl)
            if tick_size <= 0 or tick_value <= 0 or sl_distance <= 0:
                return settings.DEFAULT_LOT

            loss_per_lot = (sl_distance / tick_size) * tick_value
            if loss_per_lot <= 0:
                return settings.DEFAULT_LOT

            lot = risk_amount / loss_per_lot

            # تقييد ضمن حدود الرمز وتقريب لأقرب خطوة.
            step = info.volume_step or 0.01
            lot = max(info.volume_min, min(info.volume_max, lot))
            lot = round(lot / step) * step
            return round(lot, 2)
        except Exception as exc:  # noqa: BLE001
            self.log.error("خطأ في حساب اللوت: %s", exc)
            return settings.DEFAULT_LOT

    # ------------------------------------------------------------------ #
    def place_market_order(
        self, signal: Dict[str, Any], lot: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        تنفيذ أمر سوق (شراء/بيع) بناءً على قاموس إشارة.

        Args:
            signal: قاموس الإشارة (يحوي signal/symbol/sl/tp...).
            lot: حجم محدّد؛ إن غاب يُحسب من المخاطرة أو يسقط على الافتراضي.

        Returns:
            قاموس نتيجة: {ok, ticket?, price?, message}.
        """
        if not self._ensure():
            return {"ok": False, "message": "MT5 غير متصل."}

        side = str(signal.get("signal", "")).upper()
        if side not in (SignalType.BUY.value, SignalType.SELL.value):
            return {"ok": False, "message": f"نوع إشارة غير قابل للتنفيذ: {side}"}

        symbol = signal.get("symbol", settings.DEFAULT_SYMBOL)
        sl = float(signal.get("sl") or 0.0)
        tp = float(signal.get("tp") or 0.0)

        try:
            if not mt5.symbol_select(symbol, True):
                return {"ok": False, "message": f"تعذّر تفعيل الرمز {symbol}."}

            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                return {"ok": False, "message": "تعذّر جلب السعر اللحظي."}

            if side == SignalType.BUY.value:
                order_type = mt5.ORDER_TYPE_BUY
                price = tick.ask
            else:
                order_type = mt5.ORDER_TYPE_SELL
                price = tick.bid

            # حساب اللوت من المخاطرة إن لم يُمرَّر صراحةً.
            if lot is None:
                acc = mt5.account_info()
                balance = acc.balance if acc else settings.INITIAL_BALANCE
                risk_amount = balance * (settings.RISK_PER_TRADE_PCT / 100.0)
                lot = self.compute_lot(symbol, price, sl, risk_amount)

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": float(lot),
                "type": order_type,
                "price": price,
                "sl": sl,
                "tp": tp,
                "deviation": settings.ORDER_DEVIATION,
                "magic": settings.MAGIC_NUMBER,
                "comment": "Aetheria",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }

            result = mt5.order_send(request)
            if result is None:
                return {"ok": False, "message": f"order_send فشل: {mt5.last_error()}"}
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                return {
                    "ok": False,
                    "message": f"رُفض الأمر (retcode={result.retcode}): {result.comment}",
                }
            return {
                "ok": True,
                "ticket": result.order,
                "price": result.price,
                "volume": result.volume,
                "message": f"تم تنفيذ {side} {result.volume} لوت @ {result.price}",
            }
        except Exception as exc:  # noqa: BLE001
            self.log.error("خطأ في تنفيذ الأمر: %s", exc)
            return {"ok": False, "message": f"خطأ: {exc}"}

    # ------------------------------------------------------------------ #
    def get_open_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """استعراض المراكز المفتوحة الخاصة بالبوت (حسب الرقم السحري)."""
        if not self._ensure():
            return []
        try:
            positions = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
            if positions is None:
                return []
            out = []
            for p in positions:
                if p.magic != settings.MAGIC_NUMBER:
                    continue  # نتجاهل المراكز غير الخاصة بالبوت
                out.append(
                    {
                        "ticket": p.ticket,
                        "symbol": p.symbol,
                        "type": "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
                        "volume": p.volume,
                        "price_open": p.price_open,
                        "sl": p.sl,
                        "tp": p.tp,
                        "profit": p.profit,
                    }
                )
            return out
        except Exception as exc:  # noqa: BLE001
            self.log.error("خطأ في جلب المراكز: %s", exc)
            return []

    def close_position(self, ticket: int) -> Dict[str, Any]:
        """إغلاق مركز محدّد برقمه (ticket) عبر أمر معاكس."""
        if not self._ensure():
            return {"ok": False, "message": "MT5 غير متصل."}
        try:
            positions = mt5.positions_get(ticket=ticket)
            if not positions:
                return {"ok": False, "message": f"المركز {ticket} غير موجود."}
            p = positions[0]
            tick = mt5.symbol_info_tick(p.symbol)
            if tick is None:
                return {"ok": False, "message": "تعذّر جلب السعر."}

            # أمر معاكس لإغلاق المركز.
            if p.type == mt5.POSITION_TYPE_BUY:
                order_type, price = mt5.ORDER_TYPE_SELL, tick.bid
            else:
                order_type, price = mt5.ORDER_TYPE_BUY, tick.ask

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": p.symbol,
                "volume": p.volume,
                "type": order_type,
                "position": p.ticket,
                "price": price,
                "deviation": settings.ORDER_DEVIATION,
                "magic": settings.MAGIC_NUMBER,
                "comment": "Aetheria-close",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            result = mt5.order_send(request)
            if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
                code = result.retcode if result else mt5.last_error()
                return {"ok": False, "message": f"فشل الإغلاق (code={code})."}
            return {"ok": True, "message": f"أُغلق المركز {ticket}."}
        except Exception as exc:  # noqa: BLE001
            self.log.error("خطأ في إغلاق المركز: %s", exc)
            return {"ok": False, "message": f"خطأ: {exc}"}

    def close_all(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """
        إغلاق كل مراكز البوت (صمّام الأمان / النظرية 23 — التدمير الذاتي).

        Returns:
            {ok, closed, failed, message}
        """
        positions = self.get_open_positions(symbol)
        closed, failed = 0, 0
        for p in positions:
            res = self.close_position(p["ticket"])
            if res["ok"]:
                closed += 1
            else:
                failed += 1
        return {
            "ok": failed == 0,
            "closed": closed,
            "failed": failed,
            "message": f"أُغلق {closed} مركز، فشل {failed}.",
        }


# --------------------------------------------------------------------------- #
# اختبار مستقل: python -m core.trader
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(f"MetaTrader5 متاح؟ {MT5_AVAILABLE}")
    trader = Trader()
    if not MT5_AVAILABLE:
        print("ℹ️ بيئة بلا MT5 — التنفيذ الفعلي يتطلب Windows + MT5 متصل.")
    else:
        print("المراكز المفتوحة:", trader.get_open_positions())
