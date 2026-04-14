import os
import random
import sqlite3
import asyncio
import requests
from datetime import datetime, timedelta

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
)

from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    PreCheckoutQueryHandler,
    filters,
)

# ========== CONFIG ==========
TOKEN = os.getenv("TELEGRAM_TOKEN")
MOONSHOT_API_KEY = os.getenv("MOONSHOT_API_KEY")  # ⚠️ через ENV
MOONSHOT_API_URL = "https://api.moonshot.ai/v1/chat/completions"

if not TOKEN:
    raise ValueError("NO TELEGRAM TOKEN")

# ========== DB ==========
conn = sqlite3.connect("bot.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS users (
telegram_id TEXT PRIMARY KEY,
name TEXT,
gender TEXT,
age INTEGER,
preference TEXT,
free_18 INTEGER DEFAULT 4,
premium_until TEXT,
referrals INTEGER DEFAULT 0
)
""")
conn.commit()

# ========== FSM ==========
(NAME, GENDER, AGE, LOOKING, PREF, CONFIRM) = range(6)

# ========== DATA ==========
NAMES = ["Анна", "Мария", "Ольга", "Дарья", "София", "Алиса"]
CHAR = ["весёлая", "игривая", "нежная", "загадочная"]
CITIES = ["Москва", "СПБ", "Казань", "Сочи"]
ETH = ["русская", "украинка", "казашка", "грузинка"]

# ========== AI ==========
def ai(messages):
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
    except:
        return "..."

# ========== DB HELPERS ==========
def get_user(tg_id):
    cur.execute("SELECT * FROM users WHERE telegram_id=?", (tg_id,))
    return cur.fetchone()

def create_user(tg_id, name):
    cur.execute("INSERT OR IGNORE INTO users (telegram_id, name) VALUES (?,?)", (tg_id, name))
    conn.commit()

def update(tg_id, field, value):
    cur.execute(f"UPDATE users SET {field}=? WHERE telegram_id=?", (value, tg_id))
    conn.commit()

# ========== CHARACTER ==========
def character():
    return {
        "name": random.choice(NAMES),
        "char": random.choice(CHAR),
        "city": random.choice(CITIES),
        "eth": random.choice(ETH),
    }

# ========== KEYBOARDS ==========
def menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Обычный чат", callback_data="chat")],
        [InlineKeyboardButton("🔥 18+ чат", callback_data="chat18")],
        [InlineKeyboardButton("👤 Профиль", callback_data="profile")],
        [InlineKeyboardButton("🎁 Реферал", callback_data="ref")],
        [InlineKeyboardButton("💎 Премиум", callback_data="premium")]
    ])

def reconnect():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💫 Вернуться — 49⭐", callback_data="reconnect")]
    ])

# ========== START FLOW ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = str(update.effective_user.id)
    create_user(tg_id, update.effective_user.first_name)

    await update.message.reply_text("Как тебя зовут?")
    return NAME

async def name(update, context):
    context.user_data["name"] = update.message.text
    await update.message.reply_text("Пол?")
    return GENDER

async def gender(update, context):
    context.user_data["gender"] = update.message.text
    await update.message.reply_text("Возраст?")
    return AGE

async def age(update, context):
    context.user_data["age"] = int(update.message.text)
    await update.message.reply_text("Кого ищешь?")
    return LOOKING

async def looking(update, context):
    context.user_data["looking"] = update.message.text
    await update.message.reply_text("Предпочтение? (обычное / 18+)")
    return PREF

async def pref(update, context):
    context.user_data["pref"] = update.message.text
    await update.message.reply_text("Подтверди: Мне есть 18")
    return CONFIRM

async def confirm(update, context):
    tg_id = str(update.effective_user.id)

    update(tg_id, "age", context.user_data["age"])
    update(tg_id, "gender", context.user_data["gender"])
    update(tg_id, "preference", context.user_data["pref"])
    update(tg_id, "free_18", 4)

    await update.message.reply_text("Готово 👇", reply_markup=menu())
    return ConversationHandler.END

# ========== CALLBACK ==========
async def cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    tg_id = str(update.effective_user.id)
    user = get_user(tg_id)

    if q.data == "chat":
        context.user_data["char"] = character()
        context.user_data["msgs"] = []
        await q.edit_message_text("💬 Обычный чат")

    elif q.data == "chat18":
        if user[5] <= 0:
            await q.edit_message_text(
                "Похоже… нас разъединило 😔",
                reply_markup=reconnect()
            )
            return

        update(tg_id, "free_18", user[5] - 1)

        context.user_data["char"] = character()
        context.user_data["msgs"] = []

        await q.edit_message_text("🔥 18+ режим")

    elif q.data == "reconnect":
        update(tg_id, "free_18", user[5] + 1)
        await q.edit_message_text("Ты снова со мной 😌", reply_markup=menu())

    elif q.data == "profile":
        await q.edit_message_text(
            f"👤 {user[1]}\n🔥 18+: {user[5]}\n💎 премиум: {user[6]}",
            reply_markup=menu()
        )

    elif q.data == "premium":
        await send_invoice(update, context)

# ========== STARS PAYMENT ==========
async def send_invoice(update, context):
    await context.bot.send_invoice(
        chat_id=update.effective_chat.id,
        title="Премиум 7 дней",
        description="Безлимитный 18+ чат",
        payload="premium_7",
        provider_token="",  # ⭐ Stars = пусто
        currency="XTR",
        prices=[LabeledPrice("Premium", 180)],
    )

async def precheckout(update, context):
    await update.pre_checkout_query.answer(ok=True)

async def success(update, context):
    tg_id = str(update.effective_user.id)
    premium_until = (datetime.now() + timedelta(days=7)).isoformat()
    update(tg_id, "premium_until", premium_until)

    await update.message.reply_text("💎 Премиум активирован!")

# ========== CHAT ==========
async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "char" not in context.user_data:
        return

    msgs = context.user_data["msgs"]

    msgs.append({"role": "user", "content": update.message.text})

    char = context.user_data["char"]

    system = {
        "role": "system",
        "content": f"""
Ты девушка.
Имя: {char['name']}
Характер: {char['char']}
Город: {char['city']}

Правила:
- не говори что ты ИИ
- не давай контакты
- не встречайся
- лёгкий флирт
"""
    }

    reply = await asyncio.to_thread(ai, [system] + msgs)

    msgs.append({"role": "assistant", "content": reply})

    await update.message.reply_text(reply)

# ========== APP ==========
def main():
    app = Application.builder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NAME: [MessageHandler(filters.TEXT, name)],
            GENDER: [MessageHandler(filters.TEXT, gender)],
            AGE: [MessageHandler(filters.TEXT, age)],
            LOOKING: [MessageHandler(filters.TEXT, looking)],
            PREF: [MessageHandler(filters.TEXT, pref)],
            CONFIRM: [MessageHandler(filters.TEXT, confirm)],
        },
        fallbacks=[]
    )

    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(cb))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, success))

    print("BOT RUNNING")
    app.run_polling()

if __name__ == "__main__":
    main()
