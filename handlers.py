import logging
from datetime import datetime, date, time as dtime
from telegram import Update, BotCommand, BotCommandScopeChat, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
import database as db
import keyboards as kb
from config import REGISTER_NAME
import pytz as _pytz

log = logging.getLogger(__name__)
_MSK = _pytz.timezone("Europe/Moscow")
TODAY = lambda: datetime.now(_MSK).date().isoformat()
NOWT = lambda: datetime.now(_MSK).strftime("%H:%M")

async def set_user_commands(bot, telegram_id, role):
    try:
        if role == "director":
            cmds = [
                BotCommand("otchet", "Полный отчёт"), BotCommand("kpi", "KPI флористов"),
                BotCommand("prodazhi", "Продажи"), BotCommand("vitrina", "Букеты"),
                BotCommand("nastroyki", "Настройки")
            ]
        else:
            cmds = [
                BotCommand("otkryt", "Открыть смену"), BotCommand("buket", "Добавить букет"),
                BotCommand("vitrina", "Мои букеты"), BotCommand("moy_kpi", "Мой KPI"),
                BotCommand("vitrina_bukety", "Отчёт витрины"), BotCommand("vitrina_komp", "Отчёт комп."),
                BotCommand("flowwow_otchet", "Отчёт Flowwow"), BotCommand("pravila", "Правила и штрафы")
            ]
        await bot.set_my_commands(cmds, scope=BotCommandScopeChat(chat_id=telegram_id))
    except Exception as e:
        log.error(f"set_my_commands: {e}")

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if user:
        await set_user_commands(ctx.bot, update.effective_user.id, user["role"])
        await update.message.reply_text(f"Привет, {user['name']}!")
        return ConversationHandler.END
    await update.message.reply_text("Добро пожаловать! Как тебя зовут?")
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

async def send_task(bot, florist, task_type, scheduled_time):
    today = TODAY()
    if db.get_pending_task(florist["id"], task_type, today): return
    if not db.has_shift(florist["id"], today): return
    task_id = db.create_task(task_type, florist["id"], today, scheduled_time)
    texts = {
        "vitrina_bouquets": "14:00 — Витрина готовых букетов!\nПришли фото:",
        "vitrina_compositions": "18:00 — Витрина готовых композиций!\nПришли фото:",
        "flowwow": "15:00 — Пора обновить Flowwow!\nПришли фото:",
    }
    try:
        msg = await bot.send_message(florist["telegram_id"], texts.get(task_type, "Задача"), reply_markup=kb.task_response_kb(task_id, task_type))
        db.update_task(task_id, florist_msg_id=msg.message_id)
    except Exception as e:
        log.error(e)

async def shift_prompt(bot, florists):
    for f in florists:
        if not db.has_shift(f["id"], TODAY()):
            try:
                await bot.send_message(f["telegram_id"], "Доброе утро! Пора открывать смену:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"🟢 Начать смену — {f['name']}", callback_data=f"shift:{f['id']}")]]))
            except Exception as e:
                log.error(e)

async def cmd_pravila(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user or user["role"] != "florist": return
    ym = datetime.now(_MSK).strftime("%Y-%m")
    lates = db.get_month_lates(user["id"], ym)
    max_light = int(db.get_setting("kpi_late_light_max", "5"))
    max_medium = int(db.get_setting("kpi_late_medium_max", "3"))
    max_heavy = int(db.get_setting("kpi_late_heavy_max", "2"))
    l, m, h, n = lates.get("light", 0), lates.get("medium", 0), lates.get("heavy", 0), lates.get("no_show", 0)
    
    lines = ["Правила опозданий:", f"Лёгких: {l}/{max_light}", f"Средних: {m}/{max_medium}", f"Серьёзных: {h}/{max_heavy}"]
    await update.message.reply_text("\n".join(lines))

async def photo_handler(update, ctx): await update.message.reply_text("Фото получено.")
async def callback_handler(update, ctx): pass
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
