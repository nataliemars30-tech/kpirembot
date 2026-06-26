import logging
from datetime import datetime, date, time as dtime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, BotCommandScopeChat
from telegram.ext import ContextTypes, ConversationHandler

import database as db
import keyboards as kb
from kpi import calc_kpi, format_kpi_for_florist, format_kpi_for_director, format_sales_report
from claude_ai import ask_claude
from config import REGISTER_NAME

log = logging.getLogger(__name__)
import pytz as _pytz
_MSK   = _pytz.timezone("Europe/Moscow")
TODAY  = lambda: datetime.now(_MSK).date().isoformat()
NOW    = lambda: datetime.now(_MSK).isoformat()
NOWT   = lambda: datetime.now(_MSK).strftime("%H:%M")

TASK_LABELS = {
    "vitrina_bouquets":     "Витрина готовых букетов",
    "vitrina_compositions": "Витрина готовых композиций",
    "flowwow":              "Flowwow",
}
RATING_LABELS = {0: "👎 Плохо", 1: "👌 Норм", 2: "⭐ Отлично"}

def is_director(tid): u = db.get_user(tid); return u and u["role"] == "director"
def is_florist(tid):  u = db.get_user(tid); return u and u["role"] == "florist"

async def send_to_director(bot, text, reply_markup=None, photo=None):
    d = db.get_director()
    if not d: return None
    if photo:
        return await bot.send_photo(d["telegram_id"], photo=photo, caption=text, reply_markup=reply_markup)
    return await bot.send_message(d["telegram_id"], text, reply_markup=reply_markup)

def get_late_type(receipt_time_str):
    try:
        t = datetime.strptime(receipt_time_str, "%H:%M").time()
    except:
        return "no_show"
    deadline = dtime(10, 3)
    if t <= deadline: return None
    elif t <= dtime(10, 15): return "light"
    elif t <= dtime(10, 30): return "medium"
    elif t <= dtime(11, 0): return "heavy"
    else: return "no_show"

LATE_LABELS = {
    "light":   "лёгкое (10:03–10:15)",
    "medium":  "опоздание (10:15–10:30)",
    "heavy":   "серьёзное (10:30–11:00)",
    "no_show": "критическое (после 11:00)",
}

async def set_user_commands(bot, telegram_id, role):
    try:
        if role == "director":
            cmds = [BotCommand("otchet", "Полный отчёт"), BotCommand("kpi", "KPI флористов"), BotCommand("prodazhi", "Продажи и прибыль"), BotCommand("vitrina", "Активные букеты"), BotCommand("nastroyki", "Настройки")]
        else:
            cmds = [BotCommand("otkryt", "Открыть смену"), BotCommand("buket", "Добавить букет"), BotCommand("vitrina", "Мои активные букеты"), BotCommand("moy_kpi", "Мой KPI за месяц"), BotCommand("vitrina_bukety", "Отчёт витрины букетов"), BotCommand("vitrina_komp", "Отчёт витрины композиций"), BotCommand("flowwow_otchet", "Отчёт Flowwow"), BotCommand("pravila", "Правила опозданий и мои штрафы")]
        await bot.set_my_commands(cmds, scope=BotCommandScopeChat(chat_id=telegram_id))
    except Exception as e:
        log.error(f"set_my_commands: {e}")

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if user:
        await set_user_commands(ctx.bot, update.effective_user.id, user["role"])
        role = "директор" if user["role"] == "director" else "флорист"
        await update.message.reply_text(f"Привет, {user['name']}! Ты зарегистрирована как {role}.")
        return ConversationHandler.END
    await update.message.reply_text("Добро пожаловать в REN Bot!\n\nКак тебя зовут?")
    return REGISTER_NAME

async def register_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    tid = update.effective_user.id
    director = db.get_director()
    role = "director" if not director else "florist"
    db.create_user(tid, name, role)
    await set_user_commands(ctx.bot, tid, role)
    await update.message.reply_text(f"{name}, ты зарегистрирована как {role}!")
    return ConversationHandler.END

async def shift_prompt(bot, florists):
    for f in florists:
        if not db.has_shift(f["id"], TODAY()):
            try:
                await bot.send_message(f["telegram_id"], "Доброе утро! Пора открывать смену:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"🟢 Начать смену — {f['name']}", callback_data=f"shift:{f['id']}")]]))
            except Exception as e:
                log.error(e)

async def send_task(bot, florist, task_type, scheduled_time):
    today = TODAY()
    if db.get_pending_task(florist["id"], task_type, today): return
    if not db.has_shift(florist["id"], today): return
    task_id = db.create_task(task_type, florist["id"], today, scheduled_time)
    texts = {"vitrina_bouquets": "14:00 — Витрина готовых букетов!\nПришли фото:", "vitrina_compositions": "18:00 — Витрина готовых композиций!\nПришли фото:", "flowwow": "15:00 — Пора обновить Flowwow!\nПришли фото или скрин:"}
    try:
        msg = await bot.send_message(florist["telegram_id"], texts.get(task_type, "Задача"), reply_markup=kb.task_response_kb(task_id, task_type))
        db.update_task(task_id, florist_msg_id=msg.message_id)
    except Exception as e:
        log.error(e)

async def cmd_pravila(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user or user["role"] != "florist": return
    ym = datetime.now(_MSK).strftime("%Y-%m")
    month = datetime.now(_MSK).strftime("%B %Y")
    lates = db.get_month_lates(user["id"], ym)
    max_light = int(db.get_setting("kpi_late_light_max", "5"))
    max_medium = int(db.get_setting("kpi_late_medium_max", "3"))
    max_heavy = int(db.get_setting("kpi_late_heavy_max", "2"))
    l, m, h, n = lates.get("light", 0), lates.get("medium", 0), lates.get("heavy", 0), lates.get("no_show", 0)
    lines = [f"Правила опозданий · {month}", "", f"Лёгких: {l}/{max_light}", f"Средних: {m}/{max_medium}", f"Серьёзных: {h}/{max_heavy}"]
    await update.message.reply_text("\n".join(lines))

async def callback_handler(update, ctx): pass
async def photo_handler(update, ctx): pass
async def text_handler(update, ctx): pass
async def cmd_otkryt(update, ctx): pass
async def cmd_bukет(update, ctx): pass
async def cmd_vitrina(update, ctx): pass
async def cmd_my_kpi(update, ctx): pass
async def cmd_report(update, ctx): pass
async def cmd_kpi(update, ctx): pass
async def cmd_sales(update, ctx): pass
async def cmd_settings(update, ctx): pass
async def cmd_reset_users(update, ctx): pass
async def cmd_migrate_db(update, ctx): pass
async def cmd_debug(update, ctx): pass
async def cmd_test_alert(update, ctx): pass
async def cmd_test_smena(update, ctx): pass
async def cmd_test_vitrina(update, ctx): pass
async def cmd_test_komp(update, ctx): pass
async def cmd_test_flowwow(update, ctx): pass
async def cmd_test_buket4(update, ctx): pass
async def cmd_test_buket6(update, ctx): pass
async def cmd_test_reminder(update, ctx): pass
async def cmd_manual_vitrina_bukety(update, ctx): pass
async def cmd_manual_vitrina_komp(update, ctx): pass
async def cmd_manual_flowwow(update, ctx): pass
