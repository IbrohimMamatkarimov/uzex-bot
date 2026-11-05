"""UZEX AI Hackathon - Telegram bot (Uzbek + Russian) answering questions about the exchange deal registry.

Env: TELEGRAM_TOKEN, GEMINI_API_KEY, optional GEMINI_MODEL, BOT_USERNAME, PORT
Run: python bot.py
"""
import os, re, time, asyncio, threading, logging
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyParameters
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

import agent, extras

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("bot")

TOKEN = os.environ["TELEGRAM_TOKEN"]
BOT_USERNAME = os.environ.get("BOT_USERNAME", "")

WELCOME = (
    "Assalomu alaykum! Men UZEX birja bitimlari reyestri bo‘yicha AI-yordamchiman (2022–2026, 500 000 bitim). "
    "Savolingizni o‘zbek yoki rus tilida yozing.\n\n"
    "Masalan:\n"
    "• 2025-yilda eng ko‘p savdo qilingan 5 ta tovar qaysi?\n"
    "• Paxta-xom o‘rtacha narxi 2024 va 2025-yillarda qanday o‘zgargan?\n"
    "• Qaysi brokerda eng ko‘p bitim bor?\n\n"
    "Здравствуйте! Я AI-помощник по реестру сделок биржи UZEX (2022–2026, 500 000 сделок). "
    "Задайте вопрос на узбекском или русском языке.\n\n"
    "Например:\n"
    "• Какой регион лидирует по объёму торгов цементом?\n"
    "• Сколько сделок было аннулировано в 2025 году?\n"
    "• Какая средняя цена пшеницы за тонну в 2026 году?"
)

HISTORY: dict[int, list] = {}
LOCKS: dict[int, asyncio.Lock] = {}

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    HISTORY.pop(update.effective_chat.id, None)
    await update.message.reply_text(WELCOME)

async def test_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Testing Gemini...")
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

def keyboard(key: str, lang: str, sqls: list):
    if not sqls:
        return None
    ru = lang == "ru"
    # chart button is always shown: checking it here re-ran every SQL query and froze the bot for seconds
    row = [InlineKeyboardButton("\U0001f4da Источник" if ru else "\U0001f4da Manba", callback_data=f"src:{key}"),
           InlineKeyboardButton("\U0001f4e5 Excel", callback_data=f"xls:{key}"),
           InlineKeyboardButton("\U0001f4ca График" if ru else "\U0001f4ca Diagramma", callback_data=f"cht:{key}")]
    return InlineKeyboardMarkup([row])

async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return
    chat_id = update.effective_chat.id
    q = msg.text.strip()[:1500]
    status = await msg.reply_text("Checking your question…")
    lock = LOCKS.setdefault(chat_id, asyncio.Lock())
    async with lock:                       # one question at a time per chat, many chats in parallel
        t0 = time.time()
        stop = asyncio.Event()
        t = asyncio.create_task(_typing(ctx.bot, chat_id, stop))
        sqls = []
        try:
            text, HISTORY[chat_id], sqls = await asyncio.wait_for(
                agent.answer(q, HISTORY.get(chat_id, [])), timeout=45)
        except asyncio.TimeoutError:
            text = agent.ERR_MSG
        finally:
            stop.set(); await t
        secs = time.time() - t0
    lang = detect_lang(q)
    kb = None
    if sqls:
        key = f"{chat_id}_{msg.message_id}"
        TRACES[key] = {"sqls": sqls, "question": q, "qmsg": msg.message_id, "lang": lang, "answer": text}
        while len(TRACES) > 300:
            TRACES.popitem(last=False)
        text = f"{text}\n\n{footer(lang, len(sqls), secs)}"
        kb = keyboard(key, lang, sqls)
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
                await ctx.bot.send_message(chat_id, "Excel uchun ma’lumot topilmadi. / Нет данных для Excel.",
                                           reply_parameters=_reply_to(qmsg))
                return
            cap = ("⬇️ Excel: лист «Ответ» — вопрос и ответ, «Результат 1…» — данные, «SQL» — точные запросы" if ru else
                   "⬇️ Excel: «Javob» varag‘i — savol va javob, «Natija 1…» — ma’lumotlar, «SQL» — aniq so‘rovlar")
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
                    "Для этого ответа график не нужен: результат — одно число или не таблица." if ru else
                    "Bu javob uchun diagramma kerak emas: natija bitta raqam yoki jadval emas.",
                    reply_parameters=_reply_to(qmsg))
                return
            cap = "🖼 График по тем же данным, что и в ответе" if ru else "🖼 Javob bilan bir xil ma’lumotlar bo‘yicha diagramma"
            await ctx.bot.send_photo(chat_id, buf, caption=cap, reply_parameters=_reply_to(qmsg))
    except Exception:
        log.exception("button %s failed", kind)
        try:
            await ctx.bot.send_message(chat_id, agent.ERR_MSG)
        except Exception:
            pass
    finally:
        BUSY.discard(busy_key)

async def on_error(update, ctx: ContextTypes.DEFAULT_TYPE):
    log.error("Unhandled error", exc_info=ctx.error)

async def on_other(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Iltimos, savolni matn ko‘rinishida yozing. / Пожалуйста, напишите вопрос текстом.")

# ---- tiny web page + health check (Render/Railway need an open port; judges can open it too)
class Page(BaseHTTPRequestHandler):
    def do_GET(self):
        link = f"https://t.me/{BOT_USERNAME}" if BOT_USERNAME else "#"
        html = (f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
                f"<title>UZEX AI Bot</title><body style='font-family:system-ui;max-width:560px;margin:12vh auto;padding:0 16px'>"
                f"<h2>UZEX AI Hackathon — Telegram bot</h2><p>Birja bitimlari reyestri bo‘yicha savollarga o‘zbek va rus tillarida javob beradi.<br>"
                f"Отвечает на вопросы по реестру сделок биржи на узбекском и русском языках.</p>"
                f"<p><a href='{link}' style='font-size:1.2em'>Open in Telegram → @{BOT_USERNAME}</a></p></body>").encode()
        self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers()
        self.wfile.write(html)
    def do_HEAD(self):
        self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers()
    def log_message(self, *a): pass

def run_web():
    HTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8080"))), Page).serve_forever()

async def warm(app):
    """At startup: open the Gemini connection and pick a working model, so the first user is not slow."""
    try:
        log.info("warmup:\n%s", await agent.diagnose())
    except Exception:
        log.exception("warmup failed")

def main():
    threading.Thread(target=run_web, daemon=True).start()
    app = Application.builder().token(TOKEN).concurrent_updates(True).post_init(warm).build()
    app.add_handler(CommandHandler(["start", "help"], start))
    app.add_handler(CommandHandler("test", test_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(~filters.TEXT & ~filters.COMMAND, on_other))
    app.add_error_handler(on_error)
    log.info("bot started")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
