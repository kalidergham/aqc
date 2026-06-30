"""
=====================================================================
بوت تليجرام لاستنساخ الأصوات (Voice Cloning) عبر ElevenLabs
=====================================================================
كل شيء في ملف واحد: الإعدادات + الحالات + خدمة الـ API + المعالجات + التشغيل.

البنية:
    - FSM لإدارة حالة المستخدم (بانتظار الصوت  ->  بانتظار النص).
    - aiohttp للطلبات غير المتزامنة (سرعة عالية وعدم تجميد البوت).
    - ElevenLabs API:
        * مرحلة التدريب: رفع المقطع الصوتي إلى /voices/add للحصول على voice_id.
        * مرحلة التوليد: استخدام voice_id مع نموذج eleven_multilingual_v2.
    - حفظ الصوت الناتج بصيغة OGG/Opus لتوافق "بصمة" تليجرام الصوتية.

متطلبات التشغيل على Termux (انظر README بأسفل هذا الملف):
    pkg update && pkg upgrade -y
    pkg install python ffmpeg -y
    pip install aiogram aiohttp python-dotenv
=====================================================================
"""

import asyncio
import logging
import os
import uuid
from dataclasses import dataclass

import aiohttp
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import FSInputFile, Message
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# 1) إعداد نظام السجلات (Logging) لمتابعة عمل البوت وتتبع الأخطاء
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("voice_clone_bot")


# ===========================================================================
# 2) الإعدادات: تحميل المفاتيح الحساسة من ملف .env
# ===========================================================================
load_dotenv()  # تحميل متغيرات البيئة من ملف .env


@dataclass(frozen=True)
class Config:
    """كائن ثابت يحمل جميع إعدادات البوت المقروءة من البيئة."""

    bot_token: str            # توكن بوت تليجرام
    elevenlabs_api_key: str   # مفتاح ElevenLabs API
    elevenlabs_model: str     # النموذج المستخدم (متعدد اللغات للعربية)
    min_voice_duration: int   # الحد الأدنى لمدة المقطع الصوتي (ثوانٍ)
    max_text_length: int      # الحد الأقصى لعدد أحرف النص
    temp_dir: str             # مجلد الملفات المؤقتة


def load_config() -> Config:
    """تقرأ المتغيرات من البيئة وتتحقق من وجود القيم الإلزامية."""
    bot_token = os.getenv("BOT_TOKEN")
    elevenlabs_api_key = os.getenv("ELEVENLABS_API_KEY")

    # التحقق الصارم من المفاتيح الإلزامية قبل التشغيل
    if not bot_token:
        raise RuntimeError("المتغير BOT_TOKEN غير موجود في ملف .env")
    if not elevenlabs_api_key:
        raise RuntimeError("المتغير ELEVENLABS_API_KEY غير موجود في ملف .env")

    return Config(
        bot_token=bot_token,
        elevenlabs_api_key=elevenlabs_api_key,
        # نفرض النموذج متعدد اللغات حصراً لضمان دقة اللغة العربية
        elevenlabs_model=os.getenv("ELEVENLABS_MODEL", "eleven_multilingual_v2"),
        min_voice_duration=int(os.getenv("MIN_VOICE_DURATION", "30")),
        max_text_length=int(os.getenv("MAX_TEXT_LENGTH", "2500")),
        temp_dir=os.getenv("TEMP_DIR", "temp"),
    )


# ===========================================================================
# 3) حالات الـ FSM: تعريف مراحل رحلة المستخدم
# ===========================================================================
class CloneStates(StatesGroup):
    """حالات آلة الحالة المنتهية لإدارة خطوات الاستنساخ والتوليد."""

    waiting_for_voice = State()  # المرحلة 1: بانتظار البصمة الصوتية (تدريب)
    waiting_for_text = State()   # المرحلة 2: بانتظار النص (توليد)


# ===========================================================================
# 4) أدوات الصوت: تحويل الملفات إلى صيغة OGG/Opus عبر ffmpeg
# ===========================================================================
async def convert_to_ogg(input_path: str, output_path: str) -> str:
    """
    تحويل أي ملف صوتي إلى صيغة OGG/Opus المطلوبة لرسائل تليجرام الصوتية.
    نستخدم ffmpeg كعملية فرعية غير متزامنة حتى لا يتجمد البوت.

    تُطلق: FileNotFoundError إذا لم يكن ffmpeg مثبتاً.
            RuntimeError إذا فشلت عملية التحويل.
    """
    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y",
        "-i", input_path,          # الملف المدخل
        "-c:a", "libopus",         # ترميز Opus المطلوب لبصمة تليجرام
        "-b:a", "64k",             # معدل بت مناسب للصوت
        "-ar", "48000",            # تردد العينات القياسي لـ Opus
        output_path,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()

    if process.returncode != 0:
        # في حال فشل ffmpeg نرفع الخطأ مع رسالته للتشخيص
        raise RuntimeError(stderr.decode(errors="ignore"))
    return output_path


