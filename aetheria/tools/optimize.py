"""
tools/optimize.py
=================

محسّن معاملات (Parameter Optimizer) مستقل لمحرّكي أثيريا الحقيقيين:
    - MeanReversion  (≡ النظرية 18: تذبذب الجاذبية الإحصائية)
    - TrendFollowing (≡ النظرية 21: التوافق/الزخم الاتجاهي + ADX)

⚙️ مكتوب بـ Python خالص (بدون pandas/numpy) ليعمل في أي بيئة، ويُطابق
معادلات المحرّكات في aetheria/engines/* ومنطق aetheria/core/backtester.py
بالضبط (تم التحقق من التطابق).

🔬 المنهجية الصادقة (لتجنّب الغش بالـ Overfitting):
    - تقسيم البيانات: فترة تحسين (Train) وفترة اختبار خارج العينة (Test).
    - يُختار أفضل إعداد حسب أداء فترة *التحسين*، ثم يُبلَّغ عن أدائه في فترة
      *الاختبار* (هذا هو المقياس الصادق الوحيد).
    - يُسجَّل كل إعداد (شفافية كاملة)، وإن كانت كل النتائج سالبة يُقال ذلك صراحةً.

التشغيل:
    python tools/optimize.py
"""

from __future__ import annotations

import csv
import json
import math
import os
from datetime import datetime
from itertools import product

# ----------------------------- ثوابت عامة (مطابقة للإعدادات) ----------------- #
PIP = 0.1
SPREAD_PRICE = 2.0 * PIP        # SPREAD_PIPS=2.0
RISK_PCT = 1.0
INIT_BALANCE = 10_000.0
HV_RATIO = 1.75                 # نسبة مضاعف التقلّب العالي (2.0 → 3.5)

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(HERE, "..", "..", "XAU_1h_data.csv")
RESULTS_DIR = os.path.join(HERE, "results")

# نوافذ التحسين/الاختبار (سنوات).
TRAIN_YEARS = set(range(2014, 2021))   # 2014..2020 (تحسين)
TEST_YEARS = set(range(2021, 2026))    # 2021..2025 (اختبار خارج العينة)


# =========================================================================== #
#  قراءة البيانات
# =========================================================================== #
def load_csv(path: str):
    """قراءة ملف CSV (Date;O;H;L;C;V) وإرجاع المصفوفات."""
    dt, O, H, L, C = [], [], [], [], []
    with open(path, encoding="utf-8") as f:
        r = csv.reader(f, delimiter=";")
        next(r, None)  # رأس
        for row in r:
            if len(row) < 5:
                continue
            try:
                d = datetime.strptime(row[0], "%Y.%m.%d %H:%M")
                o, h, l, c = float(row[1]), float(row[2]), float(row[3]), float(row[4])
            except (ValueError, IndexError):
                continue
            dt.append(d); O.append(o); H.append(h); L.append(l); C.append(c)
    return dt, O, H, L, C


# =========================================================================== #
#  المؤشرات (مطابقة لصيغ المحرّكات)
# =========================================================================== #
def ema(values, span):
    """EMA بصيغة ewm(span, adjust=False)."""
    a = 2.0 / (span + 1.0)
    out = [None] * len(values)
    prev = values[0]
    out[0] = prev
    for i in range(1, len(values)):
        prev = a * values[i] + (1 - a) * prev
        out[i] = prev
    return out


def wilder_rma(values, period, seed_index=0):
    """RMA وايلدر: ewm(alpha=1/period, adjust=False)، تبدأ من أول قيمة صالحة."""
    a = 1.0 / period
    out = [None] * len(values)
    prev = values[seed_index]
    out[seed_index] = prev
    for i in range(seed_index + 1, len(values)):
        prev = a * values[i] + (1 - a) * prev
        out[i] = prev
    return out


