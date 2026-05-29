# 🏛️ Aetheria v1 — بوت التداول الكمي

بوت تداول **شبه أوتوماتيكي** (Semi-Automated) يعتمد على **التحليل الكمي البحت**
(Pure Quantitative Analysis) كمرجع وحيد لاتخاذ القرارات — بدون عشوائية أو تقدير ذاتي.
يعمل على بيئة **Termux (Android)** عبر واجهة **Telegram**، ويتصل بـ MetaTrader 5
من خلال **MetaApi**.

---

## 🧱 البنية الهندسية (Engine Pattern)

```
aetheria/
├── config/
│   └── settings.py          # مفاتيح API، إعدادات MetaApi، روابط CSV، ثوابت عامة
├── engines/
│   ├── engine_base.py       # الكلاس المجرّد الأساس لكل المحركات (ABC)
│   ├── mean_reversion.py    # محرك الارتداد للمتوسط (Bollinger Bands + RSI)
│   └── trend_following.py   # محرك اتباع الاتجاه (EMA متعدد الفريمات) [قيد التطوير]
├── data/
│   ├── csv_fetcher.py       # جلب البيانات التاريخية من CSV (محلي/GitHub)
│   └── live_fetcher.py      # جلب البيانات اللحظية من MT5 عبر MetaApi [قيد التطوير]
├── utils/
│   └── telegram_utils.py    # تقطيع الرسائل الطويلة (≤4096) وتنسيق النصوص
├── main.py                  # نقطة الدخول: ربط المحركات بالبوت [قيد التطوير]
├── requirements.txt
└── README.md
```

> **فلسفة التصميم:** كل محرك مستقل تماماً وقابل للتشغيل بمفرده عبر
> `if __name__ == "__main__"`، ويرث من `EngineBase`. هذا يسهّل الصيانة،
> الاختبار، وإضافة استراتيجيات جديدة دون المساس بالباقي.

---

## ⚙️ التثبيت على Termux

```bash
# 1) تحديث Termux وتثبيت Python
pkg update && pkg upgrade -y
pkg install python git -y

# 2) استنساخ المستودع
git clone https://github.com/kalidergham/aqc.git
cd aqc/aetheria

# 3) تثبيت المكتبات (كلها متوافقة مع Termux، بدون ta-lib)
pip install -r requirements.txt

# 4) ضبط المتغيّرات السرّية (الأفضل من تعديل settings.py مباشرة)
export AETHERIA_TG_TOKEN="ضع_توكن_بوت_تلكرام_هنا"
export AETHERIA_METAAPI_TOKEN="ضع_توكن_MetaApi_هنا"
export AETHERIA_METAAPI_ACCOUNT_ID="ضع_account_id_هنا"

# 5) التشغيل
python main.py
```

---

## 🔗 ربط المشروع بمستودع GitHub وتحديثه (GitHub Sync)

البيانات التاريخية (ملفات CSV) تُستضاف على GitHub، ويجلبها `csv_fetcher` تلقائياً
عبر الروابط المعرّفة في `config/settings.py`.

### أول مرة (ربط مستودع جديد)
```bash
git init
git remote add origin https://github.com/<USERNAME>/<REPO>.git
git add .
git commit -m "Initial commit: Aetheria v1"
git branch -M main
git push -u origin main
```

### تحديث المشروع لاحقاً
```bash
git add .
git commit -m "وصف التعديل"
git push
```

### تحديث ملفات البيانات (CSV)
1. ارفع ملفات `XAU_15m_data.csv` / `XAU_1h_data.csv` / `XAU_4h_data.csv` للمستودع.
2. حدّث `GITHUB_RAW_BASE` و `CSV_URLS` في `config/settings.py` لتطابق
   اسم المستخدم/المستودع/الفرع.
3. الصيغة الرابطية للملف الخام:
   `https://raw.githubusercontent.com/<user>/<repo>/<branch>/<file>.csv`

---

## 📊 الأقسام الوظيفية

| القسم | الوصف |
|---|---|
| **محرك الباكتيست** | يختار المستخدم السنة + التايم فريم عبر أزرار inline، يجلب CSV، ويحسب: Win Rate, Max Drawdown, Profit Factor, Sharpe Ratio. |
| **محرك التداول اللحظي** | يتصل بـ MT5 (Demo) عبر MetaApi، يحلّل آخر كاندل، وعند الإشارة يرسل تنبيهاً مفصّلاً (الزوج/الاتجاه/الدخول/SL/TP) مع زر تأكيد يدوي. |

---

## 🧪 اختبار محرك بشكل مستقل

```bash
python -m engines.mean_reversion     # يشغّل اختبار المحرك على بيانات وهمية
python -m data.csv_fetcher           # يختبر جلب وتحليل CSV
python -m utils.telegram_utils       # يختبر تقطيع الرسائل
```

---

## ⚠️ إخلاء مسؤولية

هذا المشروع لأغراض تعليمية وبحثية في التحليل الكمي. التداول في الأسواق المالية
ينطوي على مخاطر عالية. **لا تشغّل البوت على حساب حقيقي قبل اختباره أشهراً على
حساب تجريبي (Demo).** الأداء التاريخي لا يضمن النتائج المستقبلية.
