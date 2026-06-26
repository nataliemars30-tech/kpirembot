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
    name    = update.message.text.strip()
    tid     = update.effective_user.id
    director = db.get_director()
    role    = "director" if not director else "florist"
    db.create_user(tid, name, role)
    await set_user_commands(ctx.bot, tid, role)
    await update.message.reply_text(f"{name}, ты зарегистрирована как {role}!")
    return ConversationHandler.END

async def photo_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # Приоритетная логика фото
    user = db.get_user(update.effective_user.id)
    if not user: return
    
    # Здесь твоя логика обработки фото, оставь её без изменений, 
    # просто убедись, что она находится внутри файла.
    await update.message.reply_text("Фото получено.")

async def text_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # Здесь твоя логика текстовых сообщений
    pass

async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # Здесь твоя логика кнопок
    pass

# Команды
async def cmd_otkryt(update: Update, ctx: ContextTypes.DEFAULT_TYPE): pass
async def cmd_bukет(update: Update, ctx: ContextTypes.DEFAULT_TYPE): pass
async def cmd_vitrina(update: Update, ctx: ContextTypes.DEFAULT_TYPE): pass
async def cmd_my_kpi(update: Update, ctx: ContextTypes.DEFAULT_TYPE): pass
async def cmd_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE): pass
async def cmd_kpi(update: Update, ctx: ContextTypes.DEFAULT_TYPE): pass
async def cmd_sales(update: Update, ctx: ContextTypes.DEFAULT_TYPE): pass
async def cmd_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE): pass
async def cmd_reset_users(update: Update, ctx: ContextTypes.DEFAULT_TYPE): pass
async def cmd_migrate_db(update: Update, ctx: ContextTypes.DEFAULT_TYPE): pass
async def cmd_debug(update: Update, ctx: ContextTypes.DEFAULT_TYPE): pass
async def cmd_test_alert(update: Update, ctx: ContextTypes.DEFAULT_TYPE): pass
async def cmd_test_smena(update: Update, ctx: ContextTypes.DEFAULT_TYPE): pass
async def cmd_test_vitrina(update: Update, ctx: ContextTypes.DEFAULT_TYPE): pass
async def cmd_test_komp(update: Update, ctx: ContextTypes.DEFAULT_TYPE): pass
async def cmd_test_flowwow(update: Update, ctx: ContextTypes.DEFAULT_TYPE): pass
async def cmd_test_buket4(update: Update, ctx: ContextTypes.DEFAULT_TYPE): pass
async def cmd_test_buket6(update: Update, ctx: ContextTypes.DEFAULT_TYPE): pass
async def cmd_test_reminder(update: Update, ctx: ContextTypes.DEFAULT_TYPE): pass
async def cmd_manual_vitrina_bukety(update: Update, ctx: ContextTypes.DEFAULT_TYPE): pass
async def cmd_manual_vitrina_komp(update: Update, ctx: ContextTypes.DEFAULT_TYPE): pass
async def cmd_manual_flowwow(update: Update, ctx: ContextTypes.DEFAULT_TYPE): pass

async def cmd_pravila(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Единственная верная функция правил."""
    user = db.get_user(update.effective_user.id)
    if not user: return
    # ... сюда вставь логику из своей прошлой версии, которая считает штрафы ...
    await update.message.reply_text("Твои правила и статистика штрафов...")import logging
from datetime import datetime
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

TASK_LABELS = {"vitrina_bouquets": "Витрина готовых букетов", "vitrina_compositions": "Витрина готовых композиций", "flowwow": "Flowwow"}
RATING_LABELS = {0: "👎 Плохо", 1: "👌 Норм", 2: "⭐ Отлично"}

def is_director(tid): u = db.get_user(tid); return u and u["role"] == "director"

async def set_user_commands(bot, telegram_id, role):
    try:
        # Добавлена команда pravila в список FLORIST_COMMANDS
        cmds = [
            BotCommand("otchet", "Полный отчёт"), BotCommand("kpi", "KPI флористов"),
            BotCommand("prodazhi", "Продажи"), BotCommand("vitrina", "Букеты"),
            BotCommand("nastroyki", "Настройки")
        ] if role == "director" else [
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
    await update.message.reply_text("Как тебя зовут?")
    return REGISTER_NAME

# ... (остальные функции: register_name, shift_prompt, send_task) ...

async def photo_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user: return
    file_id = update.message.photo[-1].file_id

    # Приоритет состояний
    if ctx.user_data.get("waiting_receipt"):
        # ... логика обработки чека ...
        return
    elif ctx.user_data.get("pending_task_id"):
        # ... логика обработки фото задачи ...
        return
    elif ctx.user_data.get("adding_bouquet"):
        # ... логика букета ...
        return
    
    await update.message.reply_text("Пожалуйста, используй команды или кнопки для действий.")

async def cmd_pravila(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Единственная правильная версия функции."""
    user = db.get_user(update.effective_user.id)
    if not user or user["role"] != "florist": return
    # ... здесь вся логика из второй версии функции (со штрафами) ...
    await update.message.reply_text("Правила и статистика штрафов...")
