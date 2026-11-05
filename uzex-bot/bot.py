"""UZEX AI Hackathon - Telegram bot (Uzbek + Russian) answering questions about the exchange deal registry.

Env: TELEGRAM_TOKEN, GEMINI_API_KEY, optional GEMINI_MODEL, BOT_USERNAME, PORT
Run: python bot.py
"""
import os, asyncio, threading, logging
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

import agent

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

async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return
    chat_id = update.effective_chat.id
    q = msg.text.strip()[:1500]
    lock = LOCKS.setdefault(chat_id, asyncio.Lock())
    async with lock:                       # one question at a time per chat, many chats in parallel
        stop = asyncio.Event()
        t = asyncio.create_task(_typing(ctx.bot, chat_id, stop))
        try:
            text, HISTORY[chat_id] = await asyncio.wait_for(
                agent.answer(q, HISTORY.get(chat_id, [])), timeout=110)
        except asyncio.TimeoutError:
            text = agent.ERR_MSG
        finally:
            stop.set(); await t
    for i in range(0, len(text), 4000):
        await msg.reply_text(text[i:i + 4000])

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
    def log_message(self, *a): pass

def run_web():
    HTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8080"))), Page).serve_forever()

def main():
    threading.Thread(target=run_web, daemon=True).start()
    app = Application.builder().token(TOKEN).concurrent_updates(True).build()
    app.add_handler(CommandHandler(["start", "help"], start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(MessageHandler(~filters.TEXT & ~filters.COMMAND, on_other))
    log.info("bot started")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
