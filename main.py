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
    ConversationHandler, ContextTypes, filters
)
from telegram.constants import ParseMode

# ========== ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ ==========
TOKEN = os.environ.get("TELEGRAM_TOKEN")
# ТВОЙ API КЛЮЧ ОТ KIMI - ВСТАВЛЕН!
MOONSHOT_API_KEY = "sk-2VbR6yBej6324pC3TbnkXoIjOECuyvwN9qdv13ZTGbxHoRQB"
MOONSHOT_API_URL = "https://api.moonshot.ai/v1/chat/completions"
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL")
PORT = int(os.getenv("PORT", 10000))

if not TOKEN:
    raise ValueError("❌ Ошибка: TELEGRAM_TOKEN не найден в переменных окружения!")
if not RENDER_EXTERNAL_URL:
    print("⚠️ ВНИМАНИЕ: RENDER_EXTERNAL_URL не найден")

# Настройки
MAX_HISTORY = 10
USE_AI = True

# Цены
PRICES = {
    "reconnect_18": 49,
    "premium_1day": 49,
    "premium_7days": 180,
    "premium_30days": 300
}

# ========== ДАННЫЕ ДЛЯ ПЕРСОНАЖЕЙ ==========
NAMES_GIRLS = ["Анна", "Мария", "Екатерина", "Ольга", "Дарья", "Алиса", "София", "Виктория", "Полина", "Анастасия", "Ксения", "Елизавета"]
NAMES_BOYS = ["Александр", "Дмитрий", "Максим", "Артем", "Иван", "Михаил", "Егор", "Никита", "Андрей", "Сергей", "Алексей", "Владимир"]

CHARACTERS = [
    "весёлая и жизнерадостная", "задумчивая и романтичная", "дерзкая и уверенная",
    "нежная и заботливая", "энергичная и активная", "интеллектуальная и начитанная",
    "загадочная и таинственная", "добрая и отзывчивая", "страстная и эмоциональная",
    "игривая и кокетливая", "спокойная и умиротворённая", "остроумная и саркастичная"
]

ETHNICITY = ["русская", "украинка", "беларуска", "казашка", "грузинка", "армянка", "татарка", "узбечка"]
CITIES = ["Москва", "Санкт-Петербург", "Казань", "Новосибирск", "Екатеринбург", "Нижний Новгород", "Сочи", "Краснодар", "Ростов-на-Дону", "Самара"]

# ========== СОСТОЯНИЯ ДЛЯ ОНБОРДИНГА ==========
ASK_NAME, ASK_GENDER, ASK_AGE, ASK_LOOKING_FOR, ASK_PREFERENCE, ASK_CONFIRM = range(6)

# ========== НАСТРОЙКА ЛОГИРОВАНИЯ ==========
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========== БАЗА ДАННЫХ ==========
class Database:
    def __init__(self, filepath: str = "database.json"):
        self.filepath = filepath
        self.load()
    
    def load(self):
        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.users = data.get('users', {})
                self.referrals = data.get('referrals', [])
        except (FileNotFoundError, json.JSONDecodeError):
            self.users = {}
            self.referrals = []
        self.save()
    
    def save(self):
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump({
                'users': self.users,
                'referrals': self.referrals
            }, f, ensure_ascii=False, indent=2)
    
    def get_user(self, telegram_id: str) -> Optional[dict]:
        return self.users.get(str(telegram_id))
    
    def create_user(self, telegram_id: str, data: dict):
        self.users[str(telegram_id)] = data
        self.save()
    
    def update_user(self, telegram_id: str, data: dict):
        if str(telegram_id) in self.users:
            self.users[str(telegram_id)].update(data)
            self.save()
    
    def add_referral(self, user_id: str, invited_id: str):
        self.referrals.append({
            'user_id': user_id,
            'invited_id': invited_id,
            'date': datetime.now().isoformat()
        })
        user = self.get_user(user_id)
        if user:
            user['free_18_count'] = user.get('free_18_count', 0) + 1
            user['referrals_count'] = user.get('referrals_count', 0) + 1
            self.save()

db = Database()

