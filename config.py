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
FLOWWOW_PHOTO = 7import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
DIRECTOR_ID = int(os.getenv("DIRECTOR_ID", "0"))
TIMEZONE = os.getenv("TIMEZONE", "Europe/Moscow")

# Default settings (overridden by DB)
DEFAULT_SETTINGS = {
    "vitrina_bouquets_time": "14:00",
    "vitrina_compositions_time": "18:00",
    "flowwow_time": "15:00",
    "shift_start_time": "10:00",
    "response_timeout_minutes": 30,
    "bouquet_check_days": 4,
    "bouquet_disassemble_days": 6,
    "flowwow_interval_days": 2,
    "kpi_vitrina_max_skips": 4,
    "kpi_vitrina_max_norm": 7,
    "kpi_flowwow_max_skips": 1,
    "kpi_flowwow_max_norm": 4,
    "kpi_bouquet_max_bad": 2,
}

# Task types
TASK_VITRINA_BOUQUETS = "vitrina_bouquets"
TASK_VITRINA_COMPOSITIONS = "vitrina_compositions"
TASK_FLOWWOW = "flowwow"

TASK_NAMES = {
    TASK_VITRINA_BOUQUETS: "🌸 Витрина готовых букетов",
    TASK_VITRINA_COMPOSITIONS: "🎋 Витрина готовых композиций",
    TASK_FLOWWOW: "🛍 Выкладка на Flowwow",
}

# Ratings
RATING_BAD = 0
RATING_OK = 1
RATING_EXCELLENT = 2

RATING_LABELS = {
    RATING_BAD: "👎 Плохо",
    RATING_OK: "👌 Норм",
    RATING_EXCELLENT: "⭐ Отлично",
}

RATING_SCORES = {
    RATING_BAD: 0,
    RATING_OK: 1,
    RATING_EXCELLENT: 2,
}

# Bouquet statuses
BOUQUET_ACTIVE = "active"
BOUQUET_SOLD_STUDIO = "sold_studio"
BOUQUET_SOLD_FLOWWOW = "sold_flowwow"
BOUQUET_DISASSEMBLED = "disassembled"
BOUQUET_CHECKED = "checked"

# Conversation states
(
    STATE_REGISTER_NAME,
    STATE_TASK_PHOTO,
    STATE_TASK_REASON,
    STATE_BOUQUET_PHOTO,
    STATE_BOUQUET_PRICE,
    STATE_SETTINGS_VALUE,
    STATE_DIRECTOR_QUESTION,
) = range(7)
