"""UZEX AI Hackathon - Telegram bot (Uzbek + Russian) answering questions about the exchange deal registry.

Env: TELEGRAM_TOKEN, GEMINI_API_KEY, optional GEMINI_MODEL, BOT_USERNAME, PORT
Run: python bot.py
"""
import os, re, time, asyncio, threading, logging, json, hmac, hashlib, base64
from concurrent.futures import TimeoutError as FutureTimeoutError
from pathlib import Path
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qsl

from telegram import (Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyParameters,
                      ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton, BotCommand,
                      WebAppInfo, MenuButtonWebApp)
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

import agent, extras

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
log = logging.getLogger("bot")

TOKEN = os.environ["TELEGRAM_TOKEN"]
BOT_USERNAME = os.environ.get("BOT_USERNAME", "")
BASE_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://uzex-bot-tbm8.onrender.com").rstrip("/")
MINI_APP_URL = os.environ.get("MINI_APP_URL", f"{BASE_URL}/app")
WEB_DIR = Path(__file__).resolve().parent / "webapp"
WELCOME_IMAGE = Path(__file__).resolve().parent / "welcome.png"
WELCOME_ANIMATION = WEB_DIR / "assistant.gif"

WELCOME = (
    "UZEX Bitimlar AI\n"
    "Birja bitimlari bo‘yicha ma’lumotga asoslangan yordamchi.\n\n"
    "500 000 ta bitim reyestri · 03.01.2022–30.10.2026\n"
    "O‘zbekcha yoki ruscha yozing yoki ovozli savol yuboring. Javoblar reyestrga asoslanadi.\n\n"
    "Здравствуйте! AI-помощник по реестру сделок UZEX.\n"
    "500 000 сделок · 03.01.2022–30.10.2026\n"
    "Задайте вопрос на узбекском или русском или отправьте голосовое сообщение. Ответы основаны на реестре."
)

HISTORY: dict[int, list] = {}
LOCKS: dict[int, asyncio.Lock] = {}

def preferred_language(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> str:
    saved = ctx.user_data.get("lang")
    if saved in ("uz", "ru"):
        return saved
    user = getattr(update, "effective_user", None) or getattr(update, "from_user", None)
    code = getattr(user, "language_code", "") or ""
    return "ru" if code.lower().startswith("ru") else "uz"

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    HISTORY.pop(update.effective_chat.id, None)
    ctx.user_data["lang"] = preferred_language(update, ctx)
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Ilovani ochish · Открыть приложение", web_app=WebAppInfo(url=MINI_APP_URL))],
        [InlineKeyboardButton("🇺🇿 Misol savol", callback_data="sample:uz"),
         InlineKeyboardButton("🇷🇺 Пример вопроса", callback_data="sample:ru")],
    ])
    if WELCOME_ANIMATION.exists():
        with WELCOME_ANIMATION.open("rb") as animation:
            await update.message.reply_animation(animation=animation, caption=WELCOME, reply_markup=buttons)
    elif WELCOME_IMAGE.exists():
        with WELCOME_IMAGE.open("rb") as photo:
            await update.message.reply_photo(photo=photo, caption=WELCOME, reply_markup=buttons)
    else:
        await update.message.reply_text(WELCOME, reply_markup=buttons)

EXAMPLE_QUESTIONS = [
    "2025-yilda eng ko‘p savdo qilingan 5 ta tovar qaysi?",
    "2025-yilda eng ko‘p bitim tuzgan 5 ta xaridor kim?",
    "2024 va 2025-yillarda paxta narxi qanday o‘zgargan?",
    "2025-yilda nechta bitim bekor qilingan?",
    "Какие товары лидировали по обороту в 2025 году?",
    "В каком регионе было больше всего сделок в 2025 году?",
]

async def examples_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rows = [[KeyboardButton(q)] for q in EXAMPLE_QUESTIONS]
    ru = ctx.user_data.get("lang") == "ru"
    await update.message.reply_text(
        "Выберите пример вопроса или напишите свой:" if ru else
        "Savol namunalaridan birini tanlang yoki o‘z savolingizni yozing:",
        reply_markup=ReplyKeyboardMarkup(rows, resize_keyboard=True, one_time_keyboard=True))

