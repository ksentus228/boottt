import urllib.request, json, time, random
from datetime import datetime, timedelta

from config import TOKEN, ADMIN_CODE, PRICE_1_DAY, PRICE_7_DAYS, PRICE_30_DAYS, FREE_TRIAL_REQUESTS, USERS_FILE, DIALOGS_HISTORY_FILE
from database import load_json, save_json, save_dialog_history
from girl_generator import generate_girl
from ai_responder import get_ai_response
from keyboards import main_menu, preferences_menu, subscription_menu, dialog_buttons, back_button
from texts import TEXTS as T

# Загружаем данные
users = load_json(USERS_FILE)
dialogs = {}  # Активные диалоги
waiting = {}
admins = {}

# Получаем имя бота
try:
    req = urllib.request.urlopen(f"https://api.telegram.org/bot{TOKEN}/getMe")
    bot_name = json.loads(req.read())["result"]["username"]
except:
    bot_name = "AIGirlBot"

def send(cid, txt, rm=None):
    d = {"chat_id": cid, "text": txt, "parse_mode": "Markdown"}
    if rm:
        d["reply_markup"] = json.dumps(rm)
    try:
        urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data=json.dumps(d).encode(), headers={"Content-Type": "application/json"}), timeout=5)
    except:
        pass

def edit(cid, mid, txt, rm=None):
    d = {"chat_id": cid, "message_id": mid, "text": txt, "parse_mode": "Markdown"}
    if rm:
        d["reply_markup"] = json.dumps(rm)
    try:
        urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/editMessageText", data=json.dumps(d).encode(), headers={"Content-Type": "application/json"}), timeout=5)
    except:
        pass

def is_premium(uid):
    u = users.get(str(uid), {})
    if u.get("prem") and u.get("until") and datetime.fromisoformat(u["until"]) > datetime.now():
        return True
    return False

def get_adult_requests_left(uid):
    u = users.get(str(uid), {})
    if is_premium(uid):
        return 999
    used = u.get("adult_used", 0)
    free = u.get("free_adult_requests", FREE_TRIAL_REQUESTS)
    bonus = u.get("bonus_requests", 0)
    return max(0, free + bonus - used)

