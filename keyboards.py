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

def task_florist_pick_kb(florists):
    """Выбор флориста, которому директор ставит разовую задачу."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(f["name"], callback_data=f"tflorist:{f['id']}")] for f in florists]
    )

def task_difficulty_kb():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🟢 Лёгкая", callback_data="tdiff:light"),
        InlineKeyboardButton("🟡 Обычная", callback_data="tdiff:normal"),
        InlineKeyboardButton("🔴 Сложная", callback_data="tdiff:hard"),
    ]])

def task_mandatory_kb():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔴 Да, день в день", callback_data="tmand:yes"),
        InlineKeyboardButton("Нет, гибко", callback_data="tmand:no"),
    ]])

def task_date_kb():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Сегодня", callback_data="tdate:today"),
        InlineKeyboardButton("Завтра", callback_data="tdate:tomorrow"),
    ]])

def custom_task_kb(task_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Сделано", callback_data=f"mtask_done:{task_id}")],
        [InlineKeyboardButton("❌ Не сделано", callback_data=f"mtask_no:{task_id}")],
        [InlineKeyboardButton("📅 Перенести на завтра", callback_data=f"mtask_move:{task_id}")],
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
            InlineKeyboardButton("✅ В студии", callback_data=f"bsell:studio:{bouquet_id}"),
            InlineKeyboardButton("🏷 Со скидкой", callback_data=f"bsell:discount:{bouquet_id}"),
        ],
        [
            InlineKeyboardButton("🛍 Flowwow", callback_data=f"bsell:flowwow:{bouquet_id}"),
        ],
        [InlineKeyboardButton("🗑 Разобрать", callback_data=f"bdisassemble:{bouquet_id}")],
    ])

def bouquet_check_kb(bouquet_id):
    """Полные кнопки на день 4 и день 6."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ В студии", callback_data=f"bsell:studio:{bouquet_id}"),
            InlineKeyboardButton("🏷 Со скидкой", callback_data=f"bsell:discount:{bouquet_id}"),
        ],
        [
            InlineKeyboardButton("🛍 Flowwow", callback_data=f"bsell:flowwow:{bouquet_id}"),
        ],
        [InlineKeyboardButton("👍 Проверен — всё хорошо", callback_data=f"bcheck:{bouquet_id}")],
        [InlineKeyboardButton("🗑 Разобрать", callback_data=f"bdisassemble:{bouquet_id}")],
    ])

def composition_rating_kb(composition_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("👎 Плохо", callback_data=f"crate:0:{composition_id}"),
        InlineKeyboardButton("👌 Норм", callback_data=f"crate:1:{composition_id}"),
        InlineKeyboardButton("⭐ Отлично", callback_data=f"crate:2:{composition_id}"),
    ]])

def composition_status_kb(composition_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ В студии", callback_data=f"csell:studio:{composition_id}"),
            InlineKeyboardButton("🏷 Со скидкой", callback_data=f"csell:discount:{composition_id}"),
        ],
        [
            InlineKeyboardButton("🛍 Flowwow", callback_data=f"csell:flowwow:{composition_id}"),
        ],
        [InlineKeyboardButton("🗑 Разобрать", callback_data=f"cdisassemble:{composition_id}")],
    ])

