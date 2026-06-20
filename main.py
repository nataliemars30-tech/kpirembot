import asyncio
import logging
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, filters
)
from config import BOT_TOKEN, STATE_REGISTER_NAME
from database import init_db
from handlers import (
    start_command, register_name, my_kpi_command, vitrina_command,
    report_command, kpi_command, sales_command, settings_command,
    ask_command, bouquet_command, handle_photo, handle_text,
    main_callback
)
from scheduler import setup_scheduler

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


async def main():
    await init_db()
    logger.info("База данных инициализирована")

    app = Application.builder().token(BOT_TOKEN).build()

    # Registration conversation
    reg_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start_command)],
        states={
            STATE_REGISTER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_name)],
        },
        fallbacks=[CommandHandler("start", start_command)],
    )

    # Add handlers
    app.add_handler(reg_conv)
    app.add_handler(CommandHandler("мой_кпи", my_kpi_command))
    app.add_handler(CommandHandler("витрина", vitrina_command))
    app.add_handler(CommandHandler("отчет", report_command))
    app.add_handler(CommandHandler("kpi", kpi_command))
    app.add_handler(CommandHandler("продажи", sales_command))
    app.add_handler(CommandHandler("настройки", settings_command))
    app.add_handler(CommandHandler("спросить", ask_command))
    app.add_handler(CommandHandler("букет", bouquet_command))
    app.add_handler(CallbackQueryHandler(main_callback))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Scheduler
    setup_scheduler(app)

    logger.info("Бот запускается...")
    await app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
