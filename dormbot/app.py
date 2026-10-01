import telebot
from telebot import types
import sqlite3
import os
import time
import threading
import json
from datetime import datetime
from flask import Flask


TOKEN = "8634465559:AAHQu27ZqHz0pRuC8UNF9e_GFlhGubZWN2A"
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


def db_init():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (user_id TEXT PRIMARY KEY, name TEXT, joined TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS admins (user_id TEXT PRIMARY KEY, name TEXT, added TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS duty (id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT, user_name TEXT, date TEXT, done INTEGER DEFAULT 0)""")
    c.execute("""CREATE TABLE IF NOT EXISTS reminders (id INTEGER PRIMARY KEY AUTOINCREMENT,
        text TEXT, time TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS polls (id INTEGER PRIMARY KEY AUTOINCREMENT,
        question TEXT, options TEXT, votes TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS board (id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT, user_name TEXT, user_username TEXT, category TEXT, need TEXT,
        reward INTEGER DEFAULT 0, status TEXT DEFAULT 'open',
        responder_id TEXT, responder_name TEXT, responder_username TEXT, created TEXT)""")
    conn.commit()
    try: c.execute("ALTER TABLE board ADD COLUMN user_username TEXT")
    except Exception: pass
    try: c.execute("ALTER TABLE board ADD COLUMN category TEXT")
    except Exception: pass
    try: c.execute("ALTER TABLE board ADD COLUMN responder_username TEXT")
    except Exception: pass
    conn.commit(); conn.close()


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


def main_kb(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("📅 Дежурства", "➕ Объявление")
    markup.add("📋 Мои объявления", "🗳 Голосование")
    markup.add("⏰ Напоминания")
    if is_admin(user_id):
        markup.add("📢 Сообщение")
    return markup


@bot.message_handler(commands=['start', 'menu'])
def start(message):
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, name, joined) VALUES (?, ?, ?)",
              (str(message.from_user.id), message.from_user.first_name or "Аноним",
               datetime.now().strftime("%d.%m.%Y %H:%M")))
    c.execute("UPDATE users SET name=? WHERE user_id=?",
              (message.from_user.first_name or "Аноним", str(message.from_user.id)))
    conn.commit(); conn.close()
    bot.send_message(message.chat.id,
        "🏠 Привет! Я бот общаги.\n\nЖми кнопки внизу 👇",
        reply_markup=main_kb(message.from_user.id))


@bot.message_handler(commands=['help'])
def help_cmd(message):
    text = "Жми кнопки внизу 👇"
    if is_owner(message.from_user.id):
        text += "\n\n👑 Ты владелец. Команды:\n/admin — стать админом (код)\n/admins — управление админами\n/unadmin — снять админку с себя"
    elif is_admin(message.from_user.id):
        text += "\n\n🔑 Команды:\n/admin — стать админом (код)\n/unadmin — снять с себя"
    bot.send_message(message.chat.id, text, reply_markup=main_kb(message.from_user.id))


@bot.message_handler(commands=['admin'])
def admin_cmd(message):
    if is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "✅ Ты уже админ.", reply_markup=main_kb(message.from_user.id))
        return
    msg = bot.send_message(message.chat.id, "🔑 Введи секретный код:", reply_markup=types.ForceReply())
    bot.register_next_step_handler(msg, admin_code_step)


def admin_code_step(message):
    code = message.text.strip()
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
    if is_owner(message.from_user.id):
        bot.reply_to(message, "👑 Владельца нельзя снять.")
        return
    if not is_admin(message.from_user.id):
        return
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("DELETE FROM admins WHERE user_id=?", (str(message.from_user.id),))
    conn.commit(); conn.close()
    bot.reply_to(message, "Ты больше не админ.", reply_markup=main_kb(message.from_user.id))


@bot.message_handler(commands=['admins'])
def admins_list(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "❌ Только владелец.")
        return
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("SELECT user_id, name, added FROM admins ORDER BY added")
    rows = c.fetchall(); conn.close()


    text = "👑 Владелец: " + (OWNER_ID or "не задан") + "\n\n"
    if not rows:
        text += "🔑 Админов нет."
        bot.send_message(message.chat.id, text)
        return


    text += "🔑 Админы (" + str(len(rows)) + "):\n"
    for r in rows:
        text += "• " + r[1] + " (ID: " + r[0] + ")\n"


    markup = types.InlineKeyboardMarkup(row_width=1)
    for r in rows:
        markup.add(types.InlineKeyboardButton(
            "🗑 Удалить: " + r[1] + " (" + r[0] + ")",
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
    try:
        bot.send_message(int(target), "🔓 С тебя снята админка владельцем.")
    except Exception:
        pass


@bot.callback_query_handler(func=lambda c: c.data == "back")
def back_cb(call):
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, "🏠 Меню:", reply_markup=main_kb(call.from_user.id))


# ========== ДЕЖУРСТВА ==========


@bot.message_handler(func=lambda m: m.text == "📅 Дежурства")
def menu_duty(message):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("Сегодня", callback_data="d_today"),
        types.InlineKeyboardButton("Все", callback_data="d_all"),
    )
    markup.add(types.InlineKeyboardButton("✅ Отметить своё", callback_data="d_done"))
    markup.add(types.InlineKeyboardButton("➕ Добавить", callback_data="d_add"))
    bot.send_message(message.chat.id, "📅 Дежурства:", reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data == "d_today")
def d_today(call):
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
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("SELECT user_name, date, done FROM duty ORDER BY id DESC LIMIT 15")
    rows = c.fetchall(); conn.close()
    if not rows:
        bot.answer_callback_query(call.id, "Пусто.", show_alert=True); return
    text = "📋 Дежурства:\n" + "\n".join(("✅" if r[2] else "⏳") + " " + r[0] + " — " + r[1] for r in rows)
    bot.answer_callback_query(call.id, text[:200], show_alert=True)


@bot.callback_query_handler(func=lambda c: c.data == "d_done")
def d_done(call):
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
    msg = bot.send_message(call.message.chat.id, "Напиши: @ник ДД.ММ.ГГГГ", reply_markup=types.ForceReply())
    bot.register_next_step_handler(msg, d_add_step, call.from_user.id)
    bot.answer_callback_query(call.id)


def d_add_step(message, owner_id):
    if message.from_user.id != owner_id: return
    parts = message.text.split()
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
    markup = types.InlineKeyboardMarkup(row_width=2)
    for cat in CATEGORIES:
        markup.add(types.InlineKeyboardButton(cat, callback_data="bcat_" + cat))
    bot.send_message(message.chat.id, "Шаг 1 из 3. Выбери категорию:", reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data.startswith("bcat_"))
def b_cat_chosen(call):
    category = call.data[5:]
    bot.answer_callback_query(call.id, "Категория: " + category)
    msg = bot.send_message(call.message.chat.id,
        "Категория: " + category + "\n\nШаг 2 из 3. Что тебе нужно? Напиши:",
        reply_markup=types.ForceReply())
    bot.register_next_step_handler(msg, b_add_need, call.from_user.id, category)


def b_add_need(message, owner_id, category):
    if message.from_user.id != owner_id: return
    need = message.text.strip()
    if not need:
        bot.reply_to(message, "❌ Пусто. Жми «➕ Объявление» заново."); return
    if len(need) > 200:
        bot.reply_to(message, "❌ Слишком длинно, до 200 символов."); return
    msg = bot.send_message(message.chat.id,
        "Шаг 3 из 3. Сколько готов дать за это?\nНапиши число (0 — без вознаграждения):",
        reply_markup=types.ForceReply())
    bot.register_next_step_handler(msg, b_add_reward, owner_id, category, need)


def b_add_reward(message, owner_id, category, need):
    if message.from_user.id != owner_id: return
    raw = message.text.strip()
    try:
        reward = int(raw)
    except ValueError:
        bot.reply_to(message, "❌ Нужно число. Начни заново: «➕ Объявление»."); return
    if reward < 0:
        bot.reply_to(message, "❌ Не может быть отрицательным."); return


    author_name = message.from_user.first_name or "Аноним"
    author_username = message.from_user.username or ""


    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("""INSERT INTO board (user_id, user_name, user_username, category, need, reward, created)
                 VALUES (?, ?, ?, ?, ?, ?, ?)""",
              (str(message.from_user.id), author_name, author_username,
               category, need, reward, datetime.now().strftime("%d.%m.%Y %H:%M")))
    bid = c.lastrowid
    conn.commit()
    c.execute("SELECT user_id FROM users")
    uids = [r[0] for r in c.fetchall()]
    conn.close()


    text_ok = "📋 Объявление #" + str(bid) + " создано и разослано!\n" + category + " " + need
    if reward > 0:
        text_ok += "\n💰 Награда: " + str(reward)
    else:
        text_ok += "\n💬 Без вознаграждения"
    bot.reply_to(message, text_ok)


    broadcast_text = "📋 Новое объявление #" + str(bid) + "\n\n"
    broadcast_text += category + " — " + need + "\n"
    if reward > 0:
        broadcast_text += "💰 Награда: " + str(reward) + "\n"
    else:
        broadcast_text += "💬 Без вознаграждения\n"
    broadcast_text += "👤 От: " + author_name
    if author_username:
        broadcast_text += " (@" + author_username + ")"


    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🙋 Откликнуться", callback_data="b_respond_" + str(bid)))


    for uid in uids:
        if uid == str(message.from_user.id):
            continue
        try:
            bot.send_message(int(uid), broadcast_text, reply_markup=markup)
        except Exception:
            pass


@bot.callback_query_handler(func=lambda c: c.data.startswith("b_respond_"))
def b_respond(call):
    bid = int(call.data.split("_")[2])
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("SELECT user_id, user_name, user_username, category, need, reward, status FROM board WHERE id=?", (bid,))
    row = c.fetchone()
    if not row:
        conn.close()
        bot.answer_callback_query(call.id, "❌ Объявление не найдено.", show_alert=True); return
    author_id, author_name, author_username, category, need, reward, status = row


    if str(call.from_user.id) == author_id:
        conn.close()
        bot.answer_callback_query(call.id, "Это твоё объявление.", show_alert=True); return
    if status != "open":
        conn.close()
        bot.answer_callback_query(call.id, "Уже закрыто.", show_alert=True); return


    resp_name = call.from_user.first_name or "Кто-то"
    resp_username = call.from_user.username or ""


    c.execute("""UPDATE board SET status='taken', responder_id=?, responder_name=?, responder_username=?
                 WHERE id=?""", (str(call.from_user.id), resp_name, resp_username, bid))
    conn.commit(); conn.close()


    bot.answer_callback_query(call.id, "✅ Отклик отправлен!", show_alert=True)


    contact = "@" + author_username if author_username else author_name
    text_to_resp = "✅ Ты откликнулся на #" + str(bid) + "\n\n"
    text_to_resp += "📋 " + category + " — " + need + "\n"
    if reward > 0:
        text_to_resp += "💰 " + str(reward) + "\n"
    text_to_resp += "\n👤 Автор: " + contact + "\n"
    if not author_username:
        text_to_resp += "⚠️ У автора нет username — он напишет тебе сам."
    try:
        bot.send_message(int(call.from_user.id), text_to_resp)
    except Exception:
        pass


    text_to_author = "🎯 Кто-то откликнулся на #" + str(bid) + "\n\n"
    text_to_author += "📋 " + category + " — " + need + "\n"
    text_to_author += "👤 " + resp_name
    if resp_username:
        text_to_author += " (@" + resp_username + ")"
    text_to_author += "\n\nНапиши ему в личку."
    try:
        bot.send_message(int(author_id), text_to_author)
    except Exception:
        pass


# ========== МОИ ОБЪЯВЛЕНИЯ ==========


@bot.message_handler(func=lambda m: m.text == "📋 Мои объявления")
def my_boards(message):
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
        if reward:
            line += " 💰" + str(reward)
        text += line + "\n"
        if resp_name:
            contact = "@" + resp_username if resp_username else resp_name
            text += "   └ отклик: " + contact + "\n"
        if status == "open":
            markup.add(types.InlineKeyboardButton("✅ Закрыть #" + str(bid), callback_data="b_close_" + str(bid)))
    bot.send_message(message.chat.id, text, reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data.startswith("b_close_"))
def b_close(call):
    bid = int(call.data.split("_")[2])
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("SELECT user_id, responder_id, category, need FROM board WHERE id=?", (bid,))
    row = c.fetchone()
    if not row:
        conn.close()
        bot.answer_callback_query(call.id, "❌ Не найдено.", show_alert=True); return
    author_id, responder_id, cat, need = row
    if author_id != str(call.from_user.id):
        conn.close()
        bot.answer_callback_query(call.id, "❌ Только автор может закрыть.", show_alert=True); return
    c.execute("UPDATE board SET status='done' WHERE id=?", (bid,))
    conn.commit(); conn.close()
    bot.answer_callback_query(call.id, "✅ Закрыто.", show_alert=True)
    if responder_id:
        try:
            bot.send_message(int(responder_id),
                "✅ Объявление #" + str(bid) + " закрыто автором.\n📋 " + (cat or "") + " " + need)
        except Exception:
            pass


# ========== ГОЛОСОВАНИЕ ==========


@bot.message_handler(func=lambda m: m.text == "🗳 Голосование")
def menu_poll(message):
    msg = bot.send_message(message.chat.id, "Напиши: вопрос | вариант1 | вариант2", reply_markup=types.ForceReply())
    bot.register_next_step_handler(msg, poll_step, message.from_user.id)


def poll_step(message, owner_id):
    if message.from_user.id != owner_id: return
    parts = message.text.split("|")
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
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)
    except Exception:
        pass
    bot.answer_callback_query(call.id, "✅ Голос учтён")


# ========== НАПОМИНАНИЯ ==========


@bot.message_handler(func=lambda m: m.text == "⏰ Напоминания")
def menu_rem(message):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("➕ Создать", callback_data="r_add"),
        types.InlineKeyboardButton("📋 Список", callback_data="r_list"),
        types.InlineKeyboardButton("🗑 Удалить", callback_data="r_del"),
    )
    bot.send_message(message.chat.id, "⏰ Напоминания:", reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data == "r_add")
def r_add(call):
    msg = bot.send_message(call.message.chat.id,
        "Напиши: ДД.ММ.ГГГГ ЧЧ:ММ текст\nНапример: 05.10.2026 15:30 выключить утюг",
        reply_markup=types.ForceReply())
    bot.register_next_step_handler(msg, r_add_step, call.from_user.id)
    bot.answer_callback_query(call.id)


def r_add_step(message, owner_id):
    if message.from_user.id != owner_id: return
    parts = message.text.split(maxsplit=3)
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
    c.execute("INSERT INTO reminders (text, time) VALUES (?, ?)",
              (text, dt.strftime("%Y-%m-%d %H:%M")))
    conn.commit(); conn.close()
    bot.reply_to(message, "⏰ Напомню " + dt.strftime("%d.%m.%Y %H:%M") + ": " + text)


@bot.callback_query_handler(func=lambda c: c.data == "r_list")
def r_list(call):
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
    msg = bot.send_message(call.message.chat.id, "Номер?", reply_markup=types.ForceReply())
    bot.register_next_step_handler(msg, r_del_step, call.from_user.id)
    bot.answer_callback_query(call.id)


def r_del_step(message, owner_id):
    if message.from_user.id != owner_id: return
    try:
        rid = int(message.text.strip())
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
    if not is_admin(message.from_user.id):
        return
    msg = bot.send_message(message.chat.id, "Текст сообщения для всех:", reply_markup=types.ForceReply())
    bot.register_next_step_handler(msg, ann_send)


def ann_send(message):
    if not is_admin(message.from_user.id):
        return
    text = message.text.strip()
    if not text:
        bot.reply_to(message, "❌ Пусто."); return
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    uids = [r[0] for r in c.fetchall()]
    conn.close()
    sent = 0
    for uid in uids:
        try:
            bot.send_message(int(uid), "📢 Сообщение от администратора:\n\n" + text)
            sent += 1
        except Exception:
            pass
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
                        try:
                            bot.send_message(int(uid), "⏰ Напоминание: " + text)
                        except Exception:
                            pass
                    c.execute("DELETE FROM reminders WHERE id=?", (rid,))
                conn.commit()
            conn.close()
        except Exception as e:
            print(e)
        time.sleep(30)


@app.route('/')
def health():
    return "Dorm bot"


def run_bot():
    bot.infinity_polling()


if __name__ == '__main__':
    db_init()
    threading.Thread(target=run_bot, daemon=True).start()
    threading.Thread(target=reminder_worker, daemon=True).start()
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)