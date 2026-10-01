import telebot
from telebot import types
import sqlite3
import os
import time
import threading
import json
from datetime import datetime, timedelta
from flask import Flask


TOKEN = os.environ.get("BOT_TOKEN", "").strip()
DB_FILE = "dorm.db"


OWNER_ID = os.environ.get("OWNER_ID", "").strip()
ADMIN_IDS = [x.strip() for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()]


SECRET_CODE = "DEL202"


CATEGORIES = [
    "🍔 Еда", "🧴 Быт", "🔧 Инструменты", "📚 Учёба",
    "👕 Одежда", "🎮 Развлечения", "❓ Другое",
]


app = Flask(__name__)
bot = telebot.TeleBot(TOKEN)


# ========== БАЗА ==========


def db_init():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY, name TEXT, room TEXT, username TEXT, joined TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS admins (user_id TEXT PRIMARY KEY, name TEXT, added TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS banned (
        user_id TEXT PRIMARY KEY, name TEXT, reason TEXT, banned_by TEXT, banned_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS duty (id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT, user_name TEXT, date TEXT, done INTEGER DEFAULT 0)""")
    c.execute("""CREATE TABLE IF NOT EXISTS reminders (id INTEGER PRIMARY KEY AUTOINCREMENT,
        text TEXT, time TEXT, created_by TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS polls (id INTEGER PRIMARY KEY AUTOINCREMENT,
        question TEXT, options TEXT, votes TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS board (id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT, user_name TEXT, user_username TEXT, category TEXT, need TEXT,
        reward INTEGER DEFAULT 0, status TEXT DEFAULT 'open',
        responder_id TEXT, responder_name TEXT, responder_username TEXT, created TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS birthdays (
        user_id TEXT PRIMARY KEY, day INTEGER, month INTEGER, year INTEGER)""")
    c.execute("""CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT, user_name TEXT, username TEXT, item TEXT, description TEXT, created TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS bday_sent (
        key TEXT PRIMARY KEY)""")
    conn.commit()
    for stmt in [
        "ALTER TABLE users ADD COLUMN room TEXT",
        "ALTER TABLE users ADD COLUMN username TEXT",
        "ALTER TABLE board ADD COLUMN user_username TEXT",
        "ALTER TABLE board ADD COLUMN category TEXT",
        "ALTER TABLE board ADD COLUMN responder_username TEXT",
        "ALTER TABLE reminders ADD COLUMN created_by TEXT",
    ]:
        try: c.execute(stmt)
        except Exception: pass
    conn.commit(); conn.close()


# ========== ХЕЛПЕРЫ ==========


def is_owner(user_id):
    return bool(OWNER_ID) and str(user_id) == OWNER_ID


def is_admin(user_id):
    uid = str(user_id)
    if is_owner(uid): return True
    if uid in ADMIN_IDS: return True
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("SELECT 1 FROM admins WHERE user_id=?", (uid,))
    row = c.fetchone(); conn.close()
    return row is not None


def is_banned(user_id):
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("SELECT reason FROM banned WHERE user_id=?", (str(user_id),))
    row = c.fetchone(); conn.close()
    return row


def get_user(uid):
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("SELECT name, room FROM users WHERE user_id=?", (str(uid),))
    row = c.fetchone(); conn.close()
    return row


def is_registered(uid):
    row = get_user(uid)
    return bool(row and row[0] and row[1] and row[1].strip())


def main_kb(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("📅 Дежурства", "➕ Объявление")
    markup.add("📋 Мои объявления", "🗳 Голосование")
    markup.add("⏰ Напоминания", "🎂 Дни рождения")
    markup.add("🔧 Что у кого есть")
    if is_admin(user_id):
        markup.add("👥 Участники", "🚫 Чёрный список")
        markup.add("📢 Сообщение")
    return markup


def check_ban(message):
    ban = is_banned(message.from_user.id)
    if ban:
        reason = ban[0] or "без причины"
        bot.send_message(message.chat.id,
            "🚫 Ты забанен в этом боте.\nПричина: " + reason)
        return True
    return False


# ========== СТАРТ + РЕГИСТРАЦИЯ ==========


@bot.message_handler(commands=['start', 'menu'])
def start(message):
    if check_ban(message): return
    uid = str(message.from_user.id)
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, name, joined) VALUES (?, ?, ?)",
              (uid, message.from_user.first_name or "Аноним",
               datetime.now().strftime("%d.%m.%Y %H:%M")))
    c.execute("UPDATE users SET username=? WHERE user_id=?",
              (message.from_user.username or "", uid))
    conn.commit(); conn.close()


    if is_registered(uid):
        row = get_user(uid)
        bot.send_message(message.chat.id,
            "🏠 Привет, " + row[0] + "!\nКомната: " + row[1] + "\n\nЖми кнопки внизу 👇",
            reply_markup=main_kb(message.from_user.id))
        return


    msg = bot.send_message(message.chat.id,
        "👋 Привет! Давай познакомимся.\n\nШаг 1 из 2. Напиши своё имя:",
        reply_markup=types.ForceReply())
    bot.register_next_step_handler(msg, reg_name)


def reg_name(message):
    if check_ban(message): return
    name = (message.text or "").strip()
    if not name or len(name) > 50:
        bot.reply_to(message, "❌ Имя от 1 до 50 символов. Начни заново: /start")
        return
    msg = bot.send_message(message.chat.id,
        "Приятно познакомиться, " + name + "!\n\nШаг 2 из 2. Напиши номер комнаты:",
        reply_markup=types.ForceReply())
    bot.register_next_step_handler(msg, reg_room, name)


def reg_room(message, name):
    if check_ban(message): return
    room = (message.text or "").strip()
    if not room or len(room) > 20:
        bot.reply_to(message, "❌ Комната от 1 до 20 символов. Начни заново: /start")
        return
    uid = str(message.from_user.id)
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("UPDATE users SET name=?, room=?, username=? WHERE user_id=?",
              (name, room, message.from_user.username or "", uid))
    conn.commit(); conn.close()
    bot.send_message(message.chat.id,
        "✅ Готово!\n" + name + ", комната " + room + "\n\n"
        "💡 Совет: укажи свой день рождения — жми «🎂 Дни рождения» → «Указать мой ДР»\n\n"
        "Жми кнопки внизу 👇",
        reply_markup=main_kb(message.from_user.id))


# ========== RENAME ==========


@bot.message_handler(commands=['rename'])
def rename_cmd(message):
    if check_ban(message): return
    msg = bot.send_message(message.chat.id,
        "🔄 Перезапись данных.\n\nНапиши своё новое имя:",
        reply_markup=types.ForceReply())
    bot.register_next_step_handler(msg, rename_name)


def rename_name(message):
    if check_ban(message): return
    name = (message.text or "").strip()
    if not name or len(name) > 50:
        bot.reply_to(message, "❌ Имя от 1 до 50 символов. Начни заново: /rename")
        return
    msg = bot.send_message(message.chat.id, "Теперь напиши номер комнаты:",
        reply_markup=types.ForceReply())
    bot.register_next_step_handler(msg, rename_room, name)


def rename_room(message, name):
    if check_ban(message): return
    room = (message.text or "").strip()
    if not room or len(room) > 20:
        bot.reply_to(message, "❌ Комната от 1 до 20 символов. Начни заново: /rename")
        return
    uid = str(message.from_user.id)
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("UPDATE users SET name=?, room=?, username=? WHERE user_id=?",
              (name, room, message.from_user.username or "", uid))
    conn.commit(); conn.close()
    bot.send_message(message.chat.id,
        "✅ Обновлено!\n" + name + ", комната " + room,
        reply_markup=main_kb(message.from_user.id))


@bot.message_handler(commands=['help'])
def help_cmd(message):
    if check_ban(message): return
    text = ("Жми кнопки внизу 👇\n\n"
            "📝 /rename — сменить имя и комнату")
    if is_owner(message.from_user.id):
        text += ("\n\n👑 Владелец. Команды:\n"
                 "/users — все участники\n"
                 "/admins — управление админами\n"
                 "/banlist — чёрный список\n"
                 "/admin — стать админом (код)\n"
                 "/unadmin — снять с себя")
    elif is_admin(message.from_user.id):
        text += ("\n\n🔑 Админ. Команды:\n"
                 "/users — все участники\n"
                 "/banlist — чёрный список\n"
                 "/admin — стать админом (код)\n"
                 "/unadmin — снять с себя")
    bot.send_message(message.chat.id, text, reply_markup=main_kb(message.from_user.id))


# ========== АДМИН ==========


@bot.message_handler(commands=['admin'])
def admin_cmd(message):
    if check_ban(message): return
    if is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "✅ Ты уже админ.", reply_markup=main_kb(message.from_user.id))
        return
    msg = bot.send_message(message.chat.id, "🔑 Введи секретный код:", reply_markup=types.ForceReply())
    bot.register_next_step_handler(msg, admin_code_step)


def admin_code_step(message):
    if check_ban(message): return
    code = (message.text or "").strip()
    if code != SECRET_CODE:
        bot.reply_to(message, "❌ Неверный код."); return
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO admins (user_id, name, added) VALUES (?, ?, ?)",
              (str(message.from_user.id), message.from_user.first_name or "Админ",
               datetime.now().strftime("%d.%m.%Y %H:%M")))
    conn.commit(); conn.close()
    bot.reply_to(message, "✅ Ты теперь админ!", reply_markup=main_kb(message.from_user.id))


@bot.message_handler(commands=['unadmin'])
def unadmin_cmd(message):
    if check_ban(message): return
    if is_owner(message.from_user.id):
        bot.reply_to(message, "👑 Владельца нельзя снять."); return
    if not is_admin(message.from_user.id): return
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("DELETE FROM admins WHERE user_id=?", (str(message.from_user.id),))
    conn.commit(); conn.close()
    bot.reply_to(message, "Ты больше не админ.", reply_markup=main_kb(message.from_user.id))


@bot.message_handler(commands=['admins'])
def admins_list(message):
    if check_ban(message): return
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "❌ Только владелец."); return
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("SELECT user_id, name, added FROM admins ORDER BY added")
    rows = c.fetchall(); conn.close()
    text = "👑 Владелец: " + (OWNER_ID or "не задан") + "\n\n"
    if not rows:
        text += "🔑 Админов нет."
        bot.send_message(message.chat.id, text); return
    text += "🔑 Админы (" + str(len(rows)) + "):\n"
    for r in rows:
        text += "• " + r[1] + "\n"
    markup = types.InlineKeyboardMarkup(row_width=1)
    for r in rows:
        markup.add(types.InlineKeyboardButton("🗑 Удалить: " + r[1],
            callback_data="adm_del_" + r[0]))
    bot.send_message(message.chat.id, text, reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data.startswith("adm_del_"))
def adm_del(call):
    if not is_owner(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Только владелец.", show_alert=True); return
    target = call.data.split("_")[2]
    if target == OWNER_ID:
        bot.answer_callback_query(call.id, "Владельца нельзя удалить.", show_alert=True); return
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("SELECT name FROM admins WHERE user_id=?", (target,))
    row = c.fetchone()
    if not row:
        conn.close()
        bot.answer_callback_query(call.id, "Уже не админ.", show_alert=True); return
    name = row[0]
    c.execute("DELETE FROM admins WHERE user_id=?", (target,))
    conn.commit(); conn.close()
    bot.answer_callback_query(call.id, "✅ " + name + " больше не админ.", show_alert=True)
    try: bot.send_message(int(target), "🔓 С тебя снята админка владельцем.")
    except Exception: pass


# ========== СПИСОК УЧАСТНИКОВ ==========


def send_users_list(chat_id, uid):
    if not is_admin(uid):
        bot.send_message(chat_id, "❌ Только админ."); return
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("SELECT name, room, username FROM users WHERE room IS NOT NULL AND room != '' ORDER BY room, name")
    rows = c.fetchall()
    total = len(rows)
    conn.close()
    if not rows:
        bot.send_message(chat_id, "Пока никто не зарегистрирован."); return
    text = "👥 Участники (" + str(total) + "):\n\n"
    for i, r in enumerate(rows[:50]):
        line = str(i+1) + ". " + (r[0] or "Без имени") + " — комната " + (r[1] or "?")
        if r[2]:
            line += " (@" + r[2] + ")"
        text += line + "\n"
    if total > 50:
        text += "\n... и ещё " + str(total - 50) + "."
    bot.send_message(chat_id, text)


@bot.message_handler(commands=['users'])
def users_cmd(message):
    if check_ban(message): return
    send_users_list(message.chat.id, message.from_user.id)


@bot.message_handler(func=lambda m: m.text == "👥 Участники")
def users_btn(message):
    if check_ban(message): return
    send_users_list(message.chat.id, message.from_user.id)


# ========== БАН ==========


@bot.message_handler(commands=['ban'])
def ban_cmd(message):
    if check_ban(message): return
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "❌ Только админ."); return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 2:
        bot.reply_to(message, "Формат: /ban @юзернейм или имя [причина]"); return
    do_ban(message, parts[1], parts[2] if len(parts) > 2 else "без причины")


def do_ban(message, target_input, reason):
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    search_username = target_input.lstrip("@")
    c.execute("SELECT user_id, name, room, username FROM users WHERE LOWER(username)=LOWER(?)", (search_username,))
    rows = c.fetchall()
    if not rows:
        c.execute("SELECT user_id, name, room, username FROM users WHERE LOWER(name)=LOWER(?)", (target_input,))
        rows = c.fetchall()
    conn.close()
    if not rows:
        bot.reply_to(message, "❌ Не найден."); return
    if len(rows) == 1:
        target_id, target_name, _, _ = rows[0]
        _ban_user(message, target_id, target_name, reason); return
    text = "🔍 Найдено несколько (" + str(len(rows)) + "):\n\n"
    markup = types.InlineKeyboardMarkup(row_width=1)
    for r in rows:
        tid, tname, troom, tusername = r
        line = tname + " — комн. " + (troom or "?")
        if tusername: line += " (@" + tusername + ")"
        markup.add(types.InlineKeyboardButton("🚫 " + line, callback_data="ban_" + tid + "_" + reason[:25]))
        text += "• " + line + "\n"
    text += "\nЖми на нужного:"
    bot.reply_to(message, text, reply_markup=markup)


def _ban_user(message_or_call, target_id, target_name, reason):
    author_id = message_or_call.from_user.id
    author_name = message_or_call.from_user.first_name or "Админ"
    if is_owner(target_id):
        try: bot.send_message(author_id, "❌ Нельзя забанить владельца.")
        except Exception: pass
        return
    if not is_owner(author_id) and is_admin(target_id):
        try: bot.send_message(author_id, "❌ Только владелец может банить админов.")
        except Exception: pass
        return
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO banned (user_id, name, reason, banned_by, banned_at) VALUES (?, ?, ?, ?, ?)",
              (target_id, target_name, reason, author_name,
               datetime.now().strftime("%d.%m.%Y %H:%M")))
    conn.commit(); conn.close()
    try: bot.send_message(author_id, "🚫 " + target_name + " забанен.\nПричина: " + reason)
    except Exception: pass
    try: bot.send_message(int(target_id), "🚫 Тебя забанили в боте.\nПричина: " + reason)
    except Exception: pass


@bot.callback_query_handler(func=lambda c: c.data.startswith("ban_"))
def ban_from_callback(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Только админ.", show_alert=True); return
    parts = call.data.split("_", 2)
    if len(parts) < 3:
        bot.answer_callback_query(call.id, "Ошибка.", show_alert=True); return
    target_id = parts[1]; reason = parts[2]
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("SELECT name FROM users WHERE user_id=?", (target_id,))
    row = c.fetchone(); conn.close()
    target_name = row[0] if row else "?"
    _ban_user(call, target_id, target_name, reason)
    bot.answer_callback_query(call.id, "🚫 " + target_name + " забанен.", show_alert=True)


@bot.message_handler(commands=['unban'])
def unban_cmd(message):
    if check_ban(message): return
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "❌ Только админ."); return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "Формат: /unban @юзернейм или имя"); return
    target = parts[1].lstrip("@").strip()
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("SELECT user_id, name FROM banned WHERE LOWER(name)=LOWER(?) OR user_id=?", (target, target))
    row = c.fetchone()
    if not row:
        conn.close(); bot.reply_to(message, "❌ Не в бане."); return
    tid, name = row
    c.execute("DELETE FROM banned WHERE user_id=?", (tid,))
    conn.commit(); conn.close()
    bot.reply_to(message, "✅ " + name + " разбанен.")
    try: bot.send_message(int(tid), "🔓 Ты разбанен.")
    except Exception: pass


@bot.message_handler(commands=['banlist'])
def banlist_cmd(message):
    if check_ban(message): return
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "❌ Только админ."); return
    show_banlist(message.chat.id, message.from_user.id)


@bot.message_handler(func=lambda m: m.text == "🚫 Чёрный список")
def banlist_btn(message):
    if check_ban(message): return
    if not is_admin(message.from_user.id): return
    show_banlist(message.chat.id, message.from_user.id)


def show_banlist(chat_id, uid):
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("SELECT user_id, name, reason, banned_by, banned_at FROM banned ORDER BY banned_at DESC")
    rows = c.fetchall(); conn.close()
    if not rows:
        bot.send_message(chat_id, "🚫 Чёрный список пуст."); return
    text = "🚫 Чёрный список (" + str(len(rows)) + "):\n\n"
    markup = types.InlineKeyboardMarkup(row_width=1)
    for i, r in enumerate(rows):
        uid_banned = r[0]
        conn = sqlite3.connect(DB_FILE); c2 = conn.cursor()
        c2.execute("SELECT username FROM users WHERE user_id=?", (uid_banned,))
        urow = c2.fetchone(); conn.close()
        username = urow[0] if urow else ""
        line = str(i+1) + ". " + (r[1] or "?")
        if username: line += " (@" + username + ")"
        text += line + "\n"
        text += "   Причина: " + (r[2] or "без причины") + "\n"
        text += "   Забанил: " + (r[3] or "?") + " (" + (r[4] or "?") + ")\n"
        label = r[1] or "?"
        if username: label += " (@" + username + ")"
        markup.add(types.InlineKeyboardButton("🔓 Разбанить: " + label,
            callback_data="unban_" + uid_banned))
    bot.send_message(chat_id, text, reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data.startswith("unban_"))
def unban_cb(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Только админ.", show_alert=True); return
    target = call.data.split("_")[1]
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("SELECT name FROM banned WHERE user_id=?", (target,))
    row = c.fetchone()
    if not row:
        conn.close()
        bot.answer_callback_query(call.id, "Уже не в бане.", show_alert=True); return
    name = row[0]
    c.execute("DELETE FROM banned WHERE user_id=?", (target,))
    conn.commit(); conn.close()
    bot.answer_callback_query(call.id, "✅ " + name + " разбанен.", show_alert=True)
    try: bot.send_message(int(target), "🔓 Ты разбанен.")
    except Exception: pass


# ========== ДНИ РОЖДЕНИЯ ==========


@bot.message_handler(func=lambda m: m.text == "🎂 Дни рождения")
def menu_bday(message):
    if check_ban(message): return
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("🎂 Указать мой ДР", callback_data="bd_set"))
    markup.add(types.InlineKeyboardButton("📋 Все ДР", callback_data="bd_all"))
    markup.add(types.InlineKeyboardButton("⏳ Ближайшие", callback_data="bd_next"))
    bot.send_message(message.chat.id, "🎂 Дни рождения:", reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data == "bd_set")
def bd_set(call):
    if is_banned(call.from_user.id):
        bot.answer_callback_query(call.id, "🚫 Ты забанен.", show_alert=True); return
    msg = bot.send_message(call.message.chat.id,
        "📅 Напиши свою дату рождения в формате:\nДД.ММ.ГГГГ\n\nНапример: 15.03.2003",
        reply_markup=types.ForceReply())
    bot.register_next_step_handler(msg, bd_set_step, call.from_user.id)
    bot.answer_callback_query(call.id)


def bd_set_step(message, owner_id):
    if check_ban(message): return
    if message.from_user.id != owner_id: return
    raw = (message.text or "").strip()
    try:
        d = datetime.strptime(raw, "%d.%m.%Y")
    except ValueError:
        bot.reply_to(message, "❌ Формат: ДД.ММ.ГГГГ. Например: 15.03.2003\nПопробуй заново.")
        return
    uid = str(message.from_user.id)
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO birthdays (user_id, day, month, year) VALUES (?, ?, ?, ?)",
              (uid, d.day, d.month, d.year))
    conn.commit(); conn.close()
    bot.reply_to(message,
        "✅ Записал: " + d.strftime("%d.%m.%Y") + "\n\n"
        "Бот напомнит всем за 3 дня и в сам день 🎉")


@bot.callback_query_handler(func=lambda c: c.data == "bd_all")
def bd_all(call):
    if is_banned(call.from_user.id):
        bot.answer_callback_query(call.id, "🚫 Ты забанен.", show_alert=True); return
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("""SELECT b.day, b.month, b.year, u.name, u.room, u.username
                 FROM birthdays b JOIN users u ON b.user_id = u.user_id
                 ORDER BY b.month, b.day""")
    rows = c.fetchall(); conn.close()
    if not rows:
        bot.send_message(call.message.chat.id, "🎂 Никто ещё не указал ДР."); return
    text = "🎂 Дни рождения:\n\n"
    today = datetime.now()
    for r in rows:
        day, month, year, name, room, username = r
        age_str = ""
        if year:
            age = today.year - year
            # если ДР ещё не было в этом году — минус один
            if (today.month, today.day) < (month, day):
                age -= 1
            age_str = " (" + str(age) + ")"
        line = "• " + str(day).zfill(2) + "." + str(month).zfill(2) + " — " + name
        if room: line += ", комн. " + room
        if username: line += " (@" + username + ")"
        line += age_str
        text += line + "\n"
    bot.send_message(call.message.chat.id, text)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data == "bd_next")
def bd_next(call):
    if is_banned(call.from_user.id):
        bot.answer_callback_query(call.id, "🚫 Ты забанен.", show_alert=True); return
    today = datetime.now().date()
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("""SELECT b.day, b.month, b.year, u.name, u.room, u.username
                 FROM birthdays b JOIN users u ON b.user_id = u.user_id""")
    rows = c.fetchall(); conn.close()
    if not rows:
        bot.answer_callback_query(call.id, "Никто ещё не указал ДР.", show_alert=True); return


    upcoming = []
    for r in rows:
        day, month, year, name, room, username = r
        try:
            this_year = datetime(today.year, month, day).date()
        except ValueError:
            continue  # 29 февраля в невисокосный год
        if this_year < today:
            try:
                this_year = datetime(today.year + 1, month, day).date()
            except ValueError:
                continue
        days_left = (this_year - today).days
        upcoming.append((days_left, day, month, year, name, room, username))


    upcoming.sort()
    text = "⏳ Ближайшие ДР:\n\n"
    for item in upcoming[:10]:
        days_left, day, month, year, name, room, username = item
        line = "• " + str(day).zfill(2) + "." + str(month).zfill(2) + " — " + name
        if room: line += ", комн. " + room
        if username: line += " (@" + username + ")"
        if days_left == 0:
            line += " — 🎉 СЕГОДНЯ!"
        elif days_left == 1:
            line += " — завтра!"
        else:
            line += " — через " + str(days_left) + " дн."
        text += line + "\n"
    bot.send_message(call.message.chat.id, text)
    bot.answer_callback_query(call.id)


# ========== ЧТО У КОГО ЕСТЬ ==========


@bot.message_handler(func=lambda m: m.text == "🔧 Что у кого есть")
def menu_items(message):
    if check_ban(message): return
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("➕ Добавить вещь", callback_data="it_add"))
    markup.add(types.InlineKeyboardButton("📋 Общий список", callback_data="it_list"))
    markup.add(types.InlineKeyboardButton("🔍 Найти вещь", callback_data="it_find"))
    markup.add(types.InlineKeyboardButton("🗑 Удалить мою вещь", callback_data="it_del"))
    bot.send_message(message.chat.id, "🔧 Что у кого есть:", reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data == "it_add")
def it_add(call):
    if is_banned(call.from_user.id):
        bot.answer_callback_query(call.id, "🚫 Ты забанен.", show_alert=True); return
    msg = bot.send_message(call.message.chat.id,
        "🔧 Что у тебя есть?\nНапиши название вещи:\n\nНапример: дрель, пылесос, утюг",
        reply_markup=types.ForceReply())
    bot.register_next_step_handler(msg, it_add_name, call.from_user.id)
    bot.answer_callback_query(call.id)


def it_add_name(message, owner_id):
    if check_ban(message): return
    if message.from_user.id != owner_id: return
    item = (message.text or "").strip()
    if not item or len(item) > 100:
        bot.reply_to(message, "❌ Название от 1 до 100 символов."); return
    msg = bot.send_message(message.chat.id,
        "Добавь описание (или напиши «-», чтобы пропустить):\n\n"
        "Например: могу дать на время, лежит в комнате",
        reply_markup=types.ForceReply())
    bot.register_next_step_handler(msg, it_add_desc, owner_id, item)


def it_add_desc(message, owner_id, item):
    if check_ban(message): return
    if message.from_user.id != owner_id: return
    desc = (message.text or "").strip()
    if desc == "-":
        desc = ""
    if len(desc) > 200:
        bot.reply_to(message, "❌ Описание до 200 символов."); return
    u = get_user(message.from_user.id)
    name = u[0] if u else (message.from_user.first_name or "Аноним")
    username = message.from_user.username or ""
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("INSERT INTO items (user_id, user_name, username, item, description, created) VALUES (?, ?, ?, ?, ?, ?)",
              (str(message.from_user.id), name, username, item, desc,
               datetime.now().strftime("%d.%m.%Y %H:%M")))
    conn.commit(); conn.close()
    bot.reply_to(message, "✅ Добавил: " + item)


@bot.callback_query_handler(func=lambda c: c.data == "it_list")
def it_list(call):
    if is_banned(call.from_user.id):
        bot.answer_callback_query(call.id, "🚫 Ты забанен.", show_alert=True); return
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("SELECT user_name, username, item, description FROM items ORDER BY item, user_name")
    rows = c.fetchall(); conn.close()
    if not rows:
        bot.send_message(call.message.chat.id, "🔧 Пока никто ничего не добавил."); return
    text = "🔧 Что у кого есть:\n\n"
    current_item = None
    for r in rows:
        name, username, item, desc = r
        if item != current_item:
            current_item = item
            text += "• " + item + "\n"
        line = "   — " + name
        if username: line += " (@" + username + ")"
        if desc: line += " — " + desc
        text += line + "\n"
    bot.send_message(call.message.chat.id, text)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data == "it_find")
def it_find(call):
    if is_banned(call.from_user.id):
        bot.answer_callback_query(call.id, "🚫 Ты забанен.", show_alert=True); return
    msg = bot.send_message(call.message.chat.id,
        "🔍 Что ищем? Напиши название вещи:",
        reply_markup=types.ForceReply())
    bot.register_next_step_handler(msg, it_find_step, call.from_user.id)
    bot.answer_callback_query(call.id)


def it_find_step(message, owner_id):
    if check_ban(message): return
    if message.from_user.id != owner_id: return
    query = (message.text or "").strip()
    if not query:
        bot.reply_to(message, "❌ Пусто."); return
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("""SELECT user_name, username, item, description FROM items
                 WHERE LOWER(item) LIKE LOWER(?) ORDER BY user_name""",
              ("%" + query + "%",))
    rows = c.fetchall(); conn.close()
    if not rows:
        bot.reply_to(message, "❌ Ничего не найдено по запросу: " + query); return
    text = "🔍 Нашёл:\n\n"
    for r in rows:
        name, username, item, desc = r
        line = "• " + item + " — " + name
        if username: line += " (@" + username + ")"
        if desc: line += "\n   " + desc
        text += line + "\n"
    bot.reply_to(message, text)


@bot.callback_query_handler(func=lambda c: c.data == "it_del")
def it_del(call):
    if is_banned(call.from_user.id):
        bot.answer_callback_query(call.id, "🚫 Ты забанен.", show_alert=True); return
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("SELECT id, item FROM items WHERE user_id=?", (str(call.from_user.id),))
    rows = c.fetchall(); conn.close()
    if not rows:
        bot.answer_callback_query(call.id, "У тебя нет вещей в списке.", show_alert=True); return
    text = "🗑 Твои вещи:\n\n"
    markup = types.InlineKeyboardMarkup(row_width=1)
    for r in rows:
        text += "#" + str(r[0]) + " — " + r[1] + "\n"
        markup.add(types.InlineKeyboardButton("🗑 Удалить: " + r[1],
            callback_data="itdel_" + str(r[0])))
    bot.send_message(call.message.chat.id, text, reply_markup=markup)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("itdel_"))
def itdel_cb(call):
    if is_banned(call.from_user.id):
        bot.answer_callback_query(call.id, "🚫 Ты забанен.", show_alert=True); return
    iid = int(call.data.split("_")[1])
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("SELECT item, user_id FROM items WHERE id=?", (iid,))
    row = c.fetchone()
    if not row:
        conn.close()
        bot.answer_callback_query(call.id, "Уже удалено.", show_alert=True); return
    if row[1] != str(call.from_user.id):
        conn.close()
        bot.answer_callback_query(call.id, "❌ Только свою вещь.", show_alert=True); return
    c.execute("DELETE FROM items WHERE id=?", (iid,))
    conn.commit(); conn.close()
    bot.answer_callback_query(call.id, "✅ Удалено: " + row[0], show_alert=True)


# ========== ДЕЖУРСТВА ==========


@bot.message_handler(func=lambda m: m.text == "📅 Дежурства")
def menu_duty(message):
    if check_ban(message): return
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("Сегодня", callback_data="d_today"),
        types.InlineKeyboardButton("Все", callback_data="d_all"),
    )
    markup.add(types.InlineKeyboardButton("✅ Отметить своё", callback_data="d_done"))
    if is_admin(message.from_user.id):
        markup.add(types.InlineKeyboardButton("➕ Добавить (админ)", callback_data="d_add"))
    bot.send_message(message.chat.id, "📅 Дежурства:", reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data == "d_today")
def d_today(call):
    if is_banned(call.from_user.id):
        bot.answer_callback_query(call.id, "🚫 Ты забанен.", show_alert=True); return
    today = datetime.now().strftime("%d.%m.%Y")
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("SELECT user_name, done FROM duty WHERE date=?", (today,))
    rows = c.fetchall(); conn.close()
    if not rows:
        bot.answer_callback_query(call.id, "Сегодня никто не дежурит.", show_alert=True); return
    text = "📅 Сегодня:\n" + "\n".join(("✅ " if r[1] else "⏳ ") + r[0] for r in rows)
    bot.answer_callback_query(call.id, text[:200], show_alert=True)


@bot.callback_query_handler(func=lambda c: c.data == "d_all")
def d_all(call):
    if is_banned(call.from_user.id):
        bot.answer_callback_query(call.id, "🚫 Ты забанен.", show_alert=True); return
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("SELECT user_name, date, done FROM duty ORDER BY id DESC LIMIT 15")
    rows = c.fetchall(); conn.close()
    if not rows:
        bot.answer_callback_query(call.id, "Пусто.", show_alert=True); return
    text = "📋 Дежурства:\n" + "\n".join(("✅" if r[2] else "⏳") + " " + r[0] + " — " + r[1] for r in rows)
    bot.answer_callback_query(call.id, text[:200], show_alert=True)


@bot.callback_query_handler(func=lambda c: c.data == "d_done")
def d_done(call):
    if is_banned(call.from_user.id):
        bot.answer_callback_query(call.id, "🚫 Ты забанен.", show_alert=True); return
    today = datetime.now().strftime("%d.%m.%Y")
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("SELECT id FROM duty WHERE date=? AND done=0 AND user_id=?",
              (today, str(call.from_user.id)))
    row = c.fetchone()
    if not row:
        conn.close()
        bot.answer_callback_query(call.id, "❌ У тебя нет дежурства сегодня.", show_alert=True); return
    c.execute("UPDATE duty SET done=1 WHERE id=?", (row[0],))
    conn.commit(); conn.close()
    bot.answer_callback_query(call.id, "✅ Отмечено!", show_alert=True)


@bot.callback_query_handler(func=lambda c: c.data == "d_add")
def d_add(call):
    if is_banned(call.from_user.id):
        bot.answer_callback_query(call.id, "🚫 Ты забанен.", show_alert=True); return
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Только админ.", show_alert=True); return
    msg = bot.send_message(call.message.chat.id, "Напиши: @ник ДД.ММ.ГГГГ", reply_markup=types.ForceReply())
    bot.register_next_step_handler(msg, d_add_step, call.from_user.id)
    bot.answer_callback_query(call.id)


def d_add_step(message, owner_id):
    if check_ban(message): return
    if message.from_user.id != owner_id: return
    parts = (message.text or "").split()
    if len(parts) < 2:
        bot.reply_to(message, "❌ Формат: @ник ДД.ММ.ГГГГ"); return
    target = parts[0].lstrip("@"); date_raw = parts[1]
    try:
        datetime.strptime(date_raw, "%d.%m.%Y")
    except ValueError:
        bot.reply_to(message, "❌ Дата в формате ДД.ММ.ГГГГ"); return
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("INSERT INTO duty (user_id, user_name, date) VALUES (?, ?, ?)", (target, target, date_raw))
    conn.commit(); conn.close()
    bot.reply_to(message, "✅ Дежурство: " + target + " — " + date_raw)


# ========== ОБЪЯВЛЕНИЕ ==========


@bot.message_handler(func=lambda m: m.text == "➕ Объявление")
def new_board_add(message):
    if check_ban(message): return
    if not is_registered(message.from_user.id):
        bot.send_message(message.chat.id, "Сначала зарегистрируйся: /start"); return
    markup = types.InlineKeyboardMarkup(row_width=2)
    for cat in CATEGORIES:
        markup.add(types.InlineKeyboardButton(cat, callback_data="bcat_" + cat))
    bot.send_message(message.chat.id, "Шаг 1 из 3. Выбери категорию:", reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data.startswith("bcat_"))
def b_cat_chosen(call):
    if is_banned(call.from_user.id):
        bot.answer_callback_query(call.id, "🚫 Ты забанен.", show_alert=True); return
    category = call.data[5:]
    bot.answer_callback_query(call.id, "Категория: " + category)
    msg = bot.send_message(call.message.chat.id,
        "Категория: " + category + "\n\nШаг 2 из 3. Что тебе нужно? Напиши:",
        reply_markup=types.ForceReply())
    bot.register_next_step_handler(msg, b_add_need, call.from_user.id, category)


def b_add_need(message, owner_id, category):
    if check_ban(message): return
    if message.from_user.id != owner_id: return
    need = (message.text or "").strip()
    if not need:
        bot.reply_to(message, "❌ Пусто. Жми «➕ Объявление» заново."); return
    if len(need) > 200:
        bot.reply_to(message, "❌ Слишком длинно, до 200 символов."); return
    msg = bot.send_message(message.chat.id,
        "Шаг 3 из 3. Сколько готов дать за это?\nНапиши число (0 — без вознаграждения):",
        reply_markup=types.ForceReply())
    bot.register_next_step_handler(msg, b_add_reward, owner_id, category, need)


def b_add_reward(message, owner_id, category, need):
    if check_ban(message): return
    if message.from_user.id != owner_id: return
    raw = (message.text or "").strip()
    try:
        reward = int(raw)
    except ValueError:
        bot.reply_to(message, "❌ Нужно число. Начни заново: «➕ Объявление»."); return
    if reward < 0:
        bot.reply_to(message, "❌ Не может быть отрицательным."); return


    u = get_user(message.from_user.id)
    reg_name_ = (u[0] if u else (message.from_user.first_name or "Аноним"))
    room = (u[1] if u else "")
    author_username = message.from_user.username or ""


    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("""INSERT INTO board (user_id, user_name, user_username, category, need, reward, created)
                 VALUES (?, ?, ?, ?, ?, ?, ?)""",
              (str(message.from_user.id), reg_name_, author_username,
               category, need, reward, datetime.now().strftime("%d.%m.%Y %H:%M")))
    bid = c.lastrowid
    conn.commit()
    c.execute("SELECT user_id FROM users")
    uids = [r[0] for r in c.fetchall()]
    conn.close()


    text_ok = "📋 Объявление #" + str(bid) + " создано и разослано!\n" + category + " " + need
    if reward > 0: text_ok += "\n💰 Награда: " + str(reward)
    else: text_ok += "\n💬 Без вознаграждения"
    bot.reply_to(message, text_ok)


    btext = "📋 Новое объявление #" + str(bid) + "\n\n"
    btext += category + " — " + need + "\n"
    if reward > 0: btext += "💰 Награда: " + str(reward) + "\n"
    else: btext += "💬 Без вознаграждения\n"
    btext += "👤 " + reg_name_
    if room: btext += ", комн. " + room
    if author_username: btext += " (@" + author_username + ")"


    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🙋 Откликнуться", callback_data="b_respond_" + str(bid)))


    for uid in uids:
        if uid == str(message.from_user.id): continue
        if is_banned(uid): continue
        try: bot.send_message(int(uid), btext, reply_markup=markup)
        except Exception: pass


@bot.callback_query_handler(func=lambda c: c.data.startswith("b_respond_"))
def b_respond(call):
    if is_banned(call.from_user.id):
        bot.answer_callback_query(call.id, "🚫 Ты забанен.", show_alert=True); return
    bid = int(call.data.split("_")[2])
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("SELECT user_id, user_name, user_username, category, need, reward, status FROM board WHERE id=?", (bid,))
    row = c.fetchone()
    if not row:
        conn.close(); bot.answer_callback_query(call.id, "❌ Не найдено.", show_alert=True); return
    author_id, author_name, author_username, category, need, reward, status = row
    if str(call.from_user.id) == author_id:
        conn.close(); bot.answer_callback_query(call.id, "Это твоё объявление.", show_alert=True); return
    if status != "open":
        conn.close(); bot.answer_callback_query(call.id, "Уже закрыто.", show_alert=True); return


    u = get_user(call.from_user.id)
    resp_name = (u[0] if u else (call.from_user.first_name or "Кто-то"))
    resp_room = (u[1] if u else "")
    resp_username = call.from_user.username or ""


    c.execute("""UPDATE board SET status='taken', responder_id=?, responder_name=?, responder_username=?
                 WHERE id=?""", (str(call.from_user.id), resp_name, resp_username, bid))
    conn.commit(); conn.close()


    bot.answer_callback_query(call.id, "✅ Отклик отправлен!", show_alert=True)


    contact = "@" + author_username if author_username else author_name
    t1 = "✅ Ты откликнулся на #" + str(bid) + "\n\n📋 " + category + " — " + need + "\n"
    if reward > 0: t1 += "💰 " + str(reward) + "\n"
    t1 += "\n👤 Автор: " + contact
    if not author_username: t1 += "\n⚠️ У автора нет username — он напишет сам."
    try: bot.send_message(int(call.from_user.id), t1)
    except Exception: pass


    t2 = "🎯 Отклик на #" + str(bid) + "\n\n📋 " + category + " — " + need + "\n"
    t2 += "👤 " + resp_name
    if resp_room: t2 += ", комн. " + resp_room
    if resp_username: t2 += " (@" + resp_username + ")"
    t2 += "\n\nНапиши ему в личку."
    try: bot.send_message(int(author_id), t2)
    except Exception: pass


# ========== МОИ ОБЪЯВЛЕНИЯ ==========


@bot.message_handler(func=lambda m: m.text == "📋 Мои объявления")
def my_boards(message):
    if check_ban(message): return
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("""SELECT id, category, need, reward, status, responder_name, responder_username
                 FROM board WHERE user_id=? ORDER BY id DESC LIMIT 20""",
              (str(message.from_user.id),))
    rows = c.fetchall(); conn.close()
    if not rows:
        bot.send_message(message.chat.id, "У тебя нет объявлений.",
                         reply_markup=main_kb(message.from_user.id)); return
    text = "📋 Мои объявления:\n\n"
    markup = types.InlineKeyboardMarkup(row_width=1)
    for r in rows:
        bid, cat, need, reward, status, resp_name, resp_username = r
        st = "🟢" if status == "open" else "🔴"
        line = "#" + str(bid) + " " + st + " " + (cat or "❓") + " " + need
        if reward: line += " 💰" + str(reward)
        text += line + "\n"
        if resp_name:
            contact = "@" + resp_username if resp_username else resp_name
            text += "   └ отклик: " + contact + "\n"
        if status == "open":
            markup.add(types.InlineKeyboardButton("✅ Закрыть #" + str(bid), callback_data="b_close_" + str(bid)))
    bot.send_message(message.chat.id, text, reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data.startswith("b_close_"))
def b_close(call):
    if is_banned(call.from_user.id):
        bot.answer_callback_query(call.id, "🚫 Ты забанен.", show_alert=True); return
    bid = int(call.data.split("_")[2])
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("SELECT user_id, responder_id, category, need FROM board WHERE id=?", (bid,))
    row = c.fetchone()
    if not row:
        conn.close(); bot.answer_callback_query(call.id, "❌ Не найдено.", show_alert=True); return
    author_id, responder_id, cat, need = row
    if author_id != str(call.from_user.id):
        conn.close(); bot.answer_callback_query(call.id, "❌ Только автор.", show_alert=True); return
    c.execute("UPDATE board SET status='done' WHERE id=?", (bid,))
    conn.commit(); conn.close()
    bot.answer_callback_query(call.id, "✅ Закрыто.", show_alert=True)
    if responder_id:
        try: bot.send_message(int(responder_id),
            "✅ Объявление #" + str(bid) + " закрыто автором.\n📋 " + (cat or "") + " " + need)
        except Exception: pass


# ========== ГОЛОСОВАНИЕ ==========


@bot.message_handler(func=lambda m: m.text == "🗳 Голосование")
def menu_poll(message):
    if check_ban(message): return
    msg = bot.send_message(message.chat.id, "Напиши: вопрос | вариант1 | вариант2", reply_markup=types.ForceReply())
    bot.register_next_step_handler(msg, poll_step, message.from_user.id)


def poll_step(message, owner_id):
    if check_ban(message): return
    if message.from_user.id != owner_id: return
    parts = (message.text or "").split("|")
    if len(parts) < 3:
        bot.reply_to(message, "❌ Нужно минимум 2 варианта через |"); return
    question = parts[0].strip(); options = [x.strip() for x in parts[1:]][:10]
    votes = {str(i): [] for i in range(len(options))}
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("INSERT INTO polls (question, options, votes) VALUES (?, ?, ?)",
              (question, json.dumps(options), json.dumps(votes)))
    pid = c.lastrowid
    conn.commit(); conn.close()
    show_poll(message.chat.id, pid)


def show_poll(chat_id, pid):
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("SELECT question, options, votes FROM polls WHERE id=?", (pid,))
    row = c.fetchone(); conn.close()
    if not row: return
    q, opts, votes = row[0], json.loads(row[1]), json.loads(row[2])
    markup = types.InlineKeyboardMarkup(row_width=1)
    for i, o in enumerate(opts):
        markup.add(types.InlineKeyboardButton(o + " (" + str(len(votes.get(str(i), []))) + ")",
            callback_data="vote_" + str(pid) + "_" + str(i)))
    bot.send_message(chat_id, "🗳 " + q, reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data.startswith("vote_"))
def vote(call):
    if is_banned(call.from_user.id):
        bot.answer_callback_query(call.id, "🚫 Ты забанен.", show_alert=True); return
    p = call.data.split("_"); pid = int(p[1]); idx = p[2]; uid = str(call.from_user.id)
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("SELECT options, votes FROM polls WHERE id=?", (pid,))
    row = c.fetchone()
    if not row:
        conn.close(); bot.answer_callback_query(call.id, "Не найдено"); return
    opts, votes = json.loads(row[0]), json.loads(row[1])
    for k in votes:
        if uid in votes[k]: votes[k].remove(uid)
    votes.setdefault(idx, []).append(uid)
    c.execute("UPDATE polls SET votes=? WHERE id=?", (json.dumps(votes), pid))
    conn.commit(); conn.close()
    markup = types.InlineKeyboardMarkup(row_width=1)
    for i, o in enumerate(opts):
        markup.add(types.InlineKeyboardButton(o + " (" + str(len(votes.get(str(i), []))) + ")",
            callback_data="vote_" + str(pid) + "_" + str(i)))
    try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)
    except Exception: pass
    bot.answer_callback_query(call.id, "✅ Голос учтён")


# ========== НАПОМИНАНИЯ ==========


@bot.message_handler(func=lambda m: m.text == "⏰ Напоминания")
def menu_rem(message):
    if check_ban(message): return
    markup = types.InlineKeyboardMarkup(row_width=1)
    if is_admin(message.from_user.id):
        markup.add(types.InlineKeyboardButton("➕ Создать (админ)", callback_data="r_add"))
    markup.add(types.InlineKeyboardButton("📋 Список", callback_data="r_list"))
    if is_admin(message.from_user.id):
        markup.add(types.InlineKeyboardButton("🗑 Удалить (админ)", callback_data="r_del"))
    bot.send_message(message.chat.id, "⏰ Напоминания:", reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data == "r_add")
def r_add(call):
    if is_banned(call.from_user.id):
        bot.answer_callback_query(call.id, "🚫 Ты забанен.", show_alert=True); return
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Только админ.", show_alert=True); return
    msg = bot.send_message(call.message.chat.id,
        "Напиши: ДД.ММ.ГГГГ ЧЧ:ММ текст\nНапример: 05.10.2026 15:30 выключить утюг",
        reply_markup=types.ForceReply())
    bot.register_next_step_handler(msg, r_add_step, call.from_user.id)
    bot.answer_callback_query(call.id)


def r_add_step(message, owner_id):
    if check_ban(message): return
    if message.from_user.id != owner_id: return
    parts = (message.text or "").split(maxsplit=3)
    if len(parts) < 3:
        bot.reply_to(message, "❌ Формат: ДД.ММ.ГГГГ ЧЧ:ММ текст"); return
    try:
        dt = datetime.strptime(parts[0] + " " + parts[1], "%d.%m.%Y %H:%M")
    except ValueError:
        bot.reply_to(message, "❌ Дата в формате ДД.ММ.ГГГГ ЧЧ:ММ"); return
    if dt <= datetime.now():
        bot.reply_to(message, "❌ Время прошло."); return
    text = " ".join(parts[2:])
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("INSERT INTO reminders (text, time, created_by) VALUES (?, ?, ?)",
              (text, dt.strftime("%Y-%m-%d %H:%M"), str(message.from_user.id)))
    conn.commit(); conn.close()
    bot.reply_to(message, "⏰ Напомню " + dt.strftime("%d.%m.%Y %H:%M") + ": " + text)


@bot.callback_query_handler(func=lambda c: c.data == "r_list")
def r_list(call):
    if is_banned(call.from_user.id):
        bot.answer_callback_query(call.id, "🚫 Ты забанен.", show_alert=True); return
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("SELECT id, text, time FROM reminders ORDER BY time")
    rows = c.fetchall(); conn.close()
    if not rows:
        bot.answer_callback_query(call.id, "Пусто.", show_alert=True); return
    text = "⏰ Список:\n" + "\n".join(str(r[0]) + ". " +
        datetime.strptime(r[2], "%Y-%m-%d %H:%M").strftime("%d.%m.%Y %H:%M") + " — " + r[1] for r in rows)
    bot.answer_callback_query(call.id, text[:200], show_alert=True)


@bot.callback_query_handler(func=lambda c: c.data == "r_del")
def r_del(call):
    if is_banned(call.from_user.id):
        bot.answer_callback_query(call.id, "🚫 Ты забанен.", show_alert=True); return
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Только админ.", show_alert=True); return
    msg = bot.send_message(call.message.chat.id, "Номер?", reply_markup=types.ForceReply())
    bot.register_next_step_handler(msg, r_del_step, call.from_user.id)
    bot.answer_callback_query(call.id)


def r_del_step(message, owner_id):
    if check_ban(message): return
    if message.from_user.id != owner_id: return
    try:
        rid = int((message.text or "").strip())
    except ValueError:
        bot.reply_to(message, "❌ Нужен номер."); return
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("DELETE FROM reminders WHERE id=?", (rid,))
    ok = c.rowcount > 0
    conn.commit(); conn.close()
    bot.reply_to(message, "✅ Удалено." if ok else "❌ Не найдено.")


# ========== СООБЩЕНИЕ ОТ АДМИНА ==========


@bot.message_handler(func=lambda m: m.text == "📢 Сообщение")
def ann_menu(message):
    if check_ban(message): return
    if not is_admin(message.from_user.id): return
    msg = bot.send_message(message.chat.id, "Текст сообщения для всех:", reply_markup=types.ForceReply())
    bot.register_next_step_handler(msg, ann_send)


def ann_send(message):
    if check_ban(message): return
    if not is_admin(message.from_user.id): return
    text = (message.text or "").strip()
    if not text:
        bot.reply_to(message, "❌ Пусто."); return
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    uids = [r[0] for r in c.fetchall()]
    conn.close()
    sent = 0
    for uid in uids:
        if is_banned(uid): continue
        try:
            m = bot.send_message(int(uid), "📢 Сообщение от администратора:\n\n" + text)
            sent += 1
            try: bot.pin_chat_message(int(uid), m.message_id, disable_notification=True)
            except Exception: pass
        except Exception: pass
    bot.reply_to(message, "✅ Отправлено: " + str(sent) + " из " + str(len(uids)))


# ========== ФОНОВЫЕ ==========


def reminder_worker():
    while True:
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            conn = sqlite3.connect(DB_FILE); c = conn.cursor()
            c.execute("SELECT id, text FROM reminders WHERE time=?", (now,))
            rows = c.fetchall()
            if rows:
                c.execute("SELECT user_id FROM users")
                uids = [r[0] for r in c.fetchall()]
                for rid, text in rows:
                    for uid in uids:
                        if is_banned(uid): continue
                        try:
                            m = bot.send_message(int(uid), "⏰ Напоминание: " + text)
                            try: bot.pin_chat_message(int(uid), m.message_id, disable_notification=True)
                            except Exception: pass
                        except Exception: pass
                    c.execute("DELETE FROM reminders WHERE id=?", (rid,))
                conn.commit()
            conn.close()
        except Exception as e:
            print("Reminder worker:", e)
        time.sleep(30)


def birthday_worker():
    while True:
        try:
            today = datetime.now().date()
            # проверяем в 10:00
            if datetime.now().strftime("%H:%M") == "10:00":
                conn = sqlite3.connect(DB_FILE); c = conn.cursor()
                c.execute("SELECT user_id FROM users")
                all_uids = [r[0] for r in c.fetchall()]
                c.execute("""SELECT b.user_id, b.day, b.month, b.year, u.name, u.room, u.username
                             FROM birthdays b JOIN users u ON b.user_id = u.user_id""")
                rows = c.fetchall()
                for r in rows:
                    uid_bd, day, month, year, name, room, username = r
                    # вычисляем ближайшее ДР
                    try:
                        this_year = datetime(today.year, month, day).date()
                    except ValueError:
                        continue
                    if this_year < today:
                        try:
                            this_year = datetime(today.year + 1, month, day).date()
                        except ValueError:
                            continue
                    days_left = (this_year - today).days


                    if days_left == 3:
                        key = "b3_" + str(this_year.year) + "_" + uid_bd
                        c.execute("SELECT 1 FROM bday_sent WHERE key=?", (key,))
                        if not c.fetchone():
                            text = ("🎂 Напоминание!\n\n"
                                    "Через 3 дня — день рождения у " + name)
                            if room: text += " (комн. " + room + ")"
                            if username: text += " (@" + username + ")"
                            text += "\n\nНе забудьте поздравить!"
                            for uid in all_uids:
                                if is_banned(uid): continue
                                try: bot.send_message(int(uid), text)
                                except Exception: pass
                            c.execute("INSERT INTO bday_sent (key) VALUES (?)", (key,))
                            conn.commit()


                    if days_left == 0:
                        key = "b0_" + str(this_year.year) + "_" + uid_bd
                        c.execute("SELECT 1 FROM bday_sent WHERE key=?", (key,))
                        if not c.fetchone():
                            text = ("🎉🎂 СЕГОДНЯ ДЕНЬ РОЖДЕНИЯ!\n\n"
                                    "У " + name)
                            if room: text += " (комн. " + room + ")"
                            if username: text += " (@" + username + ")"
                            text += "\n\nПоздравляем! 🎉"
                            for uid in all_uids:
                                if is_banned(uid): continue
                                try: bot.send_message(int(uid), text)
                                except Exception: pass
                            # отдельно имениннику
                            try: bot.send_message(int(uid_bd),
                                "🎉 С днём рождения, " + name + "! 🎂\n\nВсе соседи шлют поздравления!")
                            except Exception: pass
                            c.execute("INSERT INTO bday_sent (key) VALUES (?)", (key,))
                            conn.commit()
                conn.close()
        except Exception as e:
            print("Birthday worker:", e)
        time.sleep(60)


@app.route('/')
def health():
    return "Dorm bot"


def run_bot():
    bot.infinity_polling()


if __name__ == '__main__':
    db_init()
    threading.Thread(target=run_bot, daemon=True).start()
    threading.Thread(target=reminder_worker, daemon=True).start()
    threading.Thread(target=birthday_worker, daemon=True).start()
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)