def rsi_wilder(close, period):
    """RSI وايلدر (يطابق engines: gain/loss + RMA)."""
    n = len(close)
    out = [float("nan")] * n
    a = 1.0 / period
    ag = al = None
    for i in range(1, n):
        d = close[i] - close[i - 1]
        g = d if d > 0 else 0.0
        l = -d if d < 0 else 0.0
        if ag is None:
            ag, al = g, l
        else:
            ag = a * g + (1 - a) * ag
            al = a * l + (1 - a) * al
        out[i] = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
    return out


def atr_wilder(H, L, C, period):
    """ATR وايلدر (TR ثم RMA، seeded بـ tr[0])."""
    n = len(C)
    tr = [H[0] - L[0]] + [0.0] * (n - 1)
    for i in range(1, n):
        tr[i] = max(H[i] - L[i], abs(H[i] - C[i - 1]), abs(L[i] - C[i - 1]))
    return wilder_rma(tr, period)


def bollinger(close, period, k):
    """نطاقات بولينجر: SMA + انحراف معياري للمجتمع (ddof=0)."""
    n = len(close)
    mb = [float("nan")] * n
    up = [float("nan")] * n
    lo = [float("nan")] * n
    ps = 0.0
    ps2 = 0.0
    from collections import deque
    win = deque()
    for i in range(n):
        win.append(close[i]); ps += close[i]; ps2 += close[i] * close[i]
        if len(win) > period:
            old = win.popleft(); ps -= old; ps2 -= old * old
        if len(win) == period:
            mean = ps / period
            var = max(ps2 / period - mean * mean, 0.0)
            sd = math.sqrt(var)
            mb[i] = mean; up[i] = mean + k * sd; lo[i] = mean - k * sd
    return mb, up, lo


def adx_wilder(H, L, C, atr_list, period):
    """ADX وايلدر (يطابق محرك TrendFollowing)."""
    n = len(C)
    plus_dm = [0.0] * n
    minus_dm = [0.0] * n
    for i in range(1, n):
        up_move = H[i] - H[i - 1]
        down_move = L[i - 1] - L[i]
        plus_dm[i] = up_move if (up_move > down_move and up_move > 0) else 0.0
        minus_dm[i] = down_move if (down_move > up_move and down_move > 0) else 0.0
    rma_plus = wilder_rma(plus_dm, period)
    rma_minus = wilder_rma(minus_dm, period)
    dx = [0.0] * n
    for i in range(n):
        at = atr_list[i]
        if at is None or at == 0:
            dx[i] = 0.0
            continue
        pdi = 100.0 * rma_plus[i] / at
        mdi = 100.0 * rma_minus[i] / at
        s = pdi + mdi
        dx[i] = 0.0 if s == 0 else 100.0 * abs(pdi - mdi) / s
    return wilder_rma(dx, period)