# ========== AI ЛОГИКА ==========
class Character:
    def __init__(self, user_looking_for: str = "girls"):
        self.gender = "girl" if user_looking_for == "girls" else "boy"
        self.name = random.choice(NAMES_GIRLS if self.gender == "girl" else NAMES_BOYS)
        self.character = random.choice(CHARACTERS)
        self.ethnicity = random.choice(ETHNICITY)
        self.city = random.choice(CITIES)
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "gender": self.gender,
            "character": self.character,
            "ethnicity": self.ethnicity,
            "city": self.city
        }
    
    def get_greeting(self, user_name: str, is_18plus: bool = False) -> str:
        if is_18plus:
            greetings = [
                f"Привет, {user_name}~ Я {self.name}, мне 21. Обожаю уверенных мужчин... ✨",
                f"Ооо, {user_name}... Ты мне сразу понравился~ Я {self.name} 💕",
                f"Ммм, {user_name}, рада познакомиться... Надеюсь, ты не стеснительный~ 😏",
                f"Хей! Я {self.name} из {self.city}. Говорят, я {self.character}. А ты какой? 🔥"
            ]
        else:
            greetings = [
                f"Привет! Я {self.name} из {self.city}. Очень приятно познакомиться, {user_name}!",
                f"Хай! Меня зовут {self.name}, я {self.character} девушка. Рада общению!",
                f"Здравствуй, {user_name}! Я {self.name}, люблю гулять по {self.city}. Расскажи о себе!",
                f"Привет-привет! Я {self.name}. Сегодня такое настроение... А у тебя как дела?"
            ]
        return random.choice(greetings)
    
    def get_refusal(self) -> str:
        refusals = [
            "Ой... Давай не будем об этом, я не такая 🙈",
            "Эмм, это слишком... Давай просто поболтаем?",
            "Я не на такое настроена, извини...",
            "Ты слишком быстрый, давай сначала узнаем друг друга получше",
            "Мне это немного неудобно... Может, сменим тему?"
        ]
        return random.choice(refusals)

class KimiAI:
    def __init__(self):
        self.api_key = MOONSHOT_API_KEY
        self.url = MOONSHOT_API_URL
    
    def get_response(self, messages: List[dict], character: dict, is_18plus: bool) -> str:
        if not USE_AI or not self.api_key:
            return "❌ Ошибка сервера. Пожалуйста, попробуй позже."
        
        gender_word = "девушка" if character['gender'] == 'girl' else "парень"
        system_prompt = f"""
Ты - {character['name']}, {character['character']} {character['ethnicity']} {gender_word} из города {character['city']}.

Правила:
- Отвечай КОРОТКО (2-3 предложения)
- Будь ЭМОЦИОНАЛЬНОЙ, используй смайлики
- {"Можешь флиртовать, но без порнографии" if is_18plus else "БЕЗ 18+ контента"}
- НИКОГДА не говори что ты бот или AI
- НЕ предлагай встретиться
- НЕ давай контакты
"""
        
        kimi_messages = [{"role": "system", "content": system_prompt}]
        
        for msg in messages[-MAX_HISTORY:]:
            role = "assistant" if msg.get("role") == "assistant" else "user"
            kimi_messages.append({"role": role, "content": msg.get("content", "")})
        
        try:
            response = requests.post(
                self.url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "moonshot-v1-8k",
                    "messages": kimi_messages,
                    "temperature": 0.9,
                    "max_tokens": 150
                },
                timeout=10
            )
            
            if response.status_code == 200:
                result = response.json()
                return result["choices"][0]["message"]["content"]
            else:
                logger.error(f"Kimi API error: {response.status_code}")
                return "❌ Ошибка сервера. Попробуй позже."
                
        except Exception as e:
            logger.error(f"AI Error: {e}")
            return "❌ Ошибка сервера. Попробуй позже."

ai_client = KimiAI()

