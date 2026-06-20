from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def task_response_kb(task_id, task_type):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Sdelano", callback_data=f"task_done:{task_id}:{task_type}")],
        [InlineKeyboardButton("Budet gotovo cherez chas", callback_data=f"task_hour:{task_id}:{task_type}")],
        [InlineKeyboardButton("Ne gotovo", callback_data=f"task_no:{task_id}:{task_type}")],
    ])

def task_after_hour_kb(task_id, task_type):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Gotovo!", callback_data=f"task_done:{task_id}:{task_type}")],
        [InlineKeyboardButton("Ne gotovo", callback_data=f"task_no:{task_id}:{task_type}")],
    ])

def rating_kb(task_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Ploho", callback_data=f"rate:0:{task_id}"),
        InlineKeyboardButton("Norm", callback_data=f"rate:1:{task_id}"),
        InlineKeyboardButton("Otlichno", callback_data=f"rate:2:{task_id}"),
    ]])

def bouquet_rating_kb(bouquet_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Ploho", callback_data=f"brate:0:{bouquet_id}"),
        InlineKeyboardButton("Norm", callback_data=f"brate:1:{bouquet_id}"),
        InlineKeyboardButton("Otlichno", callback_data=f"brate:2:{bouquet_id}"),
    ]])

def bouquet_status_kb(bouquet_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Prodan v studii", callback_data=f"bsell:studio:{bouquet_id}"),
            InlineKeyboardButton("Prodan na Flowwow", callback_data=f"bsell:flowwow:{bouquet_id}"),
        ],
        [InlineKeyboardButton("Razobrat", callback_data=f"bdisassemble:{bouquet_id}")],
    ])

def bouquet_check_kb(bouquet_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Prodan v studii", callback_data=f"bsell:studio:{bouquet_id}")],
        [InlineKeyboardButton("Prodan na Flowwow", callback_data=f"bsell:flowwow:{bouquet_id}")],
        [InlineKeyboardButton("Provereno - otlichno", callback_data=f"bcheck:{bouquet_id}")],
        [InlineKeyboardButton("Razobrat", callback_data=f"bdisassemble:{bouquet_id}")],
    ])

def shift_start_kb(florists):
    buttons = [
        [InlineKeyboardButton(f"Nachat smenu - {f['name']}", callback_data=f"shift:{f['id']}")]
        for f in florists
    ]
    return InlineKeyboardMarkup(buttons)

def settings_main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Vremya napominaniy", callback_data="settings:times")],
        [InlineKeyboardButton("Porogi KPI", callback_data="settings:kpi")],
        [InlineKeyboardButton("Srok buketov", callback_data="settings:bouquet")],
        [InlineKeyboardButton("Vremya ozhidaniya", callback_data="settings:timeout")],
        [InlineKeyboardButton("Upravlenie floristami", callback_data="settings:florists")],
    ])

def settings_times_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Vitrina buketov", callback_data="setval:vitrina_bouquets_time")],
        [InlineKeyboardButton("Vitrina kompozitsiy", callback_data="setval:vitrina_compositions_time")],
        [InlineKeyboardButton("Flowwow", callback_data="setval:flowwow_time")],
        [InlineKeyboardButton("Nachalo smeny", callback_data="setval:shift_start_time")],
        [InlineKeyboardButton("Nazad", callback_data="settings:main")],
    ])

def settings_kpi_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Vitrina - maks propuskov", callback_data="setval:kpi_vitrina_max_skips")],
        [InlineKeyboardButton("Vitrina - maks Norm", callback_data="setval:kpi_vitrina_max_norm")],
        [InlineKeyboardButton("Flowwow - maks propuskov", callback_data="setval:kpi_flowwow_max_skips")],
        [InlineKeyboardButton("Flowwow - maks Norm", callback_data="setval:kpi_flowwow_max_norm")],
        [InlineKeyboardButton("Bukety - maks Ploho", callback_data="setval:kpi_bouquet_max_bad")],
        [InlineKeyboardButton("Nazad", callback_data="settings:main")],
    ])

def settings_bouquet_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Den proverki (seychas 4)", callback_data="setval:bouquet_check_days")],
        [InlineKeyboardButton("Den razbora (seychas 6)", callback_data="setval:bouquet_max_days")],
        [InlineKeyboardButton("Nazad", callback_data="settings:main")],
    ])

SETTING_LABELS = {
    "vitrina_bouquets_time": "vremya vitriny buketov (napr. 14:00)",
    "vitrina_compositions_time": "vremya vitriny kompozitsiy (napr. 18:00)",
    "flowwow_time": "vremya Flowwow (napr. 15:00)",
    "shift_start_time": "vremya nachala smeny (napr. 10:00)",
    "timeout_minutes": "minuty ozhidaniya (napr. 30)",
    "kpi_vitrina_max_skips": "maks propuskov vitriny (napr. 4)",
    "kpi_vitrina_max_norm": "maks Norm vitriny (napr. 7)",
    "kpi_flowwow_max_skips": "maks propuskov Flowwow (napr. 1)",
    "kpi_flowwow_max_norm": "maks Norm Flowwow (napr. 4)",
    "kpi_bouquet_max_bad": "maks Ploho po buketam (napr. 2)",
    "bouquet_check_days": "den proverki buketa (napr. 4)",
    "bouquet_max_days": "den razbora buketa (napr. 6)",
}