# =========================================================================== #
#  محرّك الباكتيست العام (مطابق لـ core/backtester.py)
# =========================================================================== #
def backtest(O, H, L, C, dates, start, entry_fn, sltp_fn, max_trades_day, year_set):
    """
    محاكاة بشمعةً بشمعة. يُسمح بالدخول فقط في سنوات year_set.

    entry_fn(i) -> "BUY"/"SELL"/None
    sltp_fn(side, entry, i) -> (sl, tp)
    """
    n = len(C)
    equity = INIT_BALANCE
    peak = equity
    max_dd = 0.0
    returns = []
    gp = gl = 0.0
    wins = total = 0
    pos = None
    cur_day = None
    td = 0

    for i in range(start, n):
        in_window = dates[i].year in year_set
        day = dates[i].date()
        if day != cur_day:
            cur_day = day
            td = 0

        # (أ) إدارة المركز المفتوح
        if pos is not None:
            side = pos["side"]; sl = pos["sl"]; tp = pos["tp"]
            hit = False; px = None
            if side == "BUY":
                if L[i] <= sl:
                    hit, px = True, sl
                elif H[i] >= tp:
                    hit, px = True, tp
            else:
                if H[i] >= sl:
                    hit, px = True, sl
                elif L[i] <= tp:
                    hit, px = True, tp
            if hit:
                eb = equity
                pnl = pos["units"] * ((px - pos["entry"]) if side == "BUY" else (pos["entry"] - px))
                equity += pnl
                returns.append(pnl / eb if eb > 0 else 0.0)
                if pnl >= 0:
                    gp += pnl; wins += 1
                else:
                    gl += -pnl
                total += 1
                peak = max(peak, equity)
                if peak > 0:
                    max_dd = max(max_dd, (peak - equity) / peak)
                pos = None

        # (ب) الدخول: إشارة عند i، تنفيذ عند افتتاح i+1
        if pos is None and in_window and i + 1 < n and td < max_trades_day:
            side = entry_fn(i)
            if side:
                raw = O[i + 1]
                entry = raw + SPREAD_PRICE if side == "BUY" else raw - SPREAD_PRICE
                sl, tp = sltp_fn(side, entry, i)
                rpu = abs(entry - sl)
                if rpu > 0 and not math.isnan(rpu):
                    units = (equity * RISK_PCT / 100.0) / rpu
                    pos = {"side": side, "entry": entry, "sl": sl, "tp": tp, "units": units}
                    td += 1

    # الإحصاءات
    if total == 0:
        return {"trades": 0, "win_rate": 0.0, "profit_factor": 0.0,
                "max_drawdown": 0.0, "sharpe": 0.0, "net_profit": 0.0, "return_pct": 0.0}
    pf = (gp / gl) if gl > 0 else 999.99
    sharpe = 0.0
    if len(returns) > 1:
        mr = sum(returns) / len(returns)
        var = sum((x - mr) ** 2 for x in returns) / (len(returns) - 1)
        sd = math.sqrt(var)
        if sd > 0:
            sharpe = mr / sd * math.sqrt(len(returns))
    net = equity - INIT_BALANCE
    return {
        "trades": total,
        "win_rate": round(wins / total * 100, 2),
        "profit_factor": round(pf, 2),
        "max_drawdown": round(max_dd * 100, 2),
        "sharpe": round(sharpe, 2),
        "net_profit": round(net, 2),
        "return_pct": round(net / INIT_BALANCE * 100, 2),
    }


# =========================================================================== #
#  بناء دوال الإشارة لكل محرك
# =========================================================================== #
def build_mean_reversion(O, H, L, C, p):
    """يُحضّر مؤشرات MeanReversion ويُرجع (entry_fn, sltp_fn, start)."""
    mb, up, lo = bollinger(C, p["bb_period"], p["bb_std"])
    rsi = rsi_wilder(C, p["rsi_period"])
    atr = atr_wilder(H, L, C, p["atr_period"])
    start = max(p["bb_period"], p["rsi_period"], p["atr_period"]) + 5
    os_, ob = p["oversold"], p["overbought"]
    mult_lo, rr = p["atr_mult"], p["rr"]

    def entry_fn(i):
        if math.isnan(lo[i]) or math.isnan(up[i]) or math.isnan(rsi[i]):
            return None
        if C[i] <= lo[i] and rsi[i] <= os_:
            return "BUY"
        if C[i] >= up[i] and rsi[i] >= ob:
            return "SELL"
        return None

    def sltp_fn(side, entry, i):
        at = atr[i]
        mult = mult_lo * HV_RATIO if at > entry * 0.004 else mult_lo
        dist = at * mult
        if side == "BUY":
            sl = entry - dist; tp = mb[i]
            if (tp - entry) < rr * dist:
                tp = entry + rr * dist
        else:
            sl = entry + dist; tp = mb[i]
            if (entry - tp) < rr * dist:
                tp = entry - rr * dist
        return sl, tp

    return entry_fn, sltp_fn, start


