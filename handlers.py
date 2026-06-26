import logging
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
