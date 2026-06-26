import logging
from telegram import Update, BotCommand, BotCommandScopeChat
from telegram.ext import ContextTypes, ConversationHandler
import database as db
from config import REGISTER_NAME

log = logging.getLogger(__name__)

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

async def photo_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Фото получено.")

async def cmd_pravila(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Правила и статистика штрафов...")

# Заглушки, чтобы избежать ImportError
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