def safe_remove(path: str) -> None:
    """حذف ملف مؤقت بأمان مع تجاهل الأخطاء (تنظيف الذاكرة المؤقتة)."""
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError as error:
        logger.warning("تعذّر حذف الملف المؤقت %s: %s", path, error)


# ===========================================================================
# 5) خدمة ElevenLabs: كلاس مسؤول عن كل الاتصالات مع الـ API
# ===========================================================================
class ElevenLabsError(Exception):
    """استثناء مخصص لأخطاء ElevenLabs API لتسهيل معالجتها."""


class ElevenLabsClient:
    """
    عميل غير متزامن للتعامل مع ElevenLabs.
    يفصل تماماً بين عملية الاستنساخ (التدريب) وعملية التوليد (Inference).
    """

    BASE_URL = "https://api.elevenlabs.io/v1"

    def __init__(self, api_key: str, model_id: str, timeout: int = 120) -> None:
        # ترويسة المصادقة المطلوبة في كل طلب
        self._headers = {"xi-api-key": api_key}
        self._model_id = model_id
        # مهلة زمنية للطلبات لتفادي التعليق إلى ما لا نهاية
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    async def clone_voice(self, name: str, audio_path: str) -> str:
        """
        (مرحلة التدريب) رفع المقطع الصوتي لإنشاء صوت جديد.
        تُرسل ملف الصوت إلى نقطة النهاية /voices/add.

        تُرجع: voice_id الخاص بالصوت المُنشأ.
        تُطلق: ElevenLabsError عند أي فشل.
        """
        url = f"{self.BASE_URL}/voices/add"

        # قراءة بايتات الملف الصوتي قبل الرفع
        try:
            with open(audio_path, "rb") as audio_file:
                audio_bytes = audio_file.read()
        except OSError as error:
            raise ElevenLabsError(f"تعذّر قراءة الملف الصوتي: {error}")

        # تجهيز بيانات الطلب على شكل multipart/form-data
        form = aiohttp.FormData()
        form.add_field("name", name)
        form.add_field(
            "files",
            audio_bytes,
            filename=os.path.basename(audio_path),
            content_type="audio/ogg",
        )

        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.post(url, data=form, headers=self._headers) as resp:
                    payload = await resp.json(content_type=None)
                    if resp.status != 200:
                        # رسالة خطأ مفهومة في حال رفض الـ API الطلب
                        raise ElevenLabsError(
                            f"فشل الاستنساخ ({resp.status}): {self._extract_error(payload)}"
                        )
                    voice_id = payload.get("voice_id")
                    if not voice_id:
                        raise ElevenLabsError("لم تُرجع الخدمة معرّف الصوت (voice_id).")
                    return voice_id
        except aiohttp.ClientError as error:
            # خطأ على مستوى الشبكة (انقطاع الاتصال مثلاً)
            raise ElevenLabsError(f"خطأ في الاتصال بالشبكة أثناء الاستنساخ: {error}")

    async def text_to_speech(self, voice_id: str, text: str, output_path: str) -> str:
        """
        (مرحلة التوليد) تحويل النص إلى كلام باستخدام voice_id محفوظ مسبقاً.
        تستخدم نموذج eleven_multilingual_v2 حصراً لدقة اللغة العربية.

        تُرجع: مسار ملف الصوت الناتج (mp3).
        تُطلق: ElevenLabsError عند أي فشل.
        """
        url = f"{self.BASE_URL}/text-to-speech/{voice_id}"
        params = {"output_format": "mp3_44100_128"}
        body = {
            "text": text,
            "model_id": self._model_id,  # النموذج متعدد اللغات
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
                "style": 0.0,
                "use_speaker_boost": True,
            },
        }
        headers = {**self._headers, "Content-Type": "application/json"}

        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.post(url, params=params, json=body, headers=headers) as resp:
                    if resp.status != 200:
                        # محاولة استخراج رسالة الخطأ من الاستجابة
                        try:
                            payload = await resp.json(content_type=None)
                            message_text = self._extract_error(payload)
                        except Exception:
                            message_text = await resp.text()
                        raise ElevenLabsError(
                            f"فشل توليد الصوت ({resp.status}): {message_text}"
                        )

                    # كتابة الصوت الناتج تدفقياً (streaming) إلى الملف
                    with open(output_path, "wb") as out_file:
                        async for chunk in resp.content.iter_chunked(8192):
                            out_file.write(chunk)
            return output_path
        except aiohttp.ClientError as error:
            raise ElevenLabsError(f"خطأ في الاتصال بالشبكة أثناء التوليد: {error}")

    @staticmethod
    def _extract_error(payload) -> str:
        """استخراج رسالة خطأ مقروءة من استجابة ElevenLabs بصيغها المختلفة."""
        if isinstance(payload, dict):
            detail = payload.get("detail")
            if isinstance(detail, dict):
                return detail.get("message", str(detail))
            if detail:
                return str(detail)
        return str(payload)


