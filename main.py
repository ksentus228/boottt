import os
import json
import random
import asyncio
import logging
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from functools import lru_cache

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters
)
from telegram.constants import ParseMode

# ========== КОНФИГУРАЦИЯ ==========
TOKEN = os.environ.get("TELEGRAM_TOKEN")

# API Kimi (Moonshot)
MOONSHOT_API_KEY = "sk-2VbR6yBej6324pC3TbnkXoIjOECuyvwN9qdv13ZTGbxHoRQB"
MOONSHOT_API_URL = "https://api.moonshot.ai/v1/chat/completions"

# Настройки
MAX_HISTORY = 10
USE_AI = True

# Цены (в Telegram Stars)
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

# ========== БАЗА ДАННЫХ (JSON) ==========
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

# ========== AI ЛОГИКА (Kimi Moonshot) ==========
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
        """Получение ответа от Kimi AI"""
        if not USE_AI or not self.api_key:
            return "❌ Ошибка сервера. Пожалуйста, попробуй позже."
        
        # Системный промпт
        gender_word = "девушка" if character['gender'] == 'girl' else "парень"
        system_prompt = f"""
Ты - {character['name']}, {character['character']} {character['ethnicity']} {gender_word} из города {character['city']}.

Твои правила:
- Отвечай КОРОТКО (максимум 2-3 предложения)
- Будь ЭМОЦИОНАЛЬНОЙ и ЖИВОЙ, используй смайлики
- {"Можешь флиртовать и быть более откровенной, но без порнографии" if is_18plus else "Общайся дружелюбно, лёгкий флирт допустим, но БЕЗ 18+ контента"}
- НИКОГДА не говори, что ты бот, AI или нейросеть
- НЕ предлагай встретиться в реальной жизни
- НЕ давай свой Telegram, телефон или другие контакты
- Ты реальный человек, у тебя есть своя жизнь и эмоции
{"- Если собеседник слишком откровенен - мягко откажи" if not is_18plus else ""}

Твоя задача - создать иллюзию живого общения, быть интересной и вовлекать собеседника.
"""
        
        # Форматируем сообщения для Kimi
        kimi_messages = [{"role": "system", "content": system_prompt}]
        
        # Добавляем историю
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
                logger.error(f"Kimi API error: {response.status_code} - {response.text}")
                return "❌ Ошибка сервера. Пожалуйста, попробуй позже."
                
        except requests.exceptions.Timeout:
            logger.error("AI Timeout")
            return "❌ Ошибка сервера. Сервер не отвечает, попробуй позже."
        except requests.exceptions.ConnectionError:
            logger.error("AI Connection Error")
            return "❌ Ошибка сервера. Нет соединения с сервером."
        except Exception as e:
            logger.error(f"AI Error: {e}")
            return "❌ Ошибка сервера. Пожалуйста, попробуй позже."

ai_client = KimiAI()