# ========== КЛАВИАТУРЫ ==========
def get_main_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("💬 Обычный чат", callback_data="chat_normal")],
        [InlineKeyboardButton("🔥 18+ чат", callback_data="chat_18plus")],
        [InlineKeyboardButton("👤 Профиль", callback_data="profile")],
        [InlineKeyboardButton("🎁 Реферал", callback_data="referral")],
        [InlineKeyboardButton("💎 Премиум", callback_data="premium")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_gender_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("👨 Мужской", callback_data="gender_male")],
        [InlineKeyboardButton("👩 Женский", callback_data="gender_female")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_looking_for_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("👧 Девушек", callback_data="looking_girls")],
        [InlineKeyboardButton("👦 Парней", callback_data="looking_boys")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_preference_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("💬 Обычное общение", callback_data="pref_normal")],
        [InlineKeyboardButton("🔥 18+", callback_data="pref_18plus")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_confirm_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("✅ Мне есть 18 лет", callback_data="confirm_18")],
        [InlineKeyboardButton("❌ Нет, мне нет 18", callback_data="confirm_underage")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_chat_keyboard(is_18plus: bool = False) -> InlineKeyboardMarkup:
    keyboard = [[InlineKeyboardButton("🚪 Завершить диалог", callback_data="end_chat")]]
    return InlineKeyboardMarkup(keyboard)

def get_reconnect_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(f"💫 Вернуться к ней — {PRICES['reconnect_18']}⭐", callback_data="reconnect_18")],
        [InlineKeyboardButton("🏠 В меню", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ========== ОБРАБОТЧИКИ ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = str(update.effective_user.id)
    user = db.get_user(user_id)
    
    if context.args and context.args[0].startswith("ref_"):
        referrer_id = context.args[0][4:]
        if referrer_id != user_id and db.get_user(referrer_id):
            db.add_referral(referrer_id, user_id)
            await update.message.reply_text("🎉 +1 доступ к 18+ чату за реферала!")
    
    if user and user.get("onboarding_completed"):
        await update.message.reply_text(
            f"С возвращением, {user['name']}! 👋",
            reply_markup=get_main_keyboard()
        )
        return ConversationHandler.END
    
    context.user_data.clear()
    await update.message.reply_text("✨ Привет! Как тебя зовут?")
    return ASK_NAME

async def ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['name'] = update.message.text
    await update.message.reply_text("Выбери свой пол:", reply_markup=get_gender_keyboard())
    return ASK_GENDER

async def ask_gender(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data['gender'] = "male" if query.data == "gender_male" else "female"
    await query.edit_message_text("Сколько тебе лет?")
    return ASK_AGE

async def ask_age(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        age = int(update.message.text)
        if age < 18:
            await update.message.reply_text("❌ Только для 18+", reply_markup=get_confirm_keyboard())
            return ASK_CONFIRM
        context.user_data['age'] = age
        await update.message.reply_text("Кого хочешь найти?", reply_markup=get_looking_for_keyboard())
        return ASK_LOOKING_FOR
    except ValueError:
        await update.message.reply_text("Напиши число")
        return ASK_AGE

async def ask_looking_for(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data['looking_for'] = "girls" if query.data == "looking_girls" else "boys"
    await query.edit_message_text("Тип общения:", reply_markup=get_preference_keyboard())
    return ASK_PREFERENCE

async def ask_preference(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data['preference'] = "normal" if query.data == "pref_normal" else "18plus"
    
    text = f"📝 Проверь данные:\nИмя: {context.user_data['name']}\nВозраст: {context.user_data['age']}\n\nПодтверждаешь 18 лет?"
    await query.edit_message_text(text, reply_markup=get_confirm_keyboard())
    return ASK_CONFIRM

async def confirm_age(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    if query.data == "confirm_underage":
        await query.edit_message_text("❌ Доступ запрещён")
        return ConversationHandler.END
    
    user_id = str(update.effective_user.id)
    db.create_user(user_id, {
        "name": context.user_data['name'],
        "gender": context.user_data['gender'],
        "age": context.user_data['age'],
        "looking_for": context.user_data['looking_for'],
        "preference": context.user_data['preference'],
        "free_18_count": 4,
        "premium_until": None,
        "referrals_count": 0,
        "onboarding_completed": True,
        "created_at": datetime.now().isoformat()
    })
    
    await query.edit_message_text(
        f"🎉 Добро пожаловать, {context.user_data['name']}!\n🔥 Ты получил 4 бесплатных доступа к 18+ чату!",
        reply_markup=get_main_keyboard()
    )
    return ConversationHandler.END

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = str(update.effective_user.id)
    user = db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("Ошибка! Напиши /start")
        return
    
    if query.data == "main_menu":
        await query.edit_message_text("Главное меню:", reply_markup=get_main_keyboard())
        return
    
    elif query.data == "chat_normal":
        context.user_data['chat_type'] = 'normal'
        context.user_data['is_18plus'] = False
        context.user_data['messages'] = []
        character = Character(user.get('looking_for', 'girls'))
        context.user_data['character'] = character.to_dict()
        greeting = character.get_greeting(user['name'], False)
        await query.edit_message_text(f"✨ {greeting}\n\nНапиши что-нибудь...", reply_markup=get_chat_keyboard(False))
        return
    
    elif query.data == "chat_18plus":
        is_premium = user.get('premium_until') and datetime.fromisoformat(user['premium_until']) > datetime.now()
        free_count = user.get('free_18_count', 0)
        
        if not is_premium and free_count <= 0:
            await query.edit_message_text(
                "💔 Нас разъединило...\nВернись за 49 ⭐",
                reply_markup=get_reconnect_keyboard()
            )
            return
        
        if not is_premium:
            user['free_18_count'] = free_count - 1
            db.update_user(user_id, {'free_18_count': user['free_18_count']})
        
        context.user_data['chat_type'] = '18plus'
        context.user_data['is_18plus'] = True
        context.user_data['messages'] = []
        character = Character(user.get('looking_for', 'girls'))
        context.user_data['character'] = character.to_dict()
        greeting = character.get_greeting(user['name'], True)
        await query.edit_message_text(f"🔥 {greeting}\n\nНапиши что-нибудь...", reply_markup=get_chat_keyboard(True))
        return
    
    elif query.data == "reconnect_18":
        await send_invoice(update, context, "reconnect_18")
        return
    
    elif query.data == "profile":
        is_premium = user.get('premium_until') and datetime.fromisoformat(user['premium_until']) > datetime.now()
        text = f"👤 *{user['name']}*\nСтатус: {'💎 Premium' if is_premium else '🆓 Free'}\n🔥 Доступов: {user.get('free_18_count', 0)}\n👥 Рефералов: {user.get('referrals_count', 0)}"
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="main_menu")]]))
        return
    
    elif query.data == "referral":
        bot_username = context.bot.username
        link = f"https://t.me/{bot_username}?start=ref_{user_id}"
        await query.edit_message_text(f"🎁 *Твоя ссылка:*\n`{link}`\n\nЗа каждого друга +1 доступ!", parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="main_menu")]]))
        return
    
    elif query.data == "premium":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"1 день — 49⭐", callback_data="buy_premium_1day")],
            [InlineKeyboardButton(f"7 дней — 180⭐", callback_data="buy_premium_7days")],
            [InlineKeyboardButton(f"30 дней — 300⭐", callback_data="buy_premium_30days")],
            [InlineKeyboardButton("◀️ Назад", callback_data="main_menu")]
        ])
        await query.edit_message_text("💎 *Премиум:* безлимитный 18+ чат", parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
        return
    
    elif query.data.startswith("buy_premium_"):
        days = query.data.replace("buy_premium_", "")
        await send_invoice(update, context, f"premium_{days}")
        return
    
    elif query.data == "end_chat":
        context.user_data.clear()
        await query.edit_message_text("Диалог завершён. Возвращайся!", reply_markup=get_main_keyboard())
        return

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = db.get_user(user_id)
    
    if not user or not user.get('onboarding_completed'):
        await update.message.reply_text("Начни с /start")
        return
    
    if not context.user_data.get('character'):
        await update.message.reply_text("Сначала выбери собеседника в меню!", reply_markup=get_main_keyboard())
        return
    
    user_message = update.message.text
    is_18plus = context.user_data.get('is_18plus', False)
    character = context.user_data.get('character')
    messages = context.user_data.get('messages', [])
    
    # Проверка на 18+ в обычном чате
    if not is_18plus:
        forbidden = ['секс', 'трах', 'член', 'хуй', 'пизд']
        if any(word in user_message.lower() for word in forbidden):
            await update.message.reply_text(Character().get_refusal(), reply_markup=get_chat_keyboard(False))
            context.user_data.clear()
            await update.message.reply_text("Диалог завершён.", reply_markup=get_main_keyboard())
            return
    
    messages.append({"role": "user", "content": user_message})
    await update.message.chat.send_action(action="typing")
    
    response = await asyncio.to_thread(ai_client.get_response, messages, character, is_18plus)
    
    messages.append({"role": "assistant", "content": response})
    context.user_data['messages'] = messages
    
    await update.message.reply_text(response, reply_markup=get_chat_keyboard(is_18plus))

async def send_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE, product: str):
    chat_id = update.effective_chat.id
    products = {
        "reconnect_18": {"title": "🔥 18+ Чат", "description": "Возобновление диалога", "price": 49},
        "premium_1day": {"title": "💎 Premium 1 день", "description": "Безлимитный чат на 24ч", "price": 49},
        "premium_7days": {"title": "💎 Premium 7 дней", "description": "Безлимитный чат на неделю", "price": 180},
        "premium_30days": {"title": "💎 Premium 30 дней", "description": "Безлимитный чат на месяц", "price": 300}
    }
    p = products[product]
    await context.bot.send_invoice(
        chat_id=chat_id, title=p["title"], description=p["description"],
        payload=f"{product}_{chat_id}", provider_token="", currency="XTR",
        prices=[{"label": "Доступ", "amount": p["price"]}], start_parameter="pay"
    )

