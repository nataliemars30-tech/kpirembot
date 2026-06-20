import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DATABASE_PATH = os.environ.get("DATABASE_PATH", "ren_bot.db")
TIMEZONE = os.environ.get("TIMEZONE", "Europe/Moscow")

REGISTER_NAME = 0
BOUQUET_PHOTO = 1
BOUQUET_PRICE = 2
TASK_PHOTO = 3
TASK_REASON = 4
SETTINGS_CHOOSE = 5
SETTINGS_VALUE = 6
FLOWWOW_PHOTO = 7