def build_trend_following(O, H, L, C, p):
    """يُحضّر مؤشرات TrendFollowing ويُرجع (entry_fn, sltp_fn, start)."""
    ef = ema(C, p["ema_fast"])
    es = ema(C, p["ema_slow"])
    atr = atr_wilder(H, L, C, p["atr_period"])
    adx = adx_wilder(H, L, C, atr, p["adx_period"])
    n = len(C)
    cross = [0] * n
    for i in range(1, n):
        diff = ef[i] - es[i]
        pdiff = ef[i - 1] - es[i - 1]
        if diff > 0 and pdiff <= 0:
            cross[i] = 1
        elif diff < 0 and pdiff >= 0:
            cross[i] = -1
    start = p["ema_slow"] + p["adx_period"] + 5
    thr, mult, rr = p["adx_threshold"], p["atr_mult"], p["rr"]

    def entry_fn(i):
        if adx[i] is None or adx[i] < thr:
            return None
        if cross[i] == 1:
            return "BUY"
        if cross[i] == -1:
            return "SELL"
        return None

    def sltp_fn(side, entry, i):
        at = atr[i]
        m = mult * HV_RATIO if at > entry * 0.004 else mult
        dist = at * m
        if side == "BUY":
            return entry - dist, entry + rr * dist
        return entry + dist, entry - rr * dist

    return entry_fn, sltp_fn, start


# =========================================================================== #
#  شبكات المعاملات (≥10 لكل محرك، قيم مختلفة، صفقات/يوم 1-10)
# =========================================================================== #
def mean_reversion_grid():
    # 24 إعداد مميّز (قيم مختلفة فعلاً). max_trades_day=10 (الحد الأعلى المطلوب).
    combos = []
    for bb_std, (os_, ob), atr_mult, rr in product(
        [2.0, 2.5],
        [(30, 70), (25, 75), (20, 80)],
        [1.5, 2.0],
        [1.3, 2.0],
    ):
        combos.append({
            "bb_period": 20, "bb_std": bb_std, "rsi_period": 14,
            "oversold": os_, "overbought": ob, "atr_period": 14,
            "atr_mult": atr_mult, "rr": rr, "max_trades_day": 10,
        })
    return combos


def trend_following_grid():
    # 18 إعداد مميّز. max_trades_day=10.
    combos = []
    for (ef, es), thr, rr in product(
        [(20, 50), (50, 200), (20, 100)],
        [15, 20, 25],
        [1.5, 2.0],
    ):
        combos.append({
            "ema_fast": ef, "ema_slow": es, "adx_period": 14,
            "adx_threshold": thr, "atr_period": 14,
            "atr_mult": 2.0, "rr": rr, "max_trades_day": 10,
        })
    return combos


# =========================================================================== #
#  تشغيل التحسين لمحرك
# =========================================================================== #
def optimize_engine(name, builder, grid, data):
    dt, O, H, L, C = data
    results = []
    print(f"\n=== تحسين {name} ({len(grid)} إعداد) ===")
    for idx, p in enumerate(grid, 1):
        entry_fn, sltp_fn, start = builder(O, H, L, C, p)
        train = backtest(O, H, L, C, dt, start, entry_fn, sltp_fn, p["max_trades_day"], TRAIN_YEARS)
        test = backtest(O, H, L, C, dt, start, entry_fn, sltp_fn, p["max_trades_day"], TEST_YEARS)
        results.append({"params": p, "train": train, "test": test})
        print(f"  [{idx:2d}/{len(grid)}] PF train={train['profit_factor']:.2f} "
              f"test={test['profit_factor']:.2f} | net test={test['net_profit']:+.0f} "
              f"| trades tr/te={train['trades']}/{test['trades']}")

    # اختيار الأفضل: PF تدريب أعلى، بشرط حدّ أدنى من الصفقات في الفترتين.
    eligible = [r for r in results if r["train"]["trades"] >= 30 and r["test"]["trades"] >= 10]
    pool = eligible if eligible else results
    best = max(pool, key=lambda r: r["train"]["profit_factor"])
    # ترتيب إضافي حسب أداء الاختبار للعرض.
    by_test = sorted(results, key=lambda r: r["test"]["net_profit"], reverse=True)
    return {"engine": name, "best": best, "top_by_test": by_test[:3], "all": results}