async def clear_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    HISTORY.pop(update.effective_chat.id, None)
    msg = "Контекст диалога очищен. Задайте новый вопрос." if ctx.user_data.get("lang") == "ru" else "Suhbat konteksti tozalandi. Yangi savol yuboring."
    await update.message.reply_text(msg)

async def hide_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = "Примеры скрыты." if ctx.user_data.get("lang") == "ru" else "Namunalar yashirildi."
    await update.message.reply_text(msg, reply_markup=ReplyKeyboardRemove())

async def set_commands(app):
    try:
        await app.bot.set_my_commands([
            BotCommand("start", "Botni boshlash"),
            BotCommand("examples", "Savol namunalarini ko‘rish"),
            BotCommand("clear", "Suhbat kontekstini tozalash"),
            BotCommand("hide", "Namuna tugmalarini yashirish"),
            BotCommand("test", "Ulanishni tekshirish"),
        ])
        await app.bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="UZEX AI", web_app=WebAppInfo(url=MINI_APP_URL)))
        await app.bot.set_my_description(
            "UZEX bitimlari reyestri bo‘yicha o‘zbek va rus tillarida savol-javob mini-ilovasi.")
        await app.bot.set_my_short_description(
            "UZEX bitimlari bo‘yicha o‘zbekcha va ruscha AI-yordamchi.")
    except Exception:
        log.exception("Could not set Telegram command menu")

async def test_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Gemini ulanishi tekshirilmoqda… / Проверяю подключение Gemini…")
    await update.message.reply_text(await agent.diagnose())

async def _typing(bot, chat_id, stop: asyncio.Event):
    while not stop.is_set():
        try:
            await bot.send_chat_action(chat_id, ChatAction.TYPING)
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop.wait(), timeout=4)
        except asyncio.TimeoutError:
            pass

TRACES: "OrderedDict[str, dict]" = OrderedDict()     # answer id -> {sqls, question, qmsg, lang}
_plot_lock = threading.Lock()
BOT_LOOP: asyncio.AbstractEventLoop | None = None

def detect_lang(text: str) -> str:
    """Detect Russian Cyrillic, while keeping Uzbek Cyrillic as Uzbek."""
    uz_letters = set("\u045e\u049b\u0493\u04b3\u040e\u049a\u0492\u04b2")
    if any(ch in uz_letters for ch in text):
        return "uz"
    cyr = sum("\u0400" <= ch <= "\u04ff" for ch in text)
    lat = sum(ch.isascii() and ch.isalpha() for ch in text)
    return "ru" if cyr > lat else "uz"
def footer(lang: str, n_sql: int, secs: float) -> str:
    s = f"{secs:.1f}".replace(".", ",")
    if lang == "ru":
        return f"📒 Реестр UZEX · 500 000 сделок · 🛡 проверено {n_sql} запр. · ⚡ {s} с"
    return f"📒 UZEX reyestri · 500 000 bitim · 🛡 {n_sql} ta so‘rov bilan tekshirildi · ⚡ {s} s"

def keyboard(key: str, lang: str, sqls: list, chartable: bool = False):
    if not sqls:
        return None
    ru = lang == "ru"
    row = [InlineKeyboardButton("\U0001f4da Источник" if ru else "\U0001f4da Manba", callback_data=f"src:{key}"),
           InlineKeyboardButton("\U0001f4e5 Excel", callback_data=f"xls:{key}")]
    if chartable:
        row.append(InlineKeyboardButton("\U0001f4ca График" if ru else "\U0001f4ca Diagramma", callback_data=f"cht:{key}"))
    return InlineKeyboardMarkup([row])

async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return
    await answer_question(msg, ctx, msg.text)

