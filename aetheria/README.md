# 🏛️ Aetheria v1 — بوت التداول الكمي (Windows + MetaTrader5)

بوت تداول **شبه أوتوماتيكي / أوتوماتيكي** للذهب (XAUUSD) يعتمد على **التحليل
الكمي البحت**. يعمل على **الحاسوب (Windows)** عبر مكتبة **MetaTrader5**
الرسمية مباشرةً (بدون MetaApi)، وواجهة **Telegram** كاملة بالأزرار + **لوحة أدمن**.

---

## 🧱 البنية الهندسية

```
aetheria/
├── config/
│   └── settings.py          # توكن تلكرام، إعدادات MT5، الأدمن، المخاطر، روابط CSV
├── engines/
│   ├── engine_base.py       # الكلاس المجرّد + Signal/SignalType + خطّافات الباكتيست
│   ├── mean_reversion.py    # محرك الارتداد للمتوسط (Bollinger + RSI + ATR)
│   ├── trend_following.py   # محرك اتباع الاتجاه (EMA + ADX)
│   └── __init__.py          # ENGINE_REGISTRY + build_engine
├── data/
│   ├── csv_fetcher.py       # بيانات تاريخية (CSV محلي/GitHub) للباكتيست
│   └── live_fetcher.py      # بيانات لحظية من MetaTrader5
├── core/
│   ├── backtester.py        # محرك الباكتيست (Win Rate/PF/Drawdown/Sharpe)
│   ├── trader.py            # تنفيذ الأوامر وإدارة المراكز عبر MT5
│   └── state.py             # إدارة حالة البوت (محركات/مستخدمون/إحصاءات)
├── utils/
│   ├── telegram_utils.py    # تقطيع الرسائل ≤4096 + تنسيق التقارير/الإشارات
│   ├── keyboards.py         # كل لوحات الأزرار التفاعلية
│   └── auth.py              # التصريح (أدمن / مستخدمون مصرّح لهم)
├── main.py                  # نقطة الدخول: ربط كل شيء + لوحة الأدمن
├── requirements.txt
└── README.md
```

---

## ✅ المتطلبات

- **Windows** (لأن مكتبة MetaTrader5 تعمل على Windows فقط).
- **Python 3.10+** (64-bit، ليتوافق مع MT5).
- **برنامج MetaTrader 5** مثبّتاً وفيه حساب (تجريبي يُفضّل) ومسجّل دخوله.
- بوت تلكرام (توكن من [@BotFather](https://t.me/BotFather)).

---

## ⚙️ التثبيت والتشغيل (خطوة بخطوة)

### 1) تثبيت بايثون والمكتبات
```bat
:: نزّل Python 3.10+ (64-bit) من python.org وفعّل "Add to PATH"
git clone -b feat/aetheria-v1-bot https://github.com/kalidergham/aqc.git
cd aqc\aetheria
pip install -r requirements.txt
```

### 2) تجهيز MetaTrader 5
- ثبّت MT5 وسجّل دخول حسابك (Demo موصى به للبداية).
- فعّل: Tools → Options → Expert Advisors → *Allow Algo Trading*.
- تأكّد أن رمز الذهب ظاهر في Market Watch (غالباً `XAUUSD`؛ بعض الوسطاء
  يستخدمون `GOLD` أو `XAUUSDm` — عدّل `DEFAULT_SYMBOL` في الإعدادات لو لزم).

### 3) ضبط المتغيّرات (PowerShell)
```powershell
setx AETHERIA_TG_TOKEN     "123456:ABC..."          # توكن البوت
setx AETHERIA_ADMIN_IDS    "123456789"              # معرّفك (أرسل /id للبوت لمعرفته)
setx AETHERIA_MT5_LOGIN    "51234567"               # رقم حساب MT5
setx AETHERIA_MT5_PASSWORD "كلمة_سر_التداول"
setx AETHERIA_MT5_SERVER   "MetaQuotes-Demo"        # اسم خادم الوسيط
setx AETHERIA_MT5_PATH     "C:\Program Files\MetaTrader 5\terminal64.exe"  # اختياري
```
> ⚠️ بعد `setx` **أعد فتح نافذة الأوامر** حتى تُحمّل المتغيّرات.

### 4) التشغيل
```bat
python main.py
```
ثم افتح بوتك في تلكرام وأرسل `/start`.

---

## 🎛️ التحكّم الكامل عبر الأزرار

| القائمة | الوظيفة |
|---|---|
| 📊 **باكتيست** | اختر المحرك ← الفريم ← السنة، ويعطيك تقريراً كاملاً (Win Rate, Profit Factor, Max Drawdown, Sharpe, العائد). |
| 📡 **تداول لحظي** | بدء/إيقاف المراقبة، تحليل فوري، عرض المراكز. عند ظهور إشارة: تنبيه مفصّل + زر تأكيد (أو تنفيذ آلي حسب الوضع). |
| ⚙️ **الإعدادات** | تبديل الوضع (يدوي/أوتوماتيكي)، نسبة المخاطرة، حد الصفقات اليومي، الفريم، تفعيل/تعطيل المحركات. |
| 📈 **الحالة** | مدة التشغيل، المحركات، حالة MT5، الرصيد، الإحصاءات. |
| 🛡️ **لوحة الأدمن** | إدارة المستخدمين، الإحصاءات، حالة MT5، **إغلاق كل الصفقات (طوارئ)**، السجلّات، إعادة فحص الإعدادات. |

**أوامر نصّية:** `/start` `/menu` `/help` `/id` `/adduser <id>` `/deluser <id>`

---

## 🔒 الأمان والصلاحيات
- فقط **الأدمن** (في `AETHERIA_ADMIN_IDS`) والمستخدمون المُضافون يقدرون استخدام البوت.
- لوحة الأدمن والإجراءات الحسّاسة (إغلاق الصفقات) محصورة بالأدمن.
- الوضع الافتراضي **يدوي** (يطلب تأكيدك قبل أي صفقة) — للأمان.

---

## 🧪 اختبار المكوّنات بشكل مستقل
```bash
python -m config.settings          # فحص الإعدادات
python -m engines.mean_reversion   # اختبار محرك الارتداد
python -m engines.trend_following  # اختبار محرك الاتجاه
python -m core.backtester          # اختبار الباكتيست على بيانات وهمية
python -m core.state               # اختبار إدارة الحالة
python -m utils.auth               # اختبار التصريح
python -m utils.telegram_utils     # اختبار تقطيع الرسائل
```

---

## 🔗 ربط المشروع بـ GitHub وتحديثه
```bash
git add .
git commit -m "وصف التعديل"
git push
```
البيانات التاريخية (CSV) تُجلب تلقائياً من الروابط في `settings.py`
(`GITHUB_OWNER/REPO/BRANCH`). عدّلها إن غيّرت المستودع.

---

## ⚠️ إخلاء مسؤولية
مشروع تعليمي/بحثي. التداول مخاطرة عالية. **لا تشغّله على حساب حقيقي قبل
اختباره أشهراً على Demo.** الأداء التاريخي لا يضمن المستقبل.