def composition_check_kb(composition_id):
    """Кнопки на день 4 — срок годности истёк, продать или разобрать."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ В студии", callback_data=f"csell:studio:{composition_id}"),
            InlineKeyboardButton("🏷 Со скидкой", callback_data=f"csell:discount:{composition_id}"),
        ],
        [
            InlineKeyboardButton("🛍 Flowwow", callback_data=f"csell:flowwow:{composition_id}"),
        ],
        [InlineKeyboardButton("🔴 Разобрать", callback_data=f"cdisassemble:{composition_id}")],
    ])

def settings_main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🕐 Время напоминаний", callback_data="settings:times")],
        [InlineKeyboardButton("📏 Пороги KPI", callback_data="settings:kpi")],
        [InlineKeyboardButton("🌹 Срок годности букета", callback_data="settings:bouquet")],
        [InlineKeyboardButton("💼 Накладные расходы %", callback_data="setval:overhead_pct")],
        [InlineKeyboardButton("⏱ Время ожидания ответа", callback_data="setval:timeout_minutes")],
        [InlineKeyboardButton("👤 Флористы и график", callback_data="settings:florists")],
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
        [InlineKeyboardButton("Витрина — макс Норм", callback_data="setval:kpi_vitrina_max_norm")],
        [InlineKeyboardButton("Flowwow — макс пропусков", callback_data="setval:kpi_flowwow_max_skips")],
        [InlineKeyboardButton("Flowwow — макс Норм", callback_data="setval:kpi_flowwow_max_norm")],
        [InlineKeyboardButton("Букеты — макс Плохо", callback_data="setval:kpi_bouquet_max_bad")],
        [InlineKeyboardButton("« Назад", callback_data="settings:main")],
    ])

def settings_bouquet_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("День проверки (сейчас 4)", callback_data="setval:bouquet_check_days")],
        [InlineKeyboardButton("День разбора (сейчас 6)", callback_data="setval:bouquet_max_days")],
        [InlineKeyboardButton("« Назад", callback_data="settings:main")],
    ])

SETTING_LABELS = {
    "vitrina_bouquets_time":     "время витрины букетов (напр. 14:00)",
    "vitrina_compositions_time": "время витрины композиций (напр. 18:00)",
    "flowwow_time":              "время Flowwow (напр. 15:00)",
    "shift_start_time":          "время начала смены (напр. 10:00)",
    "timeout_minutes":           "минуты ожидания до уведомления (напр. 30)",
    "kpi_vitrina_max_skips":     "макс пропусков витрины (напр. 4)",
    "kpi_vitrina_max_norm":      "макс Норм витрины (напр. 7)",
    "kpi_flowwow_max_skips":     "макс пропусков Flowwow (напр. 1)",
    "kpi_flowwow_max_norm":      "макс Норм Flowwow (напр. 4)",
    "kpi_bouquet_max_bad":       "макс Плохо по букетам (напр. 2)",
    "bouquet_check_days":        "день проверки букета (напр. 4)",
    "bouquet_max_days":          "день разбора букета (напр. 6)",
    "overhead_pct":              "процент накладных расходов (напр. 25)",
}


def settings_florists_kb(florists):
    buttons = []
    for f in florists:
        status = "Активна" if f["active"] else "Неактивна"
        buttons.append([InlineKeyboardButton(
            f"{'✅' if f['active'] else '❌'} {f['name']} — {status}",
            callback_data=f"florist_toggle:{f['id']}"
        )])
        buttons.append([InlineKeyboardButton(
            f"📅 График {f['name']}",
            callback_data=f"florist_schedule:{f['id']}"
        )])
    buttons.append([InlineKeyboardButton("« Назад", callback_data="settings:main")])
    return InlineKeyboardMarkup(buttons)

def flowwow_copy_kb(task_id):
    """Кнопки для отчёта копирования букетов на Flowwow."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Сделано", callback_data=f"fcopy:done:{task_id}"),
        InlineKeyboardButton("⏰ Через 15 мин", callback_data=f"fcopy:later:{task_id}"),
        InlineKeyboardButton("❌ Нет", callback_data=f"fcopy:no:{task_id}"),
    ]])


def vitrina_shortage_kb(florist_id):
    """Кнопки когда букетов меньше 6."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Собрала", callback_data=f"shortage:done:{florist_id}"),
        InlineKeyboardButton("⏰ Через час", callback_data=f"shortage:hour:{florist_id}"),
        InlineKeyboardButton("❌ Не из чего", callback_data=f"shortage:nostock:{florist_id}"),
    ]])


def director_shortage_kb(florist_id):
    """Кнопки директору по причине нехватки."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("👍 Понятно", callback_data=f"shortage_dir:ok:{florist_id}"),
        InlineKeyboardButton("👎 Замечание", callback_data=f"shortage_dir:warn:{florist_id}"),
    ]])


def close_shift_kb(florist_id):
    """Кнопка закрытия смены."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔒 Закрыть смену", callback_data=f"close_shift:{florist_id}")
    ]])
