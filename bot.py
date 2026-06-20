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
    cmd_bukет, cmd_vitrina, cmd_my_kpi,
    cmd_report, cmd_kpi, cmd_sales, cmd_settings, cmd_status
)
from scheduler import setup_scheduler

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO
)

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    reg_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={REGISTER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_name)]},
        fallbacks=[],
        per_message=False,
    )
    app.add_handler(reg_conv)
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(CommandHandler("букет", cmd_bukет))
    app.add_handler(CommandHandler("витрина", cmd_vitrina))
    app.add_handler(CommandHandler("мой_кпи", cmd_my_kpi))
    app.add_handler(CommandHandler("отчет", cmd_report))
    app.add_handler(CommandHandler("kpi", cmd_kpi))
    app.add_handler(CommandHandler("продажи", cmd_sales))
    app.add_handler(CommandHandler("настройки", cmd_settings))
    app.add_handler(CommandHandler("статус", cmd_status))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    setup_scheduler(app)
    print("🌸