# ===========================================================================
# 6) المعالجات (Handlers): منطق البوت عبر الأوامر والحالات
# ===========================================================================
router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    """
    أمر /start: يرحب بالمستخدم ويبدأ رحلة جديدة (يمسح أي صوت سابق).
    ينقل الحالة إلى "بانتظار الصوت".
    """
    await state.clear()  # مسح أي voice_id قديم لبدء استنساخ صوت جديد
    await state.set_state(CloneStates.waiting_for_voice)
    await message.answer(
        "👋 <b>أهلاً بك في بوت استنساخ الأصوات!</b>\n\n"
        "🎙️ أرسل الآن <b>مقطعاً صوتياً (Voice)</b> بصوتك "
        f"لا تقل مدته عن <b>{config.min_voice_duration} ثانية</b> وبجودة عالية وواضحة.\n\n"
        "سأستخدمه لاستنساخ صوتك، ثم تستطيع إرسال أي نص لأنطقه بصوتك.\n"
        "للإلغاء في أي وقت أرسل /cancel"
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    """أمر /cancel: إلغاء العملية الحالية وإعادة ضبط الحالة."""
    await state.clear()
    await message.answer("❌ تم الإلغاء. أرسل /start للبدء من جديد.")


@router.message(CloneStates.waiting_for_voice, F.voice | F.audio)
async def handle_voice(
    message: Message,
    state: FSMContext,
    bot: Bot,
    el_client: ElevenLabsClient,
) -> None:
    """
    (مرحلة التدريب) استقبال المقطع الصوتي واستنساخه.
    الخطوات: التحقق من المدة -> تنزيل الملف -> رفعه للاستنساخ -> حفظ voice_id.
    """
    media = message.voice or message.audio
    duration = media.duration or 0

    # التحقق من أن المقطع يحقق الحد الأدنى للمدة لضمان جودة الاستنساخ
    if duration < config.min_voice_duration:
        await message.answer(
            f"⚠️ المقطع قصير ({duration} ثانية). "
            f"الرجاء إرسال مقطع لا تقل مدته عن {config.min_voice_duration} ثانية."
        )
        return

    status = await message.answer("⏳ جارٍ معالجة الصوت واستنساخه، يرجى الانتظار...")

    os.makedirs(config.temp_dir, exist_ok=True)
    local_path = os.path.join(config.temp_dir, f"{uuid.uuid4().hex}.ogg")

    try:
        # تنزيل الملف الصوتي من خوادم تليجرام إلى التخزين المحلي
        tg_file = await bot.get_file(media.file_id)
        await bot.download_file(tg_file.file_path, destination=local_path)

        # رفع الملف إلى ElevenLabs لإنشاء صوت جديد
        voice_name = f"user_{message.from_user.id}"
        voice_id = await el_client.clone_voice(voice_name, local_path)

        # تخزين voice_id في ذاكرة الحالة (يبقى حتى يغيّر المستخدم صوته)
        await state.update_data(voice_id=voice_id)
        await state.set_state(CloneStates.waiting_for_text)

        await status.edit_text(
            "✅ <b>تم استنساخ صوتك بنجاح!</b>\n\n"
            "✍️ أرسل الآن النص الذي تريد تحويله إلى كلام بصوتك."
        )
    except ElevenLabsError as error:
        logger.exception("فشل الاستنساخ")
        await status.edit_text(f"⚠️ {error}\n\nأرسل /start للمحاولة مجدداً.")
        await state.clear()
    except Exception:
        logger.exception("خطأ غير متوقع أثناء الاستنساخ")
        await status.edit_text("⚠️ حدث خطأ غير متوقع. حاول لاحقاً عبر /start.")
        await state.clear()
    finally:
        # تنظيف الملف المؤقت دائماً
        safe_remove(local_path)


@router.message(CloneStates.waiting_for_voice)
async def handle_voice_invalid(message: Message) -> None:
    """رسالة إرشادية إذا أرسل المستخدم شيئاً غير الصوت في مرحلة التدريب."""
    await message.answer("🎙️ الرجاء إرسال <b>مقطع صوتي</b> لاستنساخه، أو /cancel للإلغاء.")


@router.message(CloneStates.waiting_for_text, F.text & ~F.text.startswith("/"))
async def handle_text(
    message: Message,
    state: FSMContext,
    el_client: ElevenLabsClient,
) -> None:
    """
    (مرحلة التوليد) تحويل النص إلى صوت باستخدام voice_id المحفوظ.
    الخطوات: جلب voice_id -> توليد mp3 -> تحويله إلى ogg -> إرساله كبصمة صوتية.
    """
    data = await state.get_data()
    voice_id = data.get("voice_id")

    # التأكد من وجود صوت مستنسخ مسبقاً
    if not voice_id:
        await message.answer("⚠️ لا يوجد صوت مستنسخ. أرسل /start للبدء.")
        await state.clear()
        return

    text = message.text.strip()

    # التحقق من طول النص لتفادي رفض الـ API
    if len(text) > config.max_text_length:
        await message.answer(
            f"⚠️ النص طويل جداً. الحد الأقصى {config.max_text_length} حرف."
        )
        return

    status = await message.answer("🎙️ جارٍ توليد الصوت بصوتك...")

    os.makedirs(config.temp_dir, exist_ok=True)
    unique = uuid.uuid4().hex
    mp3_path = os.path.join(config.temp_dir, f"{unique}.mp3")
    ogg_path = os.path.join(config.temp_dir, f"{unique}.ogg")

    try:
        # توليد الصوت (mp3) ثم تحويله إلى ogg/opus لبصمة تليجرام
        await el_client.text_to_speech(voice_id, text, mp3_path)
        await convert_to_ogg(mp3_path, ogg_path)

        # إرسال النتيجة كرسالة صوتية (بصمة)
        await message.answer_voice(FSInputFile(ogg_path))
        await status.delete()
        await message.answer(
            "✅ تم! أرسل نصاً آخر لتوليده بنفس الصوت، أو /start لاستنساخ صوت جديد."
        )
    except ElevenLabsError as error:
        logger.exception("فشل التوليد")
        await status.edit_text(f"⚠️ {error}")
    except FileNotFoundError:
        # ffmpeg غير مثبت على النظام
        logger.exception("ffmpeg غير موجود")
        await status.edit_text(
            "⚠️ أداة ffmpeg غير مثبتة. ثبّتها عبر:\n<code>pkg install ffmpeg</code>"
        )
    except Exception:
        logger.exception("خطأ غير متوقع أثناء التوليد")
        await status.edit_text("⚠️ حدث خطأ أثناء التوليد. حاول مجدداً.")
    finally:
        # تنظيف الملفات المؤقتة دائماً
        safe_remove(mp3_path)
        safe_remove(ogg_path)


@router.message(CloneStates.waiting_for_text)
async def handle_text_invalid(message: Message) -> None:
    """رسالة إرشادية إذا أرسل المستخدم شيئاً غير النص في مرحلة التوليد."""
    await message.answer("✍️ الرجاء إرسال <b>نص</b> لتحويله إلى صوت، أو /start لصوت جديد.")


# ===========================================================================
# 7) نقطة التشغيل: تهيئة البوت والـ Dispatcher وبدء الاستطلاع (Polling)
# ===========================================================================
config = load_config()  # تحميل الإعدادات عند استيراد الملف


async def main() -> None:
    """تهيئة البوت وحقن التبعيات وبدء استقبال التحديثات."""
    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    # نستخدم تخزيناً في الذاكرة لحالات الـ FSM
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_router(router)

    # إنشاء عميل ElevenLabs مرة واحدة وحقنه في المعالجات
    el_client = ElevenLabsClient(
        api_key=config.elevenlabs_api_key,
        model_id=config.elevenlabs_model,
    )

    logger.info("✅ البوت يعمل الآن...")
    try:
        # حقن config و el_client تلقائياً كوسائط في المعالجات
        await dispatcher.start_polling(bot, el_client=el_client)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("🛑 تم إيقاف البوت.")
