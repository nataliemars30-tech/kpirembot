import logging
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, filters
)
from config import BOT_TOKEN, REGISTER_NAME
from database import init_db
from handlers import (
    start, register_name, callback_handler,
    photo_handler, text_handler,
    cmd_otkryt, cmd_bukет, cmd_vitrina, cmd_my_kpi,
    cmd_kompoziciya, cmd_vitrina_kompozicii,
    cmd_report, cmd_kpi, cmd_sales, cmd_settings,
    cmd_manual_vitrina_bukety, cmd_manual_vitrina_komp, cmd_manual_flowwow,
    cmd_test_smena, cmd_test_vitrina, cmd_test_komp,
    cmd_test_flowwow, cmd_test_buket4, cmd_test_buket6, cmd_test_kompoziciya4, cmd_test_reminder,
    cmd_reset_users, cmd_migrate_db, cmd_debug, cmd_test_alert, cmd_pravila, cmd_reset_tasks,
    cmd_zakryt,
)
from scheduler import setup_scheduler

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", level=logging.INFO)

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    reg_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={REGISTER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_name)]},
        fallbacks=[], per_message=False,
    )
    app.add_handler(reg_conv)
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(CommandHandler("otkryt",         cmd_otkryt))
    app.add_handler(CommandHandler("zakryt",         cmd_zakryt))
    app.add_handler(CommandHandler("buket",          cmd_bukет))
    app.add_handler(CommandHandler("vitrina",        cmd_vitrina))
    app.add_handler(CommandHandler("kompoziciya",    cmd_kompoziciya))
    app.add_handler(CommandHandler("kompozicii",     cmd_vitrina_kompozicii))
    app.add_handler(CommandHandler("moy_kpi",        cmd_my_kpi))
    app.add_handler(CommandHandler("vitrina_bukety", cmd_manual_vitrina_bukety))
    app.add_handler(CommandHandler("vitrina_komp",   cmd_manual_vitrina_komp))
    app.add_handler(CommandHandler("flowwow_otchet", cmd_manual_flowwow))
    app.add_handler(CommandHandler("otchet",         cmd_report))
    app.add_handler(CommandHandler("kpi",            cmd_kpi))
    app.add_handler(CommandHandler("prodazhi",       cmd_sales))
    app.add_handler(CommandHandler("nastroyki",      cmd_settings))
    app.add_handler(CommandHandler("reset_users",    cmd_reset_users))
    app.add_handler(CommandHandler("migrate_db",     cmd_migrate_db))
    app.add_handler(CommandHandler("debug",          cmd_debug))
    app.add_handler(CommandHandler("test_alert",     cmd_test_alert))
    app.add_handler(CommandHandler("reset_tasks",    cmd_reset_tasks))
    app.add_handler(CommandHandler("pravila",        cmd_pravila))
    app.add_handler(CommandHandler("test_smena",     cmd_test_smena))
    app.add_handler(CommandHandler("test_vitrina",   cmd_test_vitrina))
    app.add_handler(CommandHandler("test_komp",      cmd_test_komp))
    app.add_handler(CommandHandler("test_flowwow",   cmd_test_flowwow))
    app.add_handler(CommandHandler("test_buket4",    cmd_test_buket4))
    app.add_handler(CommandHandler("test_buket6",    cmd_test_buket6))
    app.add_handler(CommandHandler("test_komp4",     cmd_test_kompoziciya4))
    app.add_handler(CommandHandler("test_reminder",  cmd_test_reminder))
    app.add_handler(MessageHandler(filters.PHOTO,    photo_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    # Меню команд для флористов
    from telegram import BotCommand, BotCommandScopeChat
    async def set_commands(app):
        florist_commands = [
            BotCommand("otkryt",      "Открыть смену"),
            BotCommand("zakryt",      "Закрыть смену"),
            BotCommand("buket",       "Добавить букет"),
            BotCommand("vitrina",     "Активные букеты"),
            BotCommand("kompoziciya", "Добавить композицию"),
            BotCommand("kompozicii", "Активные композиции"),
            BotCommand("moy_kpi",     "Мой KPI"),
            BotCommand("pravila",     "Правила"),
        ]
        import database as db
        for f in db.get_florists():
            try:
                await app.bot.set_my_commands(
                    florist_commands,
                    scope=BotCommandScopeChat(chat_id=f["telegram_id"]))
            except Exception:
                pass
    app.post_init = set_commands

    setup_scheduler(app)
    print("REN Bot zapushen!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
