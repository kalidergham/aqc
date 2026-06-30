import os
import uuid
import subprocess

import requests
import telebot

BOT_TOKEN = "ضع_توكن_البوت_هنا"
ELEVENLABS_API_KEY = "ضع_مفتاح_elevenlabs_هنا"
ELEVENLABS_MODEL = "eleven_multilingual_v2"
MIN_VOICE_DURATION = 30
MAX_TEXT_LENGTH = 2500
TEMP_DIR = "temp"

bot = telebot.TeleBot(BOT_TOKEN)

user_states = {}
user_voices = {}


def clone_voice(name, audio_path):
    url = "https://api.elevenlabs.io/v1/voices/add"
    headers = {"xi-api-key": ELEVENLABS_API_KEY}
    with open(audio_path, "rb") as audio_file:
        files = {"files": (os.path.basename(audio_path), audio_file, "audio/ogg")}
        data = {"name": name}
        response = requests.post(url, headers=headers, data=data, files=files, timeout=120)
    if response.status_code != 200:
        raise RuntimeError(f"فشل الاستنساخ ({response.status_code}): {response.text}")
    voice_id = response.json().get("voice_id")
    if not voice_id:
        raise RuntimeError("لم يتم إرجاع معرّف الصوت من الخدمة")
    return voice_id


def text_to_speech(voice_id, text, output_path):
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"}
    params = {"output_format": "mp3_44100_128"}
    body = {
        "text": text,
        "model_id": ELEVENLABS_MODEL,
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0.0,
            "use_speaker_boost": True,
        },
    }
    response = requests.post(url, headers=headers, params=params, json=body, timeout=120)
    if response.status_code != 200:
        raise RuntimeError(f"فشل التوليد ({response.status_code}): {response.text}")
    with open(output_path, "wb") as out_file:
        out_file.write(response.content)
    return output_path


def convert_to_ogg(input_path, output_path):
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", input_path, "-c:a", "libopus", "-b:a", "64k", "-ar", "48000", output_path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode(errors="ignore"))
    return output_path


def safe_remove(path):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


@bot.message_handler(commands=["start"])
def cmd_start(message):
    chat_id = message.chat.id
    user_states[chat_id] = "waiting_for_voice"
    user_voices.pop(chat_id, None)
    bot.send_message(
        chat_id,
        "أهلاً بك في بوت استنساخ الأصوات!\n\n"
        f"أرسل الآن مقطعاً صوتياً بصوتك لا تقل مدته عن {MIN_VOICE_DURATION} ثانية وبجودة عالية.\n"
        "للإلغاء أرسل /cancel",
    )


@bot.message_handler(commands=["cancel"])
def cmd_cancel(message):
    chat_id = message.chat.id
    user_states.pop(chat_id, None)
    user_voices.pop(chat_id, None)
    bot.send_message(chat_id, "تم الإلغاء. أرسل /start للبدء من جديد.")


@bot.message_handler(content_types=["voice", "audio"])
def handle_voice(message):
    chat_id = message.chat.id
    if user_states.get(chat_id) != "waiting_for_voice":
        bot.send_message(chat_id, "أرسل /start للبدء أولاً.")
        return

    media = message.voice or message.audio
    duration = media.duration or 0
    if duration < MIN_VOICE_DURATION:
        bot.send_message(chat_id, f"المقطع قصير ({duration} ثانية). أرسل مقطعاً لا يقل عن {MIN_VOICE_DURATION} ثانية.")
        return

    status = bot.send_message(chat_id, "جارٍ معالجة الصوت واستنساخه، يرجى الانتظار...")
    os.makedirs(TEMP_DIR, exist_ok=True)
    local_path = os.path.join(TEMP_DIR, f"{uuid.uuid4().hex}.ogg")

    try:
        file_info = bot.get_file(media.file_id)
        downloaded = bot.download_file(file_info.file_path)
        with open(local_path, "wb") as voice_file:
            voice_file.write(downloaded)

        voice_id = clone_voice(f"user_{chat_id}", local_path)
        user_voices[chat_id] = voice_id
        user_states[chat_id] = "waiting_for_text"

        bot.edit_message_text(
            "تم استنساخ صوتك بنجاح!\n\nأرسل الآن النص الذي تريد تحويله إلى كلام بصوتك.",
            chat_id,
            status.message_id,
        )
    except Exception as error:
        bot.edit_message_text(f"حدث خطأ: {error}\n\nأرسل /start للمحاولة مجدداً.", chat_id, status.message_id)
        user_states.pop(chat_id, None)
    finally:
        safe_remove(local_path)


@bot.message_handler(content_types=["text"], func=lambda message: not message.text.startswith("/"))
def handle_text(message):
    chat_id = message.chat.id
    state = user_states.get(chat_id)

    if state == "waiting_for_voice":
        bot.send_message(chat_id, "الرجاء إرسال مقطع صوتي لاستنساخه، أو /cancel للإلغاء.")
        return
    if state != "waiting_for_text":
        bot.send_message(chat_id, "أرسل /start للبدء أولاً.")
        return

    voice_id = user_voices.get(chat_id)
    if not voice_id:
        bot.send_message(chat_id, "لا يوجد صوت مستنسخ. أرسل /start للبدء.")
        user_states.pop(chat_id, None)
        return

    text = message.text.strip()
    if len(text) > MAX_TEXT_LENGTH:
        bot.send_message(chat_id, f"النص طويل جداً. الحد الأقصى {MAX_TEXT_LENGTH} حرف.")
        return

    status = bot.send_message(chat_id, "جارٍ توليد الصوت بصوتك...")
    os.makedirs(TEMP_DIR, exist_ok=True)
    unique = uuid.uuid4().hex
    mp3_path = os.path.join(TEMP_DIR, f"{unique}.mp3")
    ogg_path = os.path.join(TEMP_DIR, f"{unique}.ogg")

    try:
        text_to_speech(voice_id, text, mp3_path)
        convert_to_ogg(mp3_path, ogg_path)
        with open(ogg_path, "rb") as voice_file:
            bot.send_voice(chat_id, voice_file)
        bot.delete_message(chat_id, status.message_id)
        bot.send_message(chat_id, "تم! أرسل نصاً آخر، أو /start لاستنساخ صوت جديد.")
    except FileNotFoundError:
        bot.edit_message_text("أداة ffmpeg غير مثبتة. ثبّتها عبر: pkg install ffmpeg", chat_id, status.message_id)
    except Exception as error:
        bot.edit_message_text(f"حدث خطأ أثناء التوليد: {error}", chat_id, status.message_id)
    finally:
        safe_remove(mp3_path)
        safe_remove(ogg_path)


if __name__ == "__main__":
    bot.infinity_polling()
