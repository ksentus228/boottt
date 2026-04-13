import os
import json
import random
import asyncio
import logging
import requests
import uvicorn
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse, Response
from starlette.requests import Request
from starlette.routing import Route

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters,
    MessageHandler, PreCheckoutQueryHandler
)
from telegram.constants import ParseMode

# ========== ENV ==========
TOKEN = os.environ.get("TELEGRAM_TOKEN")
MOONSHOT_API_KEY = "sk-2VbR6yBej6324pC3TbnkXoIjOECuyvwN9qdv13ZTGbxHoRQB"
MOONSHOT_API_URL = "https://api.moonshot.ai/v1/chat/completions"
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL")
PORT = int(os.getenv("PORT", 10000))

if not TOKEN:
    raise ValueError("❌ TELEGRAM_TOKEN missing")

MAX_HISTORY = 10

PRICES = {
    "reconnect_18": 49,
    "premium_1day": 49,
    "premium_7days": 180,
    "premium_30days": 300
}

# ========== DATA ==========
NAMES_GIRLS = ["Анна", "Мария", "Екатерина", "Ольга", "Дарья", "Алиса", "София", "Виктория"]
NAMES_BOYS = ["Александр", "Дмитрий", "Максим", "Артем", "Иван", "Михаил"]

CHARACTERS = [
    "весёлая", "романтичная", "дерзкая",
    "нежная", "игривая", "загадочная"
]

ETHNICITY = ["русская", "украинка", "казашка", "грузинка"]
CITIES = ["Москва", "СПБ", "Казань", "Сочи"]

ASK_NAME, ASK_GENDER, ASK_AGE, ASK_LOOKING_FOR, ASK_PREFERENCE, ASK_CONFIRM = range(6)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== DB ==========
class Database:
    def __init__(self):
        self.users = {}

    def get_user(self, uid):
        return self.users.get(uid)

    def create_user(self, uid, data):
        self.users[uid] = data

    def update_user(self, uid, data):
        if uid in self.users:
            self.users[uid].update(data)

db = Database()

# ========== CHARACTER ==========
class Character:
    def __init__(self, looking_for="girls"):
        self.gender = "girl" if looking_for == "girls" else "boy"
        self.name = random.choice(NAMES_GIRLS if self.gender == "girl" else NAMES_BOYS)
        self.character = random.choice(CHARACTERS)
        self.city = random.choice(CITIES)

    def greet(self, user):
        return f"Привет, {user}... Я {self.name} 😌"

# ========== AI ==========
class AI:
    def get(self, messages, character):
        try:
            r = requests.post(
                MOONSHOT_API_URL,
                headers={"Authorization": f"Bearer {MOONSHOT_API_KEY}"},
                json={
                    "model": "moonshot-v1-8k",
                    "messages": messages[-8:],
                    "temperature": 0.9,
                    "max_tokens": 120
                },
                timeout=10
            )
            return r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(e)
            return "..."

ai = AI()

# ========== KEYBOARDS ==========
def main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Обычный чат", callback_data="chat")],
        [InlineKeyboardButton("🔥 18+", callback_data="chat18")],
        [InlineKeyboardButton("👤 Профиль", callback_data="profile")],
        [InlineKeyboardButton("🎁 Реферал", callback_data="ref")],
        [InlineKeyboardButton("💎 Премиум", callback_data="premium")]
    ])

def reconnect_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💫 Вернуться — 49⭐", callback_data="reconnect")]
    ])

# ========== ONBOARD ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Как тебя зовут?")
    return ASK_NAME

async def ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text
    db.create_user(str(update.effective_user.id), {"name": update.message.text, "free": 4})
    await update.message.reply_text("Готово 👇", reply_markup=main_kb())
    return ConversationHandler.END

# ========== CALLBACK ==========
async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    uid = str(update.effective_user.id)
    user = db.get_user(uid)

    if q.data == "chat":
        char = Character()
        context.user_data["char"] = char
        context.user_data["msgs"] = []
        await q.edit_message_text(char.greet(user["name"]))

    elif q.data == "chat18":
        if user["free"] <= 0:
            await q.edit_message_text(
                "Похоже… нас разъединило 😔",
                reply_markup=reconnect_kb()
            )
            return

        user["free"] -= 1
        db.update_user(uid, {"free": user["free"]})

        char = Character()
        context.user_data["char"] = char
        context.user_data["msgs"] = []
        context.user_data["mode"] = "18"

        await q.edit_message_text(f"{char.name}: Ммм... я ждала тебя 😏")

    elif q.data == "reconnect":
        user["free"] += 1
        db.update_user(uid, {"free": user["free"]})
        await q.edit_message_text("Ты снова со мной 😌", reply_markup=main_kb())

    elif q.data == "profile":
        await q.edit_message_text(f"Имя: {user['name']}\n18+: {user['free']}")

# ========== CHAT ==========
async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "char" not in context.user_data:
        return

    text = update.message.text
    msgs = context.user_data["msgs"]

    msgs.append({"role": "user", "content": text})

    await update.message.chat.send_action("typing")

    reply = await asyncio.to_thread(ai.get, msgs, context.user_data["char"])

    msgs.append({"role": "assistant", "content": reply})

    await update.message.reply_text(reply)

# ========== PAY ==========
async def pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)

async def success(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Оплата прошла ✅")

# ========== APP ==========
async def main():
    app = Application.builder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={ASK_NAME: [MessageHandler(filters.TEXT, ask_name)]},
        fallbacks=[]
    )

    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))
    app.add_handler(PreCheckoutQueryHandler(pre_checkout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, success))

    if RENDER_EXTERNAL_URL:
        await app.bot.set_webhook(f"{RENDER_EXTERNAL_URL}/webhook")

        async def webhook(request: Request):
            update = Update.de_json(await request.json(), app.bot)
            await app.update_queue.put(update)
            return Response()

        starlette = Starlette(routes=[
            Route("/webhook", webhook, methods=["POST"]),
            Route("/health", lambda r: PlainTextResponse("OK"))
        ])

        server = uvicorn.Server(
            uvicorn.Config(starlette, host="0.0.0.0", port=PORT)
        )

        async with app:
            await app.start()
            await server.serve()
            await app.stop()
    else:
        await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