async def pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)

async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    payload = update.message.successful_payment.invoice_payload
    
    if "reconnect_18" in payload:
        user = db.get_user(user_id)
        user['free_18_count'] = user.get('free_18_count', 0) + 1
        db.update_user(user_id, {'free_18_count': user['free_18_count']})
        await update.message.reply_text("✅ +1 доступ к 18+ чату!", reply_markup=get_main_keyboard())
    
    elif "premium" in payload:
        days = 1 if "1day" in payload else 7 if "7days" in payload else 30
        until = datetime.now() + timedelta(days=days)
        db.update_user(user_id, {'premium_until': until.isoformat()})
        await update.message.reply_text(f"✅ Premium активирован на {days} дней!", reply_markup=get_main_keyboard())

# ========== ЗАПУСК ==========
async def main():
    application = Application.builder().token(TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_name)],
            ASK_GENDER: [CallbackQueryHandler(ask_gender)],
            ASK_AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_age)],
            ASK_LOOKING_FOR: [CallbackQueryHandler(ask_looking_for)],
            ASK_PREFERENCE: [CallbackQueryHandler(ask_preference)],
            ASK_CONFIRM: [CallbackQueryHandler(confirm_age)],
        },
        fallbacks=[CommandHandler("start", start)],
    )
    
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    application.add_handler(MessageHandler(filters.PRE_CHECKOUT_QUERY, pre_checkout))
    
    if RENDER_EXTERNAL_URL:
        webhook_url = f"{RENDER_EXTERNAL_URL}/webhook"
        await application.bot.set_webhook(webhook_url)
        logger.info(f"Webhook: {webhook_url}")
        
        async def webhook(request: Request) -> Response:
            try:
                update = Update.de_json(await request.json(), application.bot)
                await application.update_queue.put(update)
                return Response()
            except Exception as e:
                logger.error(f"Webhook error: {e}")
                return Response(status_code=500)
        
        async def healthcheck(request: Request) -> PlainTextResponse:
            return PlainTextResponse("OK")
        
        starlette_app = Starlette(routes=[
            Route("/webhook", webhook, methods=["POST"]),
            Route("/healthcheck", healthcheck, methods=["GET"]),
        ])
        
        config = uvicorn.Config(starlette_app, host="0.0.0.0", port=PORT, log_level="info")
        server = uvicorn.Server(config)
        
        async with application:
            await application.start()
            await server.serve()
            await application.stop()
    else:
        logger.info("Запуск в polling режиме")
        await application.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