# ========== КЛАВИАТУРЫ ==========
def get_main_keyboard(is_premium: bool = False) -> InlineKeyboardMarkup:
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
    keyboard = [
        [InlineKeyboardButton("🚪 Завершить диалог", callback_data="end_chat")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_reconnect_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(f"💫 Вернуться к ней — {PRICES['reconnect_18']}⭐", callback_data="reconnect_18")],
        [InlineKeyboardButton("🏠 В меню", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ========== ФУНКЦИЯ ОТПРАВКИ ИНВОЙСА ==========
async def send_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE, product: str, price: int = None):
    chat_id = update.effective_chat.id
    
    products = {
        "reconnect_18": {"title": "🔥 18+ Чат", "description": "Возобновление диалога"},
        "premium_1day": {"title": "💎 Premium 1 день", "description": "Безлимитный 18+ чат на 24 часа"},
        "premium_7days": {"title": "💎 Premium 7 дней", "description": "Безлимитный 18+ чат на неделю"},
        "premium_30days": {"title": "💎 Premium 30 дней", "description": "Безлимитный 18+ чат на месяц"}
    }
    
    if price is None:
        price = PRICES.get(product, 49)
    
    await context.bot.send_invoice(
        chat_id=chat_id,
        title=products[product]["title"],
        description=products[product]["description"],
        payload=f"{product}_{chat_id}_{int(datetime.now().timestamp())}",
        provider_token="",
        currency="XTR",
        prices=[{"label": "Доступ", "amount": price}],
        start_parameter="pay"
    )

# ========== ОБРАБОТЧИКИ ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = str(update.effective_user.id)
    user = db.get_user(user_id)
    
    # Проверка на реферала
    if context.args and context.args[0].startswith("ref_"):
        referrer_id = context.args[0][4:]
        if referrer_id != user_id and db.get_user(referrer_id):
            db.add_referral(referrer_id, user_id)
            await update.message.reply_text(
                "🎉 Реферальный бонус активирован!\n"
                "Твой друг получил +1 доступ к 18+ чату"
            )
    
    if user and user.get("onboarding_completed"):
        await update.message.reply_text(
            f"С возвращением, {user['name']}! 👋\n\n"
            "Выбери, с кем хочешь пообщаться сегодня:",
            reply_markup=get_main_keyboard()
        )
        return ConversationHandler.END
    
    context.user_data.clear()
    await update.message.reply_text(
        "✨ Привет! Давай познакомимся ✨\n\n"
        "Как тебя зовут?"
    )
    return ASK_NAME

async def ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['name'] = update.message.text
    await update.message.reply_text(
        "Отлично! Теперь выбери свой пол:",
        reply_markup=get_gender_keyboard()
    )
    return ASK_GENDER

async def ask_gender(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    gender_map = {"gender_male": "male", "gender_female": "female"}
    context.user_data['gender'] = gender_map[query.data]
    
    await query.edit_message_text(
        "Сколько тебе лет? (напиши цифру)"
    )
    return ASK_AGE

async def ask_age(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        age = int(update.message.text)
        if age < 18:
            await update.message.reply_text(
                "❌ Извини, бот только для пользователей старше 18 лет",
                reply_markup=get_confirm_keyboard()
            )
            return ASK_CONFIRM
        context.user_data['age'] = age
        
        await update.message.reply_text(
            "Кого ты хочешь найти для общения?",
            reply_markup=get_looking_for_keyboard()
        )
        return ASK_LOOKING_FOR
    except ValueError:
        await update.message.reply_text("Пожалуйста, напиши число (твой возраст)")
        return ASK_AGE

async def ask_looking_for(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    looking_map = {"looking_girls": "girls", "looking_boys": "boys"}
    context.user_data['looking_for'] = looking_map[query.data]
    
    await query.edit_message_text(
        "Какой тип общения тебя интересует?",
        reply_markup=get_preference_keyboard()
    )
    return ASK_PREFERENCE

async def ask_preference(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    pref_map = {"pref_normal": "normal", "pref_18plus": "18plus"}
    context.user_data['preference'] = pref_map[query.data]
    
    await query.edit_message_text(
        f"📝 Проверь свои данные:\n\n"
        f"Имя: {context.user_data['name']}\n"
        f"Пол: {context.user_data['gender']}\n"
        f"Возраст: {context.user_data['age']}\n"
        f"Ищу: {context.user_data['looking_for']}\n"
        f"Предпочтения: {context.user_data['preference']}\n\n"
        f"Подтверждаешь, что тебе есть 18 лет?",
        reply_markup=get_confirm_keyboard()
    )
    return ASK_CONFIRM

async def confirm_age(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    if query.data == "confirm_underage":
        await query.edit_message_text(
            "❌ Извини, бот доступен только пользователям старше 18 лет.\n"
            "Возвращайся, когда исполнится 18! 👋"
        )
        return ConversationHandler.END
    
    user_id = str(update.effective_user.id)
    user_data = {
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
    }
    
    db.create_user(user_id, user_data)
    
    await query.edit_message_text(
        f"🎉 Добро пожаловать, {user_data['name']}!\n\n"
        f"🔥 Ты получил 4 бесплатных доступа к 18+ чату!\n\n"
        f"Выбери, с кем хочешь пообщаться:",
        reply_markup=get_main_keyboard()
    )
    return ConversationHandler.END

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = str(update.effective_user.id)
    user = db.get_user(user_id)
    
    if not user:
        await query.edit_message_text("Ошибка! Начни заново: /start")
        return
    
    # MAIN MENU
    if query.data == "main_menu":
        await query.edit_message_text(
            "Главное меню:",
            reply_markup=get_main_keyboard()
        )
        return
    
    # NORMAL CHAT
    elif query.data == "chat_normal":
        context.user_data['chat_type'] = 'normal'
        context.user_data['is_18plus'] = False
        context.user_data['messages'] = []
        
        character = Character(user.get('looking_for', 'girls'))
        context.user_data['character'] = character.to_dict()
        
        greeting = character.get_greeting(user['name'], False)
        
        await query.edit_message_text(
            f"✨ Твой собеседник найден! ✨\n\n"
            f"{greeting}\n\n"
            f"💡 Напиши что-нибудь...",
            reply_markup=get_chat_keyboard(False)
        )
        return
    
    # 18+ CHAT
    elif query.data == "chat_18plus":
        is_premium = user.get('premium_until') and datetime.fromisoformat(user['premium_until']) > datetime.now()
        free_count = user.get('free_18_count', 0)
        
        if not is_premium and free_count <= 0:
            await query.edit_message_text(
                "💔 Похоже… нас разъединило 😔\n"
                "Я бы хотела продолжить с тобой…\n"
                "Если хочешь — можешь снова подключиться ко мне за 49 ⭐",
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
        
        await query.edit_message_text(
            f"🔥 Твой собеседник найден! 🔥\n\n"
            f"{greeting}\n\n"
            f"💕 Напиши что-нибудь...",
            reply_markup=get_chat_keyboard(True)
        )
        return
    
    # RECONNECT
    elif query.data == "reconnect_18":
        await send_invoice(update, context, "reconnect_18")
        return
    
    # PROFILE
    elif query.data == "profile":
        is_premium = user.get('premium_until') and datetime.fromisoformat(user['premium_until']) > datetime.now()
        premium_text = f"до {datetime.fromisoformat(user['premium_until']).strftime('%d.%m.%Y')}" if is_premium else "Нет"
        
        profile_text = (
            f"👤 *Твой профиль*\n\n"
            f"Имя: {user['name']}\n"
            f"Статус: {'💎 Премиум ' + premium_text if is_premium else '🆓 Бесплатный'}\n"
            f"Приглашено друзей: {user.get('referrals_count', 0)}\n"
            f"🔥 Осталось 18+ доступов: {user.get('free_18_count', 0)}"
        )
        
        await query.edit_message_text(
            profile_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Назад", callback_data="main_menu")]
            ])
        )
        return
    
    # REFERRAL
    elif query.data == "referral":
        bot_username = context.bot.username
        ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
        
        await query.edit_message_text(
            f"🎁 *Реферальная программа*\n\n"
            f"Приглашай друзей и получай +1 доступ к 18+ чату!\n\n"
            f"Твоя ссылка:\n`{ref_link}`\n\n"
            f"👥 Приглашено: {user.get('referrals_count', 0)}\n"
            f"🔥 Получено бонусов: {user.get('referrals_count', 0)}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Назад", callback_data="main_menu")]
            ])
        )
        return
    
    # PREMIUM
    elif query.data == "premium":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"1 день — {PRICES['premium_1day']}⭐", callback_data="buy_premium_1day")],
            [InlineKeyboardButton(f"7 дней — {PRICES['premium_7days']}⭐", callback_data="buy_premium_7days")],
            [InlineKeyboardButton(f"30 дней — {PRICES['premium_30days']}⭐", callback_data="buy_premium_30days")],
            [InlineKeyboardButton("◀️ Назад", callback_data="main_menu")]
        ])
        
        await query.edit_message_text(
            "💎 *Премиум подписка*\n\n"
            "✅ Безлимитный доступ к 18+ чатам\n"
            "✅ Никаких обрывов диалога\n"
            "✅ Приоритет в общении\n\n"
            "Выбери пакет:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )
        return
    
    elif query.data.startswith("buy_premium_"):
        days = query.data.replace("buy_premium_", "")
        await send_invoice(update, context, f"premium_{days}")
        return
    
    # END CHAT
    elif query.data == "end_chat":
        context.user_data.clear()
        await query.edit_message_text(
            "Диалог завершён. Возвращайся в любое время! 💫",
            reply_markup=get_main_keyboard()
        )
        return

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = db.get_user(user_id)
    
    if not user or not user.get('onboarding_completed'):
        await update.message.reply_text("Начни с /start")
        return
    
    # Проверяем, в чате ли пользователь
    if not context.user_data.get('character'):
        await update.message.reply_text(
            "Сначала выбери собеседника в меню!",
            reply_markup=get_main_keyboard()
        )
        return
    
    user_message = update.message.text
    is_18plus = context.user_data.get('is_18plus', False)
    character = context.user_data.get('character')
    messages = context.user_data.get('messages', [])
    
    # Проверка на 18+ контент в обычном чате
    if not is_18plus:
        forbidden_words = ['секс', 'трах', 'член', 'писька', 'киска', 'выеба', 'ебал', 'хуй', 'пизд']
        if any(word in user_message.lower() for word in forbidden_words):
            refusal = Character().get_refusal()
            await update.message.reply_text(refusal, reply_markup=get_chat_keyboard(False))
            # Обрываем диалог
            context.user_data.clear()
            await update.message.reply_text("Диалог завершён.", reply_markup=get_main_keyboard())
            return
    
    # Добавляем сообщение пользователя в историю
    messages.append({"role": "user", "content": user_message})
    
    # Отправляем статус "печатает"
    await update.message.chat.send_action(action="typing")
    
    # Получаем ответ от AI
    try:
        response = await asyncio.to_thread(
            ai_client.get_response,
            messages,
            character,
            is_18plus
        )
    except Exception as e:
        logger.error(f"Error getting AI response: {e}")
        response = "❌ Ошибка сервера. Пожалуйста, попробуй позже."
    
    # Добавляем ответ в историю
    messages.append({"role": "assistant", "content": response})
    context.user_data['messages'] = messages
    
    await update.message.reply_text(response, reply_markup=get_chat_keyboard(is_18plus))

async def pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    await query.answer(ok=True)

async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    payload = update.message.successful_payment.invoice_payload
    
    if "reconnect_18" in payload:
        # Добавляем 1 бесплатный доступ
        user = db.get_user(user_id)
        if user:
            user['free_18_count'] = user.get('free_18_count', 0) + 1
            db.update_user(user_id, {'free_18_count': user['free_18_count']})
            await update.message.reply_text(
                "✅ Оплата прошла успешно!\n"
                "🔥 Ты получил +1 доступ к 18+ чату!\n\n"
                "Нажми на кнопку 18+ чат в меню, чтобы продолжить общение.",
                reply_markup=get_main_keyboard()
            )
    
    elif "premium" in payload:
        days_map = {"1day": 1, "7days": 7, "30days": 30}
        for key, days in days_map.items():
            if key in payload:
                until = datetime.now() + timedelta(days=days)
                db.update_user(user_id, {'premium_until': until.isoformat()})
                await update.message.reply_text(
                    f"✅ Премиум активирован на {days} дней!\n"
                    f"Теперь у тебя безлимитный 18+ чат 🎉",
                    reply_markup=get_main_keyboard()
                )
                break

# ========== ЗАПУСК БОТА ==========
def main():
    app = Application.builder().token(TOKEN).build()
    
    # Онбординг
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
    
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", lambda u,c: u.message.reply_text("Меню:", reply_markup=get_main_keyboard())))
    
    # Платежи
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    app.add_handler(MessageHandler(filters.PRE_CHECKOUT_QUERY, pre_checkout))
    
    print("✅ Бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