def simulate_search(cid, mid, msg):
    """Симуляция поиска от 5 до 20 секунд"""
    search_time = random.randint(5, 20)
    for i in range(search_time):
        time.sleep(1)
        if i % 3 == 0 and i > 0:
            dots = "." * ((i // 3) % 3 + 1)
            edit(cid, mid, msg + dots, None)

def process(update):
    global dialogs
    
    # Обработка предоплаты
    if "pre_checkout_query" in update:
        query = update["pre_checkout_query"]
        url = f"https://api.telegram.org/bot{TOKEN}/answerPreCheckoutQuery"
        data = {"pre_checkout_query_id": query["id"], "ok": True}
        try:
            urllib.request.urlopen(urllib.request.Request(url, data=json.dumps(data).encode(), headers={"Content-Type": "application/json"}), timeout=5)
        except:
            pass
        return
    
    if "message" in update:
        cid = str(update["message"]["chat"]["id"])
        text = update["message"].get("text", "")
        
        # Обработка успешной оплаты
        if "successful_payment" in update["message"]:
            payload = update["message"]["successful_payment"]["invoice_payload"]
            if "premium" in payload:
                parts = payload.split("_")
                plan = parts[1] if len(parts) > 1 else "day"
                days = 1 if plan == "day" else 7 if plan == "week" else 30
                if cid not in users:
                    users[cid] = {}
                users[cid]["prem"] = True
                users[cid]["until"] = (datetime.now() + timedelta(days=days)).isoformat()
                save_json(USERS_FILE, users)
                send(cid, T["prem_act"].format(days), main_menu(cid in admins))
            return
        
        # Обработка /start
        if text == "/start":
            if cid not in users:
                users[cid] = {
                    "name": None, "age": None, "prem": False,
                    "until": datetime.now().isoformat(), "adult_used": 0,
                    "free_adult_requests": FREE_TRIAL_REQUESTS, "bonus_requests": 0,
                    "refs": 0, "dialogs_count": 0, "favorite_nationalities": [],
                    "asked_preferences": False
                }
                save_json(USERS_FILE, users)
                send(cid, T["disclaimer"], None)
                send(cid, "👋 *Давай познакомимся!*\n\nКак тебя зовут?", None)
            else:
                u = users[cid]
                left = get_adult_requests_left(cid)
                send(cid, T["start"].format(u.get("name", "User"), left), main_menu(cid in admins))
            return
        
        # Если пользователь не зарегистрирован
        if cid not in users:
            users[cid] = {
                "name": None, "age": None, "prem": False,
                "until": datetime.now().isoformat(), "adult_used": 0,
                "free_adult_requests": FREE_TRIAL_REQUESTS, "bonus_requests": 0,
                "refs": 0, "dialogs_count": 0, "favorite_nationalities": [],
                "asked_preferences": False
            }
            save_json(USERS_FILE, users)
            send(cid, T["disclaimer"], None)
            send(cid, "👋 *Давай познакомимся!*\n\nКак тебя зовут?", None)
            return
        
        u = users[cid]
        
        # Регистрация: имя
        if u.get("name") is None:
            u["name"] = text
            save_json(USERS_FILE, users)
            send(cid, f"👋 Приятно познакомиться, *{text}*!\n\nСколько тебе лет?", None)
        
        # Регистрация: возраст
        elif u.get("age") is None:
            try:
                u["age"] = int(text)
                save_json(USERS_FILE, users)
                send(cid, "✅ *Регистрация завершена!*\n\nТеперь ты можешь искать собеседниц 👇", main_menu(cid in admins))
            except:
                send(cid, "❌ Введи число (18-99):", None)
        
        # Активный диалог
        elif cid in dialogs:
            girl = dialogs[cid]["girl"]
            context = dialogs[cid]["context"]
            context.append({"role": "user", "content": text})
            response = get_ai_response(girl, text, context)
            context.append({"role": "assistant", "content": response})
            if len(context) > 10:
                context = context[-10:]
            dialogs[cid]["context"] = context
            send(cid, response, dialog_buttons())
        
        # Поддержка
        elif waiting.get(cid) == "support":
            waiting[cid] = None
            send(cid, T["thanks"], main_menu(cid in admins))
    
    # Обработка callback'ов
    elif "callback_query" in update:
        cb = update["callback_query"]
        cid, mid, data = str(cb["message"]["chat"]["id"]), cb["message"]["message_id"], cb["data"]
        
        if cid not in users:
            users[cid] = {
                "name": None, "age": None, "prem": False,
                "until": datetime.now().isoformat(), "adult_used": 0,
                "free_adult_requests": FREE_TRIAL_REQUESTS, "bonus_requests": 0,
                "refs": 0, "dialogs_count": 0, "favorite_nationalities": [],
                "asked_preferences": False
            }
            save_json(USERS_FILE, users)
        
        u = users[cid]
        
        # Назад
        if data == "back":
            left = get_adult_requests_left(cid)
            edit(cid, mid, T["start"].format(u.get("name", "User"), left), main_menu(cid in admins))
        
        # Премиум меню
        elif data == "subscription":
            edit(cid, mid, T["subscription_title"], subscription_menu())
        
        # Предпочтения
        elif data == "preferences":
            current = u.get("favorite_nationalities", [])
            txt = T["pref_question"]
            if current:
                txt += f"\n\n✅ *Твои предпочтения:* {', '.join(current)}"
            edit(cid, mid, txt, preferences_menu())
        
        # Выбор национальности
        elif data.startswith("pref_"):
            code = data[5:]
            if "favorite_nationalities" not in u:
                u["favorite_nationalities"] = []
            if code in u["favorite_nationalities"]:
                u["favorite_nationalities"].remove(code)
            else:
                u["favorite_nationalities"].append(code)
            save_json(USERS_FILE, users)
            txt = T["pref_question"]
            if u["favorite_nationalities"]:
                txt += f"\n\n✅ *Выбрано:* {', '.join(u['favorite_nationalities'])}"
            edit(cid, mid, txt, preferences_menu())
        
        # Обычный чат
        elif data == "find_normal":
            edit(cid, mid, T["searching"], None)
            simulate_search(cid, mid, T["searching"])
            
            edit(cid, mid, T["policy"], None)
            time.sleep(2)
            
            girl = generate_girl(u.get("favorite_nationalities"), "normal")
            greeting = f"Привет! Меня зовут {girl['name']}. {girl['personality']} 😊"
            dialogs[cid] = {
                "girl": girl,
                "context": [{"role": "assistant", "content": greeting}],
                "mode": "normal",
                "start_time": datetime.now().isoformat()
            }
            u["dialogs_count"] = u.get("dialogs_count", 0) + 1
            save_json(USERS_FILE, users)
            
            edit(cid, mid, T["girl_found"].format(
                girl["name"], girl["age"], girl["nationality"], 
                girl["appearance"], girl["personality"], greeting
            ), dialog_buttons())
            
            # Вопрос о предпочтениях после первого диалога
            if not u.get("asked_preferences"):
                u["asked_preferences"] = True
                save_json(USERS_FILE, users)
                send(cid, T["pref_question"], preferences_menu())
        
        # 18+ чат
        elif data == "find_adult":
            left = get_adult_requests_left(cid)
            if left <= 0:
                edit(cid, mid, T["no_adult"].format(left), {"inline_keyboard": [
                    [{"text": "💎 КУПИТЬ ПРЕМИУМ", "callback_data": "subscription"}],
                    [{"text": "⬅️ НАЗАД", "callback_data": "back"}]
                ]})
                return
            
            if left <= 3:
                send(cid, T["adult_warning"].format(left), None)
            
            edit(cid, mid, T["searching"], None)
            simulate_search(cid, mid, T["searching"])
            
            edit(cid, mid, T["policy"], None)
            time.sleep(2)
            
            girl = generate_girl(u.get("favorite_nationalities"), "adult")
            greeting = f"Привет! Я {girl['name']}. {girl['personality']} 🔥"
            dialogs[cid] = {
                "girl": girl,
                "context": [{"role": "assistant", "content": greeting}],
                "mode": "adult",
                "start_time": datetime.now().isoformat()
            }
            u["adult_used"] = u.get("adult_used", 0) + 1
            u["dialogs_count"] = u.get("dialogs_count", 0) + 1
            save_json(USERS_FILE, users)
            
            edit(cid, mid, T["girl_found"].format(
                girl["name"], girl["age"], girl["nationality"], 
                girl["appearance"], girl["personality"], greeting
            ), dialog_buttons())
            
            if not u.get("asked_preferences"):
                u["asked_preferences"] = True
                save_json(USERS_FILE, users)
                send(cid, T["pref_question"], preferences_menu())
        
        # Завершить диалог
        elif data == "end_dialog":
            if cid in dialogs:
                save_dialog_history(
                    cid, dialogs[cid]["girl"], dialogs[cid]["context"],
                    dialogs[cid]["mode"], dialogs[cid]["start_time"]
                )
                del dialogs[cid]
            edit(cid, mid, T["end_dialog"], main_menu(cid in admins))
        
        # Новая девушка
        elif data == "new_girl":
            if cid in dialogs:
                save_dialog_history(
                    cid, dialogs[cid]["girl"], dialogs[cid]["context"],
                    dialogs[cid]["mode"], dialogs[cid]["start_time"]
                )
                del dialogs[cid]
            edit(cid, mid, T["new_girl"], None)
            simulate_search(cid, mid, T["new_girl"])
            
            mode = "normal"
            edit(cid, mid, T["policy"], None)
            time.sleep(2)
            
            girl = generate_girl(u.get("favorite_nationalities"), mode)
            greeting = f"Привет! Меня зовут {girl['name']}. {girl['personality']} 😊"
            dialogs[cid] = {
                "girl": girl,
                "context": [{"role": "assistant", "content": greeting}],
                "mode": mode,
                "start_time": datetime.now().isoformat()
            }
            u["dialogs_count"] = u.get("dialogs_count", 0) + 1
            save_json(USERS_FILE, users)
            
            edit(cid, mid, T["girl_found"].format(
                girl["name"], girl["age"], girl["nationality"], 
                girl["appearance"], girl["personality"], greeting
            ), dialog_buttons())
        
        # Профиль
        elif data == "profile":
            status = "💎 ПРЕМИУМ" if is_premium(cid) else "🆓 FREE"
            until = datetime.fromisoformat(u["until"]).strftime("%d.%m.%Y") if u.get("prem") and u.get("until") else "-"
            left = get_adult_requests_left(cid)
            edit(cid, mid, T["profile"].format(
                u.get("name", "-"), status, until, left,
                u.get("refs", 0), u.get("bonus_requests", 0), u.get("dialogs_count", 0)
            ), {"inline_keyboard": [
                [{"text": "💎 ПРЕМИУМ", "callback_data": "subscription"}],
                [{"text": "⬅️ НАЗАД", "callback_data": "back"}]
            ]})
        
        # Рефералы
        elif data == "ref":
            edit(cid, mid, T["ref"].format(bot_name, cid, u.get("refs", 0), u.get("bonus_requests", 0)), back_button())
        
        # Поддержка
        elif data == "support":
            edit(cid, mid, T["support"], back_button())
            waiting[cid] = "support"
        
        # Покупка подписки
        elif data.startswith("sub_"):
            plan = data[4:]
            if plan == "day":
                price = PRICE_1_DAY
                days = 1
            elif plan == "week":
                price = PRICE_7_DAYS
                days = 7
            else:
                price = PRICE_30_DAYS
                days = 30
            
            inv = {
                "chat_id": int(cid),
                "title": "💎 ПРЕМИУМ ПОДПИСКА",
                "description": f"{days} дней безлимитного 18+ чата",
                "payload": f"premium_{plan}_{cid}_{int(time.time())}",
                "currency": "XTR",
                "prices": [{"label": "PREMIUM", "amount": price}],
                "start_parameter": "premium_sub"
            }
            try:
                req = urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/sendInvoice", data=json.dumps(inv).encode(), headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=10)
                edit(cid, mid, T["inv"].format(price), back_button())
            except Exception as e:
                edit(cid, mid, f"❌ Ошибка: {str(e)}", back_button())
        
        # Админ панель
        elif data == "admin" and cid in admins:
            edit(cid, mid, "🔐 *АДМИН ПАНЕЛЬ*", {"inline_keyboard": [
                [{"text": "📊 СТАТИСТИКА", "callback_data": "stats"}],
                [{"text": "⬅️ НАЗАД", "callback_data": "back"}]
            ]})
        
        # Статистика
        elif data == "stats" and cid in admins:
            prem = sum(1 for u in users.values() if is_premium(u))
            total_dialogs = sum(u.get("dialogs_count", 0) for u in users.values())
            hist = load_json(DIALOGS_HISTORY_FILE)
            edit(cid, mid, f"📊 *СТАТИСТИКА*\n\n👥 Пользователей: {len(users)}\n💎 Премиум: {prem}\n💬 Диалогов: {total_dialogs}\n📁 Сохранено диалогов: {sum(len(v) for v in hist.values())}", {"inline_keyboard": [[{"text": "⬅️ НАЗАД", "callback_data": "admin"}]]})
        
        # Ответ на callback
        try:
            urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/answerCallbackQuery", data=json.dumps({"callback_query_id": cb["id"]}).encode(), headers={"Content-Type": "application/json"}), timeout=5)
        except:
            pass

# ========== ЗАПУСК ==========
last_update_id = 0
print("✅ БОТ ДЛЯ АНОНИМНОГО ОБЩЕНИЯ ЗАПУЩЕН!")
print(f"🤖 @{bot_name}")
print("📌 Отправь /start в Telegram")

while True:
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/getUpdates?offset={last_update_id + 1}&timeout=30"
        updates = json.loads(urllib.request.urlopen(url, timeout=35).read())
        
        for update in updates.get("result", []):
            last_update_id = update["update_id"]
            process(update)
        
        time.sleep(1)
    except Exception as e:
        print(f"Ошибка: {e}")
        time.sleep(5)