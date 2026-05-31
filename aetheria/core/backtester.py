"""
core/backtester.py
==================

محرك الباكتيست (Backtesting Engine).

يحاكي تنفيذ استراتيجية محرك معيّن على بيانات تاريخية، شمعةً بشمعة، مع
نموذج واقعي للتكاليف (سبريد) وإدارة المخاطر (مخاطرة ثابتة لكل صفقة)، ثم
يحسب مقاييس الأداء المعيارية:

    - Win Rate       : نسبة الصفقات الرابحة.
    - Profit Factor  : إجمالي الأرباح ÷ إجمالي الخسائر.
    - Max Drawdown   : أقصى تراجع نسبي في منحنى رأس المال.
    - Sharpe Ratio   : العائد المعدّل بالمخاطرة (تقريبي، معايَر بعدد الصفقات).

منهجية المحاكاة (لتفادي التحيّز الاستشرافي / look-ahead bias):
    1. تُحسب المؤشرات مرة واحدة على كامل البيانات.
    2. عند ظهور إشارة في إغلاق الشمعة i، يُفتح المركز في *افتتاح* الشمعة i+1.
    3. يُفحص ضرب SL/TP باستخدام high/low كل شمعة لاحقة.
    4. عند تطابق SL و TP في نفس الشمعة، يُفترض ضرب SL أولاً (افتراض متحفّظ).

النموذج المالي:
    - حجم المركز يُحسب بحيث تساوي الخسارة عند SL نسبةً ثابتة من رأس المال
      (RISK_PER_TRADE_PCT) — أي مخاطرة 1R لكل صفقة.
    - الربح/الخسارة يُقاس بمضاعفات R ويُحوّل لعملة الحساب.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional

import pandas as pd

from config import settings
from engines.engine_base import EngineBase, SignalType

logger = logging.getLogger(__name__)


class BacktestEngine:
    """
    مُنفّذ الباكتيست لمحرك واحد على DataFrame تاريخي.

    Attributes:
        engine          : نسخة المحرك (يجب أن يدعم خطّافات الباكتيست).
        initial_balance : رأس المال الابتدائي.
        risk_pct        : نسبة المخاطرة لكل صفقة (%).
        spread_price    : تكلفة السبريد محوّلة لسعر.
        max_trades_day  : حد أقصى لعدد الصفقات اليومية.
    """

    def __init__(
        self,
        engine: EngineBase,
        initial_balance: Optional[float] = None,
        risk_pct: Optional[float] = None,
        spread_pips: Optional[float] = None,
        max_trades_per_day: Optional[int] = None,
    ) -> None:
        self.engine = engine
        self.initial_balance = float(
            initial_balance if initial_balance is not None else settings.INITIAL_BALANCE
        )
        self.risk_pct = float(risk_pct if risk_pct is not None else settings.RISK_PER_TRADE_PCT)
        spread = spread_pips if spread_pips is not None else settings.SPREAD_PIPS
        self.spread_price = float(spread) * settings.PIP_SIZE
        self.max_trades_day = int(
            max_trades_per_day if max_trades_per_day is not None else settings.MAX_TRADES_PER_DAY
        )
        self.log = logging.getLogger("aetheria.backtester")

    # ------------------------------------------------------------------ #
    @staticmethod
    def _check_exit(side: str, sl: float, tp: float, high: float, low: float):
        """
        فحص ما إذا ضُربت SL أو TP خلال شمعة (بافتراض متحفّظ: SL أولاً).

        Returns:
            (hit: bool, exit_price: float|None, is_win: bool)
        """
        if side == SignalType.BUY.value:
            if low <= sl:                       # ضرب وقف الخسارة
                return True, sl, False
            if high >= tp:                      # ضرب الهدف
                return True, tp, True
        else:  # SELL
            if high >= sl:
                return True, sl, False
            if low <= tp:
                return True, tp, True
        return False, None, False

    def run(self, df: "pd.DataFrame", meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        تشغيل الباكتيست على DataFrame وإرجاع قاموس الإحصاءات.

        Args:
            df: بيانات OHLCV بفهرس زمني تصاعدي.
            meta: بيانات وصفية اختيارية (symbol/timeframe/period) للتقرير.

        Returns:
            قاموس إحصاءات متوافق مع utils.telegram_utils.format_backtest_report.
        """
        meta = meta or {}
        stats_base = {
            "engine": self.engine.name,
            "symbol": meta.get("symbol", getattr(self.engine, "symbol", "—")),
            "timeframe": meta.get("timeframe", "—"),
            "period": meta.get("period", "—"),
        }

        try:
            if df is None or len(df) < self.engine.min_rows + 2:
                return {**stats_base, **self._empty_stats(), "note": "بيانات غير كافية."}

            # 1) حساب المؤشرات مرة واحدة، ثم تحويلها لقائمة قواميس (أسرع للتكرار).
            d = self.engine.compute_indicators(df)
            records: List[dict] = d.to_dict("records")
            dates = list(d.index)
            n = len(records)

            equity = self.initial_balance
            peak = equity
            max_dd = 0.0
            trades: List[dict] = []
            returns: List[float] = []  # عائد كل صفقة كنسبة من رأس المال
            gross_profit = 0.0
            gross_loss = 0.0

            position: Optional[dict] = None
            current_day = None
            trades_today = 0

            start = self.engine.min_rows  # نبدأ بعد اكتمال المؤشرات

            for i in range(start, n):
                row = records[i]
                day = dates[i].date() if hasattr(dates[i], "date") else None

                # إعادة ضبط العدّاد اليومي.
                if day != current_day:
                    current_day = day
                    trades_today = 0

                # --- (أ) إدارة المركز المفتوح: فحص SL/TP على الشمعة الحالية ---
                if position is not None:
                    hit, exit_price, is_win = self._check_exit(
                        position["side"], position["sl"], position["tp"],
                        float(row["high"]), float(row["low"]),
                    )
                    if hit:
                        equity_before = equity
                        # ر/ح بالعملة = الوحدات × فرق السعر باتجاه الصفقة.
                        if position["side"] == SignalType.BUY.value:
                            pnl = position["units"] * (exit_price - position["entry"])
                        else:
                            pnl = position["units"] * (position["entry"] - exit_price)
                        equity += pnl
                        returns.append(pnl / equity_before if equity_before > 0 else 0.0)
                        if pnl >= 0:
                            gross_profit += pnl
                        else:
                            gross_loss += -pnl
                        trades.append(
                            {
                                "side": position["side"],
                                "entry": position["entry"],
                                "exit": exit_price,
                                "pnl": pnl,
                                "win": is_win,
                                "entry_time": position["entry_time"],
                                "exit_time": dates[i],
                            }
                        )
                        # تحديث منحنى رأس المال و أقصى تراجع.
                        peak = max(peak, equity)
                        if peak > 0:
                            max_dd = max(max_dd, (peak - equity) / peak)
                        position = None

                # --- (ب) الدخول: إشارة عند إغلاق i، تُنفّذ عند افتتاح i+1 ---
                if position is None and i + 1 < n and trades_today < self.max_trades_day:
                    side = self.engine.generate_entry(row)
                    if side is not None:
                        raw_entry = float(records[i + 1]["open"])
                        # تطبيق السبريد: الشراء يدفع أعلى، البيع يبيع أدنى.
                        if side == SignalType.BUY:
                            entry = raw_entry + self.spread_price
                        else:
                            entry = raw_entry - self.spread_price

                        sl, tp = self.engine.compute_sl_tp(side, entry, row)
                        risk_per_unit = abs(entry - sl)
                        if risk_per_unit <= 0 or math.isnan(risk_per_unit):
                            continue  # تخطّي إشارة غير صالحة

                        risk_amount = equity * (self.risk_pct / 100.0)
                        units = risk_amount / risk_per_unit
                        position = {
                            "side": side.value,
                            "entry": entry,
                            "sl": sl,
                            "tp": tp,
                            "units": units,
                            "entry_time": dates[i + 1],
                        }
                        trades_today += 1

            return {**stats_base, **self._compute_stats(equity, trades, returns, gross_profit, gross_loss, max_dd)}

        except Exception as exc:  # noqa: BLE001
            self.log.error("خطأ في الباكتيست: %s", exc)
            return {**stats_base, **self._empty_stats(), "note": f"خطأ: {exc}"}

    # ------------------------------------------------------------------ #
    def _empty_stats(self) -> Dict[str, Any]:
        """إحصاءات صفرية (عند غياب الصفقات أو وجود خطأ)."""
        return {
            "total_trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
            "profit_factor": 0.0, "max_drawdown": 0.0, "sharpe_ratio": 0.0,
            "net_profit": 0.0, "return_pct": 0.0, "final_balance": self.initial_balance,
            "avg_win": 0.0, "avg_loss": 0.0, "expectancy": 0.0,
        }

    def _compute_stats(
        self, equity, trades, returns, gross_profit, gross_loss, max_dd
    ) -> Dict[str, Any]:
        """حساب مقاييس الأداء النهائية من نتائج المحاكاة."""
        total = len(trades)
        if total == 0:
            return self._empty_stats()

        wins = sum(1 for t in trades if t["pnl"] >= 0)
        losses = total - wins
        win_rate = wins / total * 100.0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

        win_pnls = [t["pnl"] for t in trades if t["pnl"] >= 0]
        loss_pnls = [t["pnl"] for t in trades if t["pnl"] < 0]
        avg_win = sum(win_pnls) / len(win_pnls) if win_pnls else 0.0
        avg_loss = sum(loss_pnls) / len(loss_pnls) if loss_pnls else 0.0
        expectancy = sum(t["pnl"] for t in trades) / total

        # Sharpe تقريبي على عوائد الصفقات، معايَر بالجذر التربيعي لعددها.
        sharpe = 0.0
        if len(returns) > 1:
            mean_r = sum(returns) / len(returns)
            var = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
            std = math.sqrt(var)
            if std > 0:
                rf = settings.RISK_FREE_RATE
                sharpe = (mean_r - rf) / std * math.sqrt(len(returns))

        net_profit = equity - self.initial_balance
        return {
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate, 2),
            "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else 999.99,
            "max_drawdown": round(max_dd * 100.0, 2),
            "sharpe_ratio": round(sharpe, 2),
            "net_profit": round(net_profit, 2),
            "return_pct": round(net_profit / self.initial_balance * 100.0, 2),
            "final_balance": round(equity, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "expectancy": round(expectancy, 2),
        }


# --------------------------------------------------------------------------- #
# اختبار مستقل: python -m core.backtester
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import numpy as np
    from engines.mean_reversion import MeanReversionEngine

    # بيانات وهمية متذبذبة (مناسبة للارتداد للمتوسط).
    rng = np.random.default_rng(1)
    n = 2000
    t = np.arange(n)
    close = 2300 + 50 * np.sin(2 * np.pi * t / 60) + rng.normal(0, 6, n).cumsum() * 0.05
    high = close + rng.uniform(1, 6, n)
    low = close - rng.uniform(1, 6, n)
    open_ = np.concatenate([[close[0]], close[:-1]]) + rng.uniform(-2, 2, n)
    volume = rng.integers(50, 500, n)
    idx = pd.date_range("2023-01-01", periods=n, freq="h")
    df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx
    )

    bt = BacktestEngine(MeanReversionEngine())
    stats = bt.run(df, {"symbol": "XAUUSD", "timeframe": "1h", "period": "وهمي"})
    print("نتائج الباكتيست على بيانات وهمية:")
    for k, v in stats.items():
        print(f"  {k}: {v}")