async def on_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Answer Telegram voice notes with the same UZEX data agent."""
    msg = update.effective_message
    if not msg:
        return
    media = msg.voice or msg.audio
    if not media:
        return
    lang = preferred_language(update, ctx)
    if getattr(media, "duration", 0) > 45 or (getattr(media, "file_size", 0) or 0) > 2 * 1024 * 1024:
        notice = ("Ovozli xabar 45 soniyadan va 2 MB dan oshmasin." if lang == "uz" else
                  "Голосовое сообщение должно быть не длиннее 45 секунд и не больше 2 МБ.")
        await msg.reply_text(notice)
        return
    try:
        telegram_file = await ctx.bot.get_file(media.file_id)
        audio_data = bytes(await telegram_file.download_as_bytearray())
        if len(audio_data) > 2 * 1024 * 1024:
            notice = ("Ovozli xabar 2 MB dan katta. Qisqaroq xabar yuboring." if lang == "uz" else
                      "Голосовое сообщение больше 2 МБ. Отправьте запись короче.")
            await msg.reply_text(notice)
            return
        mime_type = getattr(media, "mime_type", None) or ("audio/ogg" if msg.voice else "audio/mpeg")
        await answer_question(msg, ctx, "", audio_data=audio_data, audio_mime_type=mime_type)
    except Exception:
        log.exception("voice message processing failed")
        notice = ("Ovozli xabarni o‘qib bo‘lmadi. Qayta yuboring yoki savolni yozing." if lang == "uz" else
                  "Не удалось обработать голосовое сообщение. Отправьте его ещё раз или напишите вопрос.")
        await msg.reply_text(notice)

async def on_web_app_data(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or not msg.web_app_data:
        return
    try:
        data = json.loads(msg.web_app_data.data)
        question = str(data.get("question", "")).strip()[:1500]
    except (json.JSONDecodeError, AttributeError, TypeError):
        question = msg.web_app_data.data.strip()[:1500]
    if not question:
        await msg.reply_text("Savolni kiriting. / Введите вопрос.")
        return
    await answer_question(msg, ctx, question)

async def answer_question(msg, ctx: ContextTypes.DEFAULT_TYPE, question: str,
                          audio_data: bytes | None = None, audio_mime_type: str = "audio/ogg"):
    chat_id = msg.chat_id
    q = question.strip()[:1500] if audio_data is None else "🎙"
    lang = detect_lang(q) if audio_data is None else preferred_language(msg, ctx)
    status_text = (("Ovozli savol tahlil qilinmoqda…" if lang == "uz" else "Анализирую голосовой вопрос…")
                   if audio_data is not None else
                   ("Savolingiz tekshirilmoqda…" if lang == "uz" else "Проверяю ваш вопрос…"))
    status = await msg.reply_text(status_text)
    lock = LOCKS.setdefault(chat_id, asyncio.Lock())
    async with lock:                       # one question at a time per chat, many chats in parallel
        t0 = time.time()
        stop = asyncio.Event()
        t = asyncio.create_task(_typing(ctx.bot, chat_id, stop))
        sqls = []
        try:
            text, HISTORY[chat_id], sqls = await asyncio.wait_for(
                agent.answer(q, HISTORY.get(chat_id, []), audio_data=audio_data,
                             audio_mime_type=audio_mime_type), timeout=65)
        except asyncio.TimeoutError:
            text = agent.ERR_MSG
        finally:
            stop.set(); await t
        secs = time.time() - t0
    if audio_data is not None and text != agent.ERR_MSG:
        lang = detect_lang(text)
    ctx.user_data["lang"] = lang
    if text == agent.ERR_MSG:
        text = ("Kechirasiz, texnik xatolik yuz berdi. Birozdan keyin qayta urinib ko‘ring." if lang == "uz" else
                "Извините, произошла техническая ошибка. Попробуйте ещё раз чуть позже.")
    kb = None
    if sqls:
        key = f"{chat_id}_{msg.message_id}"
        TRACES[key] = {"sqls": sqls, "question": q, "qmsg": msg.message_id, "lang": lang, "answer": text}
        while len(TRACES) > 300:
            TRACES.popitem(last=False)
        text = f"{text}\n\n{footer(lang, len(sqls), secs)}"
        kb = keyboard(key, lang, sqls, chartable=extras.can_chart(sqls))
    chunks = [text[i:i + 4000] for i in range(0, len(text), 4000)]
    for i, ch in enumerate(chunks):
        if i == 0:
            await status.edit_text(ch, reply_markup=kb if i == len(chunks) - 1 else None)
        else:
            await msg.reply_text(ch, reply_markup=kb if i == len(chunks) - 1 else None)

BUSY: set = set()      # buttons being processed right now (ignore double taps)

def _reply_to(msg_id):
    """Reply to the user's question, and do NOT fail if that message was deleted."""
    return ReplyParameters(message_id=msg_id, allow_sending_without_reply=True)

