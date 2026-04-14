import random
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import *

from db import get_user, create_user, update
from ai import chat
from payments import premium_invoice

NAMES=["Анна","Мария","Ольга"]
CHAR=["нежная","игривая","загадочная"]
CITIES=["Москва","СПБ"]

def character():
    return {"name":random.choice(NAMES),"char":random.choice(CHAR),"city":random.choice(CITIES)}

def menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Чат",callback_data="chat")],
        [InlineKeyboardButton("🔥 18+",callback_data="chat18")],
        [InlineKeyboardButton("💎 Премиум",callback_data="premium")],
        [InlineKeyboardButton("👤 Профиль",callback_data="profile")]
    ])

def setup(app):

    async def start(update:Update,context):
        uid=str(update.effective_user.id)
        create_user(uid, update.effective_user.first_name)
        await update.message.reply_text("Привет 👋", reply_markup=menu())

    async def cb(update:Update,context):
        q=update.callback_query
        await q.answer()
        uid=str(update.effective_user.id)
        user=get_user(uid)

        if q.data=="chat":
            context.user_data["char"]=character()
            context.user_data["msgs"]=[]
            await q.edit_message_text("💬 чат")

        elif q.data=="chat18":
            if user[4]<=0:
                await q.edit_message_text("лимит 18+ закончился 😔")
                return
            update(uid,"free_18",user[4]-1)
            context.user_data["char"]=character()
            context.user_data["msgs"]=[]
            await q.edit_message_text("🔥 18+ режим")

        elif q.data=="premium":
            await premium_invoice(context, q.message.chat.id)

        elif q.data=="profile":
            await q.edit_message_text(f"{user[1]}\n18+: {user[4]}\n💎 premium: {user[5]}")

    async def msg(update:Update,context):
        if "char" not in context.user_data:
            return

        msgs=context.user_data["msgs"]
        msgs.append({"role":"user","content":update.message.text})

        char=context.user_data["char"]
        system={"role":"system","content":f"Ты {char['name']} {char['char']} из {char['city']}"}

        reply=await asyncio.to_thread(chat,[system]+msgs)
        msgs.append({"role":"assistant","content":reply})

        await update.message.reply_text(reply)

    app.add_handler(CommandHandler("start",start))
    app.add_handler(CallbackQueryHandler(cb))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,msg))
