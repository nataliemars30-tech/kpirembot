from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def task_response_kb(task_id, task_type):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Сделано", callback_data=f"task_done:{task_id}:{task_type}")],
        [InlineKeyboardButton("⏳ Буду готово через час", callback_data=f"task_hour:{task_id}:{task_type}")],
        [InlineKeyboardButton("❌ Не готово", callback_data=f"task_no:{task_id}:{task_type}")],
    ])


def task_after_hour_kb(task_id, task_type):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Готово!", callback_data=f"task_done:{task_id}:{task_type}")],
        [InlineKeyboardButton("❌ Не готово", callback_data=f"task_no:{task_id}:{task_type}")],
    ])


def rating_kb(task_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("👎 Плохо", callback_data=f"rate:0:{task_id}"),
        InlineKeyboardButton("👌 Норм", callback_data=f"rate:1:{task_id}"),
        InlineKeyboardButton("⭐ Отлично", callback_data=f"rate:2:{task_id}"),
    ]])


def bouquet_rating_kb(bouquet_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("👎 Плохо", callback_data=f"brate:0:{bouquet_id}"),
        InlineKeyboardButton("👌 Норм", callback_data=f"brate:1:{bouquet_id}"),
        InlineKeyboardButton("⭐ Отлично", callback_data=f"brate:2:{bouquet_id}"),
    ]])


def bouquet_status_kb(bouquet_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Продан в студии", callback_data=f"bsell:studio:{bouquet_id}"),
            InlineKeyboardButton("🛍 Продан на Flowwow", callback_data=f"bsell:flowwow:{bouquet_id}"),
        ],
        [InlineKeyboardButton("🗑 Разобрать", callback_data=f"bdisassemble:{bouquet_id}")],
    ])


def bouquet_check_kb(bouquet_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Продан в студии", callback_data=f"bsell:studio:{bouquet_id}")],
        [InlineKeyboardButton("🛍 Продан на Flowwow", callback_data=f"bsell:flowwow:{bouquet_id}")],
        [InlineKeyboardButton("👍 Проверен — отлично", callback_data=f"bcheck:{bouquet_id}")],
        [InlineKeyboardButton("🗑 Разобрать", callback_data=f"bdisassemble:{bouquet_id}")],
    ])


def shift_start_kb(florists):
    buttons = [
        [InlineKeyboardButton(f"🟢 Начать смену — {f['name']}", callback_data=f"shift:{f['id']}")]
        for f in florists
    ]
    return InlineKeyboardMarkup(buttons)


def settings_main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🕐 Время напоминаний", callback_data="settings:times")],
        [InlineKeyboardButton("📏 Пороги KPI", callback_data="settings:kpi")],
        [InlineKeyboardButton("🌹 Срок годности букета", callback_data="settings:bouquet")],
        [InlineKeyboardButton("⏱ Время ожидания ответа", callback_data="settings:timeout")],
        [InlineKeyboardButton("👩‍🌾 Управление флористами", callback_data="settings:florists")],
        [InlineKeyboardButton("🔔 Вкл/выкл задачи", callback_data="settings:tasks")],
    ])


def settings_times_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌸 Витрина букетов", callback_data="setval:vitrina_bouquets_time")],
        [InlineKeyboardButton("🎋 Витрина композиций", callback_data="setval:vitrina_compositions_time")],
        [InlineKeyboardButton("🛍 Flowwow", callback_data="setval:flowwow_time")],
        [InlineKeyboardButton("🚀 Начало смены", callback_data="setval:shift_start_time")],
        [InlineKeyboardButton("« Назад", callback_data="settings:main")],
    ])


def settings_kpi_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Витрина — макс пропусков", callback_data="setval:kpi_vitrina_max_skips")],
        [InlineKeyboardButton("Витрина — макс «Норм»", callback_data="setval:kpi_vitrina_max_norm")],
        [InlineKeyboardButton("Flowwow — макс пропусков", callback_data="setval:kpi_flowwow_max_skips")],
        [InlineKeyboardButton("Flowwow — макс «Норм»", callback_data="setval:kpi_flowwow_max_norm")],
        [InlineKeyboardButton("Букеты — макс «Плохо»", callback_data="setval:kpi_bouquet_max_bad")],
        [InlineKeyboardButton("« Назад", callback_data="settings:main")],
    ])


def settings_bouquet_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("День проверки (сейчас 4)", callback_data="setval:bouquet_check_days")],
        [InlineKeyboardButton("День разбора (сейчас 6)", callback_data="setval:bouquet_max_days")],
        [InlineKeyboardButton("« Назад", callback_data="settings:main")],
    ])


SETTING_LABELS = {
    "vitrina_bouquets_time": "время витрины букетов (напр. 14:00)",
    "vitrina_compositions_time": "время витрины композиций (напр. 18:00)",
    "flowwow_time": "время Flowwow (напр. 15:00)",
    "shift_start_time": "время начала смены (напр. 10:00)",
    "timeout_minutes": "минуты ожидания до уведомления (напр. 30)",
    "kpi_vitrina_max_skips": "макс пропусков витрины для KPI (напр. 4)",
    "kpi_vitrina_max_norm": "макс «Норм» витрины для KPI (напр. 7)",
    "kpi_flowwow_max_skips": "макс пропусков Flowwow для KPI (напр. 1)",
    "kpi_flowwow_max_norm": "макс «Норм» Flowwow для KPI (напр. 4)",
    "kpi_bouquet_max_bad": "макс «Плохо» по букетам для KPI (напр. 2)",
    "bouquet_check_days": "день проверки букета (напр. 4)",
    "bouquet_max_days": "день обязательного разбора (напр. 6)",
    "timeout_minutes": "минут до уведомления о просрочке (напр. 30)",
}
