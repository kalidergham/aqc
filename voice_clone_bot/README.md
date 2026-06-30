# بوت استنساخ الأصوات (Voice Cloning Bot)

بوت تليجرام بسيط مبني بمكتبتي `pyTelegramBotAPI (telebot)` و `requests`، يستنسخ صوت
المستخدم عبر ElevenLabs ثم ينطق أي نص بصوته. كل الكود في ملف واحد: `bot.py`.

## التثبيت على Termux

```bash
pkg update && pkg upgrade -y
pkg install python ffmpeg -y
pip install pyTelegramBotAPI requests
```

## الإعداد

افتح ملف `bot.py` وعدّل القيمتين في أعلى الملف:

```python
BOT_TOKEN = "ضع_توكن_البوت_هنا"
ELEVENLABS_API_KEY = "ضع_مفتاح_elevenlabs_هنا"
```

## التشغيل

```bash
python bot.py
```

## طريقة الاستخدام
1. أرسل `/start`.
2. أرسل مقطعاً صوتياً واضحاً (لا يقل عن 30 ثانية).
3. انتظر رسالة "تم استنساخ صوتك".
4. أرسل أي نص، فيصلك مقطع صوتي بصوتك.
5. `/start` لاستنساخ صوت جديد، و `/cancel` للإلغاء.

## ملاحظات
- ميزة Instant Voice Cloning تتطلب اشتراكاً مدفوعاً في ElevenLabs (Starter فأعلى).
- استخدم البوت على صوتك أو بإذن صريح من صاحب الصوت فقط.