async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cq = update.callback_query
    kind, _, key = (cq.data or "").partition(":")
    if kind == "sample":
        await cq.answer()
        question = EXAMPLE_QUESTIONS[0] if key == "uz" else EXAMPLE_QUESTIONS[4]
        ctx.user_data["lang"] = key
        prompt = await ctx.bot.send_message(cq.message.chat_id, question)
        await answer_question(prompt, ctx, question)
        return
    entry = TRACES.get(key)
    chat_id = cq.message.chat_id if cq.message else cq.from_user.id
    lang = entry["lang"] if entry else "uz"
    ru = lang == "ru"

    toast = {"src": "📚", "xls": "⏳ Готовлю Excel…" if ru else "⏳ Excel tayyorlanmoqda…",
             "cht": "⏳ Рисую график…" if ru else "⏳ Diagramma chizilmoqda…"}.get(kind, "")
    try:
        await cq.answer(toast)                      # small popup, so the user sees that the tap worked
    except Exception:
        pass

    if not entry:
        await ctx.bot.send_message(chat_id, "Bu javob eskirgan, savolni qayta bering. / Ответ устарел, задайте вопрос заново.")
        return
    busy_key = f"{kind}:{key}"
    if busy_key in BUSY:                            # already working on this exact button
        return
    BUSY.add(busy_key)
    sqls, qmsg = entry["sqls"], entry["qmsg"]
    try:
        if kind == "src":
            await ctx.bot.send_message(chat_id, extras.source_text(sqls, lang), reply_parameters=_reply_to(qmsg))

        elif kind == "xls":
            await ctx.bot.send_chat_action(chat_id, ChatAction.UPLOAD_DOCUMENT)
            buf = await asyncio.wait_for(asyncio.to_thread(
                extras.build_excel, sqls, entry["question"], entry.get("answer", ""), lang), timeout=60)
            if not buf:
                no_data = "Excel yaratish uchun ma’lumot topilmadi." if not ru else "Нет данных для создания Excel-файла."
                await ctx.bot.send_message(chat_id, no_data,
                                           reply_parameters=_reply_to(qmsg))
                return
            cap = ("📥 Excel: «Сводка» — вопрос, ответ и обзор; «Результат 1…» — таблицы; «SQL» — запросы." if ru else
                   "📥 Excel: «Hisobot» — savol, javob va xulosa; «Natija 1…» — jadvallar; «SQL» — so‘rovlar.")
            await ctx.bot.send_document(chat_id, buf, filename=f"uzex_{key.split('_')[-1]}.xlsx",
                                        caption=cap, reply_parameters=_reply_to(qmsg))

        elif kind == "cht":
            await ctx.bot.send_chat_action(chat_id, ChatAction.UPLOAD_PHOTO)
            def make():
                with _plot_lock:
                    return extras.build_chart(sqls, entry["question"], lang)
            buf = await asyncio.wait_for(asyncio.to_thread(make), timeout=60)
            if not buf:
                await ctx.bot.send_message(
                    chat_id,
                    "Для диаграммы нужны как минимум две строки и числовой столбец. В этом ответе таких данных нет." if ru else
                    "Diagramma tuzish uchun kamida ikki qator va sonli ustun kerak. Bu javobda bunday ma’lumot yo‘q.",
                    reply_parameters=_reply_to(qmsg))
                return
            cap = "🖼 График по тем же данным, что и в ответе" if ru else "🖼 Javob bilan bir xil ma’lumotlar bo‘yicha diagramma"
            await ctx.bot.send_photo(chat_id, buf, caption=cap, reply_parameters=_reply_to(qmsg))
    except Exception:
        log.exception("button %s failed", kind)
        try:
            failure = (("Excel faylini yaratishda xatolik yuz berdi. Qayta urinib ko‘ring." if not ru else
                        "Не удалось создать файл Excel. Попробуйте ещё раз.") if kind == "xls" else
                       ("Diagramma yaratishda xatolik yuz berdi. Qayta urinib ko‘ring." if not ru else
                        "Не удалось создать диаграмму. Попробуйте ещё раз."))
            await ctx.bot.send_message(chat_id, failure)
        except Exception:
            pass
    finally:
        BUSY.discard(busy_key)