# =========================================================================== #
#  كتابة النتائج (JSON + Markdown)
# =========================================================================== #
def write_results(res, theory_id, theory_name):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    engine = res["engine"]
    base = f"th_{theory_id}_{engine}"
    payload = {
        "theory_id": theory_id,
        "theory_name": theory_name,
        "engine": engine,
        "data": "XAUUSD 1h",
        "train_years": f"{min(TRAIN_YEARS)}-{max(TRAIN_YEARS)}",
        "test_years": f"{min(TEST_YEARS)}-{max(TEST_YEARS)}",
        "method": "in-sample train selection, out-of-sample test reporting",
        "best_params": res["best"]["params"],
        "best_train": res["best"]["train"],
        "best_test": res["best"]["test"],
        "all_runs": res["all"],
    }
    json_path = os.path.join(RESULTS_DIR, base + ".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    b = res["best"]
    md = []
    md.append(f"# {base}")
    md.append(f"\n**النظرية:** {theory_id} — {theory_name}")
    md.append(f"**المحرك:** {engine}  |  **البيانات:** XAUUSD 1h")
    md.append(f"**التحسين:** {min(TRAIN_YEARS)}-{max(TRAIN_YEARS)}  |  "
              f"**الاختبار (خارج العينة):** {min(TEST_YEARS)}-{max(TEST_YEARS)}")
    md.append("\n## ✅ أفضل القيم (Best Parameters)\n")
    md.append("```json")
    md.append(json.dumps(b["params"], ensure_ascii=False, indent=2))
    md.append("```")
    md.append("\n## 📊 الأداء\n")
    md.append("| المقياس | فترة التحسين (Train) | فترة الاختبار (Test, خارج العينة) |")
    md.append("|---|---|---|")
    for key, lbl in [("trades", "عدد الصفقات"), ("win_rate", "نسبة الربح %"),
                      ("profit_factor", "Profit Factor"), ("max_drawdown", "Max Drawdown %"),
                      ("sharpe", "Sharpe"), ("net_profit", "صافي الربح"),
                      ("return_pct", "العائد %")]:
        md.append(f"| {lbl} | {b['train'][key]} | {b['test'][key]} |")

    verdict = "✅ مربح خارج العينة" if b["test"]["net_profit"] > 0 and b["test"]["profit_factor"] > 1 \
        else "❌ غير مربح خارج العينة (لم تثبت النظرية أفضليةً حقيقية)"
    md.append(f"\n## 🧾 الحكم الصادق\n{verdict}")
    md.append(f"\n> أفضل عائد اختبار بين كل الإعدادات: "
              f"{max(r['test']['net_profit'] for r in res['all']):+.2f}")

    md_path = os.path.join(RESULTS_DIR, base + ".md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    return json_path, md_path, payload


# =========================================================================== #
if __name__ == "__main__":
    print(f"قراءة البيانات: {DATA_PATH}")
    data = load_csv(DATA_PATH)
    print(f"عدد الشموع: {len(data[4]):,} | المدى: {data[0][0]} → {data[0][-1]}")

    mr = optimize_engine("MeanReversion", build_mean_reversion, mean_reversion_grid(), data)
    tf = optimize_engine("TrendFollowing", build_trend_following, trend_following_grid(), data)

    jp1, mp1, _ = write_results(mr, 18, "Mean Reversion (تذبذب الجاذبية الإحصائية)")
    jp2, mp2, _ = write_results(tf, 21, "Tri-Consensus / Trend Following (التوافق الاتجاهي)")

    print("\n" + "=" * 60)
    print("أفضل القيم (خارج العينة):")
    for r, tid in [(mr, 18), (tf, 21)]:
        b = r["best"]
        print(f"\n■ th_{tid}_{r['engine']}")
        print(f"  params: {b['params']}")
        print(f"  TEST  : PF={b['test']['profit_factor']} net={b['test']['net_profit']:+.0f} "
              f"WR={b['test']['win_rate']}% trades={b['test']['trades']} DD={b['test']['max_drawdown']}%")
    print("\nالملفات المكتوبة:")
    for pth in (jp1, mp1, jp2, mp2):
        print("  " + pth)