async def on_error(update, ctx: ContextTypes.DEFAULT_TYPE):
    log.error("Unhandled error", exc_info=ctx.error)

async def on_other(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    source = update.message.caption or ""
    lang = detect_lang(source)
    prompt = "Savolingizni matn ko‘rinishida yuboring." if lang == "uz" else "Пожалуйста, отправьте вопрос текстом."
    await update.message.reply_text(prompt)

def validate_webapp_init_data(raw: str) -> int | None:
    """Validate Telegram-signed Mini App data; never trust initDataUnsafe from the browser."""
    try:
        fields = dict(parse_qsl(raw, keep_blank_values=True, strict_parsing=True))
        received_hash = fields.pop("hash")
        auth_date = int(fields["auth_date"])
        now = int(time.time())
        if auth_date > now + 60 or now - auth_date > 24 * 60 * 60:
            return None
        data_check = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
        secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
        expected = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, received_hash):
            return None
        return int(json.loads(fields["user"])["id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None

async def answer_webapp_question(user_id: int, question: str, audio_data: bytes | None = None,
                                 audio_mime_type: str = "audio/webm"):
    lang = detect_lang(question) if question else "uz"
    lock = LOCKS.setdefault(user_id, asyncio.Lock())
    started = time.monotonic()
    async with lock:
        try:
            answer, history, sqls = await asyncio.wait_for(
                agent.answer(question, HISTORY.get(user_id, []), audio_data=audio_data,
                             audio_mime_type=audio_mime_type), timeout=65)
            HISTORY[user_id] = history
        except asyncio.TimeoutError:
            answer, sqls = agent.ERR_MSG, []
    if audio_data is not None and answer != agent.ERR_MSG:
        lang = detect_lang(answer)
    if answer == agent.ERR_MSG:
        answer = ("Kechirasiz, texnik xatolik yuz berdi. Birozdan keyin qayta urinib ko‘ring." if lang == "uz" else
                  "Извините, произошла техническая ошибка. Попробуйте ещё раз чуть позже.")
    elapsed = time.monotonic() - started
    if sqls:
        answer = f"{answer}\n\n{footer(lang, len(sqls), elapsed)}"
    return {"answer": answer, "elapsed": elapsed}

# ---- Telegram Mini App + health check
class Page(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/health", "/healthz"):
            body = (b"UZEX AI is running. Open the Telegram Mini App at /app." if path != "/" else
                    b"<!doctype html><meta charset=utf-8><meta http-equiv=refresh content='0;url=/app'><a href='/app'>Open UZEX AI</a>")
            self._send(body, "text/plain; charset=utf-8" if path != "/" else "text/html; charset=utf-8")
            return
        files = {
            "/app": (WEB_DIR / "index.html", "text/html; charset=utf-8"),
            "/app/": (WEB_DIR / "index.html", "text/html; charset=utf-8"),
            "/app.css": (WEB_DIR / "app.css", "text/css; charset=utf-8"),
            "/app.js": (WEB_DIR / "app.js", "application/javascript; charset=utf-8"),
            "/hero.svg": (WEB_DIR / "hero.svg", "image/svg+xml"),
            "/assistant.css": (WEB_DIR / "assistant.css", "text/css; charset=utf-8"),
            "/assistant.gif": (WELCOME_ANIMATION, "image/gif"),
            "/welcome.png": (WELCOME_IMAGE, "image/png"),
        }
        item = files.get(path)
        if not item or not item[0].is_file():
            self.send_error(404)
            return
        self._send(item[0].read_bytes(), item[1])

    def do_POST(self):
        if urlparse(self.path).path != "/api/ask":
            self.send_error(404)
            return
        if BOT_LOOP is None:
            self._json(503, {"error": "Ilova ishga tushmoqda. Birozdan keyin qayta urinib ko‘ring."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 1 <= length <= 3 * 1024 * 1024:
                self._json(413, {"error": "So‘rov hajmi ruxsat etilganidan katta."})
                return
            payload = json.loads(self.rfile.read(length))
            question = str(payload.get("question", "")).strip()[:1500]
            user_id = validate_webapp_init_data(str(payload.get("initData", "")))
            if user_id is None:
                self._json(401, {"error": "Telegram seansi tasdiqlanmadi. Ilovani bot ichidan qayta oching."})
                return
            audio_data = None
            audio_mime_type = "audio/webm"
            encoded_audio = payload.get("audio")
            if encoded_audio:
                if not isinstance(encoded_audio, str) or len(encoded_audio) > 2_796_204:
                    self._json(413, {"error": "Ovozli savol 2 MB dan oshmasin."})
                    return
                try:
                    audio_data = base64.b64decode(encoded_audio, validate=True)
                except (ValueError, base64.binascii.Error):
                    self._json(400, {"error": "Ovozli so‘rov formati noto‘g‘ri."})
                    return
                if not audio_data or len(audio_data) > 2 * 1024 * 1024:
                    self._json(413, {"error": "Ovozli savol 2 MB dan oshmasin."})
                    return
                requested_mime = str(payload.get("audioMimeType", "audio/webm")).split(";", 1)[0].lower()
                audio_mime_type = {"audio/mp4": "audio/m4a"}.get(requested_mime, requested_mime)
                if audio_mime_type not in {"audio/webm", "audio/ogg", "audio/m4a", "audio/mpeg", "audio/wav"}:
                    self._json(400, {"error": "Ovozli fayl turi qo‘llab-quvvatlanmaydi."})
                    return
            if not question and audio_data is None:
                self._json(400, {"error": "Savol matnini kiriting."})
                return
            future = asyncio.run_coroutine_threadsafe(
                answer_webapp_question(user_id, question, audio_data, audio_mime_type), BOT_LOOP)
            result = future.result(timeout=70)
            self._json(200, result)
        except FutureTimeoutError:
            self._json(504, {"error": "Javob olish cho‘zildi. Iltimos, yana urinib ko‘ring."})
        except (ValueError, AttributeError, json.JSONDecodeError):
            self._json(400, {"error": "So‘rov formati noto‘g‘ri."})
        except Exception:
            log.exception("Mini App request failed")
            self._json(500, {"error": "Texnik xatolik. Birozdan keyin qayta urinib ko‘ring."})

    def _json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _send(self, body, content_type):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):
        self.send_response(200 if urlparse(self.path).path in ("/", "/health", "/healthz", "/app", "/app/") else 404)
        self.end_headers()
    def log_message(self, *a): pass

def run_web():
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8080"))), Page).serve_forever()

async def warm(app):
    """Register the bot UI without making a burst of paid model calls at every restart."""
    global BOT_LOOP
    BOT_LOOP = asyncio.get_running_loop()
    await set_commands(app)
    log.info("bot UI ready; Gemini model calls are made only when a user asks a question")

def main():
    threading.Thread(target=run_web, daemon=True).start()
    app = Application.builder().token(TOKEN).concurrent_updates(True).post_init(warm).build()
    app.add_handler(CommandHandler(["start", "help"], start))
    app.add_handler(CommandHandler("examples", examples_cmd))
    app.add_handler(CommandHandler("clear", clear_cmd))
    app.add_handler(CommandHandler("hide", hide_cmd))
    app.add_handler(CommandHandler("test", test_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(~filters.TEXT & ~filters.COMMAND, on_other))
    app.add_error_handler(on_error)
    log.info("bot started")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
