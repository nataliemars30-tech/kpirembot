import logging
from datetime import datetime, date, time as dtime
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

def _time_diff_minutes(start_str, end_str):
    try:
        sh, sm = map(int, start_str.split(":"))
        eh, em = map(int, end_str.split(":"))
    except Exception:
        return None
    diff = (eh * 60 + em) - (sh * 60 + sm)
    if diff < 0:
        diff += 24 * 60
    return diff

TASK_LABELS = {
    "vitrina_bouquets":     "Витрина готовых букетов",
    "vitrina_compositions": "Витрина готовых композиций",
    "flowwow":              "Flowwow",
}
RATING_LABELS = {0: "🤮 Плохо", 1: "👌 Норм", 2: "❤️‍🔥 Отлично"}
TASK_DIFFICULTY_WEIGHTS = {"light": 1, "normal": 1, "hard": 1}  # когда-нибудь / обычная / срочная
TASK_DIFFICULTY_LABELS  = {"light": "🟢 Когда-нибудь", "normal": "🟡 Обычная", "hard": "❗️ Срочная"}

def is_director(tid): u = db.get_user(tid); return u and u["role"] == "director"
def is_florist(tid):  u = db.get_user(tid); return u and u["role"] == "florist"

async def send_to_director(bot, text, reply_markup=None, photo=None):
    d = db.get_director()
    if not d: return None
    if photo:
        return await bot.send_photo(d["telegram_id"], photo=photo, caption=text, reply_markup=reply_markup)
    return await bot.send_message(d["telegram_id"], text, reply_markup=reply_markup)

async def safe_edit(q, text):
    try:
        if q.message.photo:
            await q.message.edit_caption(caption=text, reply_markup=None)
        else:
            await q.message.edit_text(text, reply_markup=None)
    except Exception as e:
        log.error(e)
        try:
            await q.message.reply_text(text)
        except Exception as e2:
            log.error(e2)

def get_late_type(receipt_time_str):
    try:
        t = datetime.strptime(receipt_time_str, "%H:%M").time()
    except:
        return "no_show"
    deadline = dtime(10, 5)
    if t <= deadline:
        return None  # вовремя (до 10:05 включительно)
    elif t <= dtime(10, 15):
        return "light"
    elif t <= dtime(10, 30):
        return "medium"
    elif t <= dtime(11, 0):
        return "heavy"
    else:
        return "no_show"

LATE_LABELS = {
    "light":   "лёгкое (10:05–10:15)",
    "medium":  "опоздание (10:15–10:30)",
    "heavy":   "серьёзное (10:30–11:00)",
    "no_show": "критическое (после 11:00)",
}

DIRECTOR_COMMANDS = [
    BotCommand("zadacha",   "Поставить задачу"),
    BotCommand("zadachi",   "Все открытые задачи"),
    BotCommand("chasy",     "Часы и переработки"),
    BotCommand("kpi",       "KPI флористов"),
    BotCommand("otchet",    "Полный отчёт"),
    BotCommand("prodazhi",  "Продажи и прибыль"),
    BotCommand("vitrina",   "Активные букеты"),
    BotCommand("kompozicii","Активные композиции"),
    BotCommand("nastroyki", "Настройки"),
]

FLORIST_COMMANDS = [
    BotCommand("otkryt",          "Открыть смену"),
    BotCommand("zakryt",          "Закрыть смену"),
    BotCommand("buket",           "Добавить букет"),
    BotCommand("vitrina",         "Мои активные букеты"),
    BotCommand("kompoziciya",     "Добавить композицию"),
    BotCommand("kompozicii",      "Активные композиции"),
    BotCommand("zadacha",         "Поставить себе задачу"),
    BotCommand("zadachi",         "Мои открытые задачи"),
    BotCommand("moy_kpi",         "Мой KPI за месяц"),
    BotCommand("pravila",         "Правила опозданий и мои штрафы"),
]

async def set_user_commands(bot, telegram_id, role):
    try:
        cmds = DIRECTOR_COMMANDS if role == "director" else FLORIST_COMMANDS
        await bot.set_my_commands(cmds, scope=BotCommandScopeChat(chat_id=telegram_id))
    except Exception as e:
        log.error(f"set_my_commands: {e}")


# ── /start ────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if user:
        await set_user_commands(ctx.bot, update.effective_user.id, user["role"])
        role = "директор" if user["role"] == "director" else "флорист"
        await update.message.reply_text(
            f"Привет, {user['name']}! Ты зарегистрирована как {role}.\n\n"
            + (_director_help() if user["role"] == "director" else _florist_help()))
        return ConversationHandler.END
    await update.message.reply_text("Добро пожаловать в REN Bot!\n\nКак тебя зовут?")
    return REGISTER_NAME

async def register_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    name     = update.message.text.strip()
    tid      = update.effective_user.id
    director = db.get_director()
    role     = "director" if not director else "florist"
    db.create_user(tid, name, role)
    await set_user_commands(ctx.bot, tid, role)
    if role == "director":
        await update.message.reply_text(f"{name}, ты зарегистрирована как директор!\n\n" + _director_help())
    else:
        await update.message.reply_text(f"{name}, ты зарегистрирована как флорист!\n\n" + _florist_help())
        if director:
            await ctx.bot.send_message(director["telegram_id"], f"Новый флорист: {name}")
    return ConversationHandler.END

def _director_help():
    return "/zadacha /kpi /prodazhi /vitrina /nastroyki\nЛюбой текст — вопрос Claude"

def _florist_help():
    return "/otkryt — открыть смену\n/buket — новый букет\n/vitrina — мои букеты\n/moy_kpi — мой KPI"


# ── Shift ─────────────────────────────────────────────────

async def shift_prompt(bot, florists):
    for f in florists:
        if not db.has_shift(f["id"], TODAY()):
            try:
                await bot.send_message(
                    f["telegram_id"], "Доброе утро! Пора открывать смену:",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton(
                            f"☀️ Начать смену — {f['name']}",
                            callback_data=f"shift:{f['id']}")
                    ]]))
            except Exception as e:
                log.error(e)


async def send_task(bot, florist, task_type, scheduled_time, force=False):
    today = TODAY()
    if not force and db.get_pending_task(florist["id"], task_type, today): return
    if not db.has_shift(florist["id"], today): return
    task_id = db.create_task(task_type, florist["id"], today, scheduled_time)
    texts = {
        "vitrina_bouquets":     f"{scheduled_time} — Витрина готовых букетов!\nПришли фото:",
        "vitrina_compositions": f"{scheduled_time} — Витрина готовых композиций!\nПришли фото:",
        "flowwow":              f"{scheduled_time} — Пора обновить Flowwow!\nПришли скрин:",
    }
    try:
        msg = await bot.send_message(
            florist["telegram_id"], texts.get(task_type, "Задача"),
            reply_markup=kb.task_response_kb(task_id, task_type))
        db.update_task(task_id, florist_msg_id=msg.message_id)
    except Exception as e:
        log.error(e)


# ── Callbacks ──────────────────────────────────────────────

async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    await q.answer()
    data = q.data
    user = db.get_user(q.from_user.id)

    # Начало смены
    if data.startswith("shift:"):
        florist_id = int(data.split(":")[1])
        fu = db.get_user_by_id(florist_id)
        if not fu or fu["telegram_id"] != q.from_user.id: return
        if db.has_shift(florist_id, TODAY()):
            await q.message.edit_text("Смена уже начата сегодня.")
            return
        db.start_shift(florist_id, TODAY())
        await q.message.edit_text("Смена начата! Теперь пришли фото чека с терминала:")
        ctx.user_data["waiting_receipt"] = florist_id
        ctx.user_data["receipt_shift_date"] = TODAY()

    # Задача сделана
    elif data.startswith("task_done:"):
        _, task_id, task_type = data.split(":")
        task_id = int(task_id)
        task = db.get_task(task_id)
        if not task or task["status"] in ("done","rated","submitted"): return
        if task_type == "flowwow_copy":
            # Flowwow copy не требует фото — просто подтверждение
            db.update_task(task_id, status="submitted", submitted_at=NOW())
            await q.message.edit_text("✅ Отлично! Букеты скопированы на Flowwow.", reply_markup=None)
            await send_to_director(ctx.bot,
                f"✅ {db.get_user_by_id(task['assigned_to'])['name'] if db.get_user_by_id(task['assigned_to']) else '?'} скопировала букеты на Flowwow")
        else:
            db.update_task(task_id, status="waiting_photo")
            await q.message.edit_text("Отлично! Пришли фото.", reply_markup=None)
            ctx.user_data["pending_task_id"]   = task_id
            ctx.user_data["pending_task_type"] = task_type

    # Через час
    elif data.startswith("task_hour:"):
        _, task_id, task_type = data.split(":")
        task_id = int(task_id)
        task = db.get_task(task_id)
        if not task: return
        db.update_task(task_id, status="in_hour", in_hour_at=NOW())
        await q.message.edit_text("Хорошо! Напомню через час.")
        u = db.get_user_by_id(task["assigned_to"])
        label = TASK_LABELS.get(task_type, task_type)
        await send_to_director(ctx.bot,
            f"⏳ {u['name'] if u else '?'} нажала «Через час»\nЗадача: {label} ({task['scheduled_time']})")
        import asyncio
        async def remind():
            await asyncio.sleep(3600)
            t = db.get_task(task_id)
            if t and t["status"] == "in_hour":
                try:
                    await ctx.bot.send_message(q.from_user.id, "Час прошёл! Задача готова?",
                        reply_markup=kb.task_after_hour_kb(task_id, task_type))
                except: pass
        asyncio.create_task(remind())

    # Не готово
    elif data.startswith("task_no:"):
        _, task_id, task_type = data.split(":")
        db.update_task(int(task_id), status="no")
        await q.message.edit_text("Понятно. Напиши причину:")
        ctx.user_data["reason_task_id"] = int(task_id)

    # Оценка задачи
    elif data.startswith("rate:"):
        _, rating, task_id = data.split(":")
        rating, task_id = int(rating), int(task_id)
        if not is_director(q.from_user.id): return
        db.update_task(task_id, rating=rating, status="rated", rated_at=NOW())
        txt = f"\n\nОценка: {RATING_LABELS[rating]}"
        try:
            await q.message.edit_caption((q.message.caption or "") + txt, reply_markup=None)
        except:
            await q.message.edit_text((q.message.text or "") + txt, reply_markup=None)
        task = db.get_task(task_id)
        if task:
            fl = db.get_user_by_id(task["assigned_to"])
            if fl:
                label = TASK_LABELS.get(task["type"], task["type"])
                await ctx.bot.send_message(fl["telegram_id"],
                    f"Оценка за {label}: {RATING_LABELS[rating]}")

    # Оценка букета
    elif data.startswith("brate:"):
        _, rating, bouquet_id = data.split(":")
        rating, bouquet_id = int(rating), int(bouquet_id)
        if not is_director(q.from_user.id): return
        db.update_bouquet(bouquet_id, director_rating=rating)
        txt = f"\n\nОценка: {RATING_LABELS[rating]}"
        try:
            await q.message.edit_caption((q.message.caption or "") + txt, reply_markup=None)
        except:
            await q.message.edit_text((q.message.text or "") + txt, reply_markup=None)
        bouquet = db.get_bouquet(bouquet_id)
        if bouquet:
            fl = db.get_user_by_id(bouquet["florist_id"])
            if fl:
                await ctx.bot.send_message(fl["telegram_id"],
                    f"Директор оценил букет #{bouquet_id}: {RATING_LABELS[rating]}")

    # Продажа букета
    elif data.startswith("bsell:"):
        _, channel, bouquet_id = data.split(":")
        bouquet_id = int(bouquet_id)
        bouquet = db.get_bouquet(bouquet_id)
        if not bouquet or bouquet["status"] != "in_vitrina":
            await q.message.reply_text("Букет уже не в витрине.")
            return
        if channel in ("flowwow", "discount"):
            ctx.user_data["sell_bouquet_id"] = bouquet_id
            ctx.user_data["sell_channel"]    = channel
            if channel == "flowwow":
                await q.message.reply_text(f"Букет #{bouquet_id}\nВведи фактическую цену продажи на Flowwow:")
            else:
                await q.message.reply_text(f"Букет #{bouquet_id}\nВведи новую цену продажи (со скидкой):")
        else:
            sold_price = bouquet["price"]
            db.update_bouquet(bouquet_id, status="sold_studio", sale_channel="studio",
                              sold_at=NOW(), sold_price=sold_price)
            profit = sold_price - (bouquet.get("cost") or 0)
            await safe_edit(q,
                f"✅ Букет #{bouquet_id} продан в студии!\nЦена: {sold_price:,} ₽ · Прибыль: {profit:,} ₽".replace(",", " "))
            fl = db.get_user_by_id(bouquet["florist_id"])
            await send_to_director(ctx.bot,
                f"💰 Букет #{bouquet_id} продан в студии\n"
                f"Флорист: {fl['name'] if fl else '—'}\n"
                f"Цена: {sold_price:,} ₽ · Прибыль: ~{profit:,} ₽".replace(",", " "))

    # Разобрать букет
    elif data.startswith("bdisassemble:"):
        bouquet_id = int(data.split(":")[1])
        bouquet = db.get_bouquet(bouquet_id)
        if not bouquet: return
        db.update_bouquet(bouquet_id, status="disassembled", disassembled_at=NOW())
        await safe_edit(q, f"🗑 Букет #{bouquet_id} разобран — цветы пойдут в новый букет.")
        fl = db.get_user_by_id(bouquet["florist_id"])
        await send_to_director(ctx.bot,
            f"🗑 Букет #{bouquet_id} разобран\nФлорист: {fl['name'] if fl else '—'}")

    # Букет пересобран — обновить себестоимость и цену (срок годности не сбрасывается)
    elif data.startswith("breassemble:"):
        bouquet_id = int(data.split(":")[1])
        bouquet = db.get_bouquet(bouquet_id)
        if not bouquet: return
        ctx.user_data["reassemble_bouquet_id"] = bouquet_id
        await safe_edit(q,
            f"🔄 Букет #{bouquet_id} пересобран!\n"
            f"Введи через запятую новую себестоимость и цену продажи\n"
            f"Например: 2000, 3500\n\n"
            f"(Срок годности считается с даты первой сборки — {bouquet.get('created_at', '—')[:10]})")
        fl = db.get_user_by_id(bouquet["florist_id"])
        await send_to_director(ctx.bot,
            f"🔄 {fl['name'] if fl else '?'} пересобрала букет #{bouquet_id} — ждём новую цену")

    # Букет проверен
    elif data.startswith("bcheck:"):
        bouquet_id = int(data.split(":")[1])
        db.update_bouquet(bouquet_id, checked_at=NOW())
        await safe_edit(q, f"👍 Букет #{bouquet_id} проверен — всё хорошо, продаётся дальше!")
        bouquet = db.get_bouquet(bouquet_id)
        fl = db.get_user_by_id(bouquet["florist_id"]) if bouquet else None
        await send_to_director(ctx.bot,
            f"👍 Букет #{bouquet_id} проверен на {int(db.get_setting('bouquet_check_days','4'))}-й день\n"
            f"Флорист: {fl['name'] if fl else '—'} — продаётся дальше")

    # Оценка композиции
    elif data.startswith("crate:"):
        _, rating, composition_id = data.split(":")
        rating, composition_id = int(rating), int(composition_id)
        if not is_director(q.from_user.id): return
        db.update_composition(composition_id, director_rating=rating)
        txt = f"\n\nОценка: {RATING_LABELS[rating]}"
        try:
            await q.message.edit_caption((q.message.caption or "") + txt, reply_markup=None)
        except:
            await q.message.edit_text((q.message.text or "") + txt, reply_markup=None)
        composition = db.get_composition(composition_id)
        if composition:
            fl = db.get_user_by_id(composition["florist_id"])
            if fl:
                await ctx.bot.send_message(fl["telegram_id"],
                    f"Директор оценил композицию #{composition_id}: {RATING_LABELS[rating]}")

    # Продажа композиции
    elif data.startswith("csell:"):
        _, channel, composition_id = data.split(":")
        composition_id = int(composition_id)
        composition = db.get_composition(composition_id)
        if not composition or composition["status"] != "in_vitrina":
            await q.message.reply_text("Композиция уже не в витрине.")
            return
        if channel in ("flowwow", "discount"):
            ctx.user_data["sell_composition_id"] = composition_id
            ctx.user_data["sell_channel"]        = channel
            if channel == "flowwow":
                await q.message.reply_text(f"Композиция #{composition_id}\nВведи фактическую цену продажи на Flowwow:")
            else:
                await q.message.reply_text(f"Композиция #{composition_id}\nВведи новую цену продажи (со скидкой):")
        else:
            sold_price = composition["price"]
            db.update_composition(composition_id, status="sold_studio", sale_channel="studio",
                              sold_at=NOW(), sold_price=sold_price)
            profit = sold_price - (composition.get("cost") or 0)
            await safe_edit(q,
                f"✅ Композиция #{composition_id} продана в студии!\nЦена: {sold_price:,} ₽ · Прибыль: {profit:,} ₽".replace(",", " "))
            fl = db.get_user_by_id(composition["florist_id"])
            await send_to_director(ctx.bot,
                f"💰 Композиция #{composition_id} продана в студии\n"
                f"Флорист: {fl['name'] if fl else '—'}\n"
                f"Цена: {sold_price:,} ₽ · Прибыль: ~{profit:,} ₽".replace(",", " "))

    # Разобрать композицию
    elif data.startswith("cdisassemble:"):
        composition_id = int(data.split(":")[1])
        composition = db.get_composition(composition_id)
        if not composition: return
        db.update_composition(composition_id, status="disassembled", disassembled_at=NOW())
        await safe_edit(q, f"🗑 Композиция #{composition_id} разобрана — материалы пойдут в новую работу.")
        fl = db.get_user_by_id(composition["florist_id"])
        await send_to_director(ctx.bot,
            f"🗑 Композиция #{composition_id} разобрана\nФлорист: {fl['name'] if fl else '—'}")

    # Композиция пересобрана — обновить себестоимость и цену (срок годности не сбрасывается)
    elif data.startswith("creassemble:"):
        composition_id = int(data.split(":")[1])
        composition = db.get_composition(composition_id)
        if not composition: return
        ctx.user_data["reassemble_composition_id"] = composition_id
        await safe_edit(q,
            f"🔄 Композиция #{composition_id} пересобрана!\n"
            f"Введи через запятую новую себестоимость и цену продажи\n"
            f"Например: 1500, 2800\n\n"
            f"(Срок годности считается с даты первой сборки — {composition.get('created_at', '—')[:10]})")
        fl = db.get_user_by_id(composition["florist_id"])
        await send_to_director(ctx.bot,
            f"🔄 {fl['name'] if fl else '?'} пересобрала композицию #{composition_id} — ждём новую цену")

    # Разовая задача — директор выбрал флориста
    elif data.startswith("tflorist:"):
        if not is_director(q.from_user.id): return
        florist_id = int(data.split(":")[1])
        director   = db.get_user(q.from_user.id)
        fl         = db.get_user_by_id(florist_id)
        ctx.user_data["new_task_assigned_to"] = florist_id
        ctx.user_data["new_task_created_by"]  = director["id"] if director else None
        ctx.user_data["new_task_step"]        = "text"
        await q.message.edit_text(f"Опиши задачу для {fl['name'] if fl else 'флориста'}:", reply_markup=None)

    # Разовая задача — выбор сложности
    elif data.startswith("tdiff:"):
        level = data.split(":")[1]
        ctx.user_data["new_task_difficulty"] = level
        ctx.user_data["new_task_step"]       = "mandatory"
        await q.message.edit_text(
            f"{TASK_DIFFICULTY_LABELS.get(level, level)}\n\n"
            "Обязательно выполнить день в день?\n"
            "Если да — и задача не будет сделана, это минус в KPI, и она автоматически перенесётся на следующий день.",
            reply_markup=kb.task_mandatory_kb())

    # Разовая задача — обязательно или гибко
    elif data.startswith("tmand:"):
        mandatory = data.split(":")[1] == "yes"
        ctx.user_data["new_task_mandatory"] = mandatory
        ctx.user_data["new_task_step"]      = "photo_confirm"
        await q.message.edit_text(
            "Нужно ли фото-подтверждение когда задача выполнена?",
            reply_markup=kb.task_photo_confirm_kb())

    # Разовая задача — нужно ли фото
    elif data.startswith("tphoto:"):
        require_photo = data.split(":")[1] == "yes"
        ctx.user_data["new_task_require_photo"] = require_photo
        ctx.user_data["new_task_step"]          = "date"
        await q.message.edit_text(
            "На какую дату?\nВыбери кнопку или напиши дату сама (например 05.07 или 05.07.2026):",
            reply_markup=kb.task_date_kb())

    # Разовая задача — быстрый выбор даты
    elif data.startswith("tdate:"):
        choice = data.split(":")[1]
        from datetime import date as _date, timedelta as _td
        task_date = _date.today().isoformat() if choice == "today" else (_date.today() + _td(days=1)).isoformat()
        ctx.user_data["new_task_date"] = task_date
        ctx.user_data["new_task_step"] = "time"
        await q.message.edit_text(
            f"Дата: {task_date}\n\n"
            "Во сколько напомнить? Формат ЧЧ:ММ (например 16:30)\n"
            "Или напиши «сейчас» для немедленной отправки.",
            reply_markup=None)

    # Разовая задача — сделано
    elif data.startswith("mtask_done:"):
        task_id = int(data.split(":")[1])
        task = db.get_task(task_id)
        if not task or task["status"] in ("done", "rated"): return
        db.update_task(task_id, status="done", submitted_at=NOW())
        await safe_edit(q, f"✅ {task.get('title') or 'Задача'} — выполнено!")
        fl = db.get_user_by_id(task["assigned_to"])
        diff_label = TASK_DIFFICULTY_LABELS.get(task.get("difficulty") or "normal", "🟡 Обычная")
        await send_to_director(ctx.bot,
            f"✅ {fl['name'] if fl else '?'} выполнила задачу\n"
            f"«{task.get('title') or '—'}» ({diff_label})",
            reply_markup=kb.rating_kb(task_id))

    # Разовая задача — сделано с фото (запрос фото)
    elif data.startswith("mtask_done_photo:"):
        task_id = int(data.split(":")[1])
        task = db.get_task(task_id)
        if not task or task["status"] in ("done", "rated"): return
        db.update_task(task_id, status="waiting_photo")
        await safe_edit(q, f"📷 Пришли фото выполненной задачи «{task.get('title') or '—'}»:")
        ctx.user_data["pending_custom_task_id"] = task_id

    # Разовая задача — не сделано
    elif data.startswith("mtask_no:"):
        task_id = int(data.split(":")[1])
        task = db.get_task(task_id)
        if not task: return
        db.update_task(task_id, status="no")
        await safe_edit(q, "Понятно. Напиши причину — почему не получилось:")
        ctx.user_data["reason_task_id"] = task_id
        fl = db.get_user_by_id(task["assigned_to"])
        await send_to_director(ctx.bot,
            f"❌ {fl['name'] if fl else '?'} нажала «Не сделано»\n"
            f"«{task.get('title') or '—'}» — ждём причину")

    # Разовая задача — снуз
    elif data.startswith("mtask_snooze:"):
        _, minutes, task_id = data.split(":")
        minutes, task_id = int(minutes), int(task_id)
        task = db.get_task(task_id)
        if not task: return
        from datetime import datetime as _dt, timedelta as _td
        import pytz as _ptz
        _msk = _ptz.timezone("Europe/Moscow")
        snooze_until = (_dt.now(_msk) + _td(minutes=minutes)).strftime("%H:%M")
        db.update_task(task_id, snoozed_until=snooze_until, sent_at=None)
        await safe_edit(q, f"⏰ Напомню в {snooze_until}")
        fl = db.get_user_by_id(task["assigned_to"])
        await send_to_director(ctx.bot,
            f"⏰ {fl['name'] if fl else '?'} отложила задачу на {minutes} мин\n"
            f"«{task.get('title') or '—'}» — напомню в {snooze_until}")

    # Разовая задача — перенести на завтра
    elif data.startswith("mtask_move:"):
        task_id = int(data.split(":")[1])
        task = db.get_task(task_id)
        if not task: return
        from datetime import date as _date, timedelta as _td
        new_date = (_date.fromisoformat(task["date"]) + _td(days=1)).isoformat()
        ctx.user_data["move_task_id"]   = task_id
        ctx.user_data["move_task_date"] = new_date
        await safe_edit(q,
            f"📅 Переносим «{task.get('title') or 'Задача'}» на {new_date}\n"
            f"Во сколько напомнить? Формат ЧЧ:ММ (например 10:30)\n"
            f"Или напиши «то же» чтобы оставить {task.get('scheduled_time', '—')}")

    # Оценка причины «Не сделано» директором
    elif data.startswith("reason_rate:"):
        _, rating, task_id = data.split(":")
        task_id = int(task_id)
        if not is_director(q.from_user.id): return
        task = db.get_task(task_id)
        if not task: return
        db.update_task(task_id, reason_rating=rating)
        fl = db.get_user_by_id(task["assigned_to"])
        if rating == "bad":
            await safe_edit(q, f"👎 Оценка «Плохо» — минус KPI для {fl['name'] if fl else '?'}")
            if fl:
                await ctx.bot.send_message(fl["telegram_id"],
                    f"⚠️ Директор оценила твою причину по задаче «{task.get('title') or '—'}»\n"
                    f"Оценка: 👎 Плохо — это минус в KPI.\nОзнакомься и нажми подтверждение.",
                    reply_markup=kb.task_ack_kb(task_id))
        else:
            await safe_edit(q, f"👌 Оценка «Норм» — KPI без изменений для {fl['name'] if fl else '?'}")
            if fl:
                await ctx.bot.send_message(fl["telegram_id"],
                    f"Директор оценила причину по задаче «{task.get('title') or '—'}»\n"
                    f"Оценка: 👌 Норм — KPI без изменений.",
                    reply_markup=kb.task_ack_kb(task_id))

    # Флорист ознакомилась с оценкой
    elif data.startswith("task_ack:"):
        task_id = int(data.split(":")[1])
        task = db.get_task(task_id)
        db.update_task(task_id, status="ack")
        await safe_edit(q, "✅ Ознакомлена")
        await send_to_director(ctx.bot,
            f"✅ {q.from_user.first_name} ознакомилась с оценкой по задаче «{task.get('title') if task else '—'}»")

    # Директор нажала «Спросить почему» (3 часа)
    elif data.startswith("ask_reason_skip:"):
        task_id = int(data.split(":")[1])
        await safe_edit(q, "🔕 Уведомление проигнорировано")
    elif data.startswith("shift_rate:"):
        if not is_director(q.from_user.id): return
        task = db.get_task(task_id)
        if not task: return
        fl = db.get_user_by_id(task["assigned_to"])
        if fl:
            await ctx.bot.send_message(fl["telegram_id"],
                f"❓ Директор спрашивает почему не выполнена задача:\n\n"
                f"📋 «{task.get('title') or TASK_LABELS.get(task['type'], task['type'])}»\n\n"
                f"Напиши причину:")
            db.update_task(task_id, status="waiting_reason")
        await safe_edit(q, f"🔔 Отправила запрос флористу {fl['name'] if fl else ''}")

    # Директор нажала «Игнорировать»
    elif data.startswith("shift_rate:"):
        _, rating, florist_id, date_str = data.split(":")
        florist_id = int(florist_id)
        if not is_director(q.from_user.id): return
        fl = db.get_user_by_id(florist_id)
        messages = {
            "fire": "🔥 Директор оценила твою смену — Огонь! Так держать!",
            "good": "👍 Директор оценила твою смену — Хорошо!",
            "ok":   "😐 Директор: смена прошла нормально, есть к чему стремиться.",
            "bad":  "😤 Директор недовольна сменой. Нужно поговорить.",
        }
        director_labels = {
            "fire": "🔥 Огонь!", "good": "👍 Хорошо",
            "ok": "😐 Нормально", "bad": "😤 Плохо",
        }
        if fl:
            await ctx.bot.send_message(fl["telegram_id"], messages.get(rating, "Оценка получена"))
        await safe_edit(q, f"Оценка смены {fl['name'] if fl else '?'} · {date_str}: {director_labels.get(rating, rating)}")

    # Настройки — fcopy
    elif data.startswith("fcopy:"):
        parts   = data.split(":")
        action  = parts[1]
        task_id = int(parts[2])
        director = db.get_director()

        if action == "done":
            db.update_task(task_id, status="submitted", submitted_at=NOW())
            await q.message.edit_text("✅ Отлично! Букеты скопированы на Flowwow.", reply_markup=None)
            if director:
                await ctx.bot.send_message(director["telegram_id"],
                    f"✅ {user['name'] if user else '—'} скопировала букеты на Flowwow")
        elif action == "later":
            from datetime import datetime as _dt, timedelta as _td
            import pytz as _ptz
            _msk = _ptz.timezone("Europe/Moscow")
            snooze_until = (_dt.now(_msk) + _td(minutes=15)).strftime("%H:%M")
            db.update_task(task_id, snoozed_until=snooze_until, sent_at=None)
            await q.message.edit_text(f"⏰ Напомню в {snooze_until}.", reply_markup=None)
        elif action == "no":
            db.update_task(task_id, status="missed", no_reason="Не скопировала")
            await q.message.edit_text("Понятно. Директор получит уведомление.", reply_markup=None)
            if director:
                await ctx.bot.send_message(director["telegram_id"],
                    f"❌ {user['name'] if user else '—'} не скопировала букеты на Flowwow (11:00)")

    elif data.startswith("shortage:"):
        parts      = data.split(":")
        action     = parts[1]
        florist_id = int(parts[2])
        fl         = db.get_user_by_id(florist_id)
        director   = db.get_director()
        active_count = db.count_active_bouquets()

        if action == "done":
            await q.message.edit_text(
                f"Отлично! Букеты собраны. На витрине: {active_count}", reply_markup=None)
            if director:
                await ctx.bot.send_message(director["telegram_id"],
                    f"✅ {fl['name']} собрала букеты — на витрине {active_count}")
        elif action == "hour":
            await q.message.edit_text("Хорошо! Напомню через час.", reply_markup=None)
            if director:
                await ctx.bot.send_message(director["telegram_id"],
                    f"⏰ {fl['name']}: соберёт букеты через час (на витрине {active_count})")
            ctx.user_data[f"shortage_hour_{florist_id}"] = True
        elif action == "nostock":
            await q.message.edit_text(
                "Напиши причину — почему не из чего собрать?", reply_markup=None)
            ctx.user_data["shortage_reason_florist"] = florist_id

    elif data.startswith("shortage_dir:"):
        parts      = data.split(":")
        action     = parts[1]
        florist_id = int(parts[2])
        fl         = db.get_user_by_id(florist_id)
        if action == "ok":
            await q.message.edit_text((q.message.text or "") + "\n\n👍 Принято", reply_markup=None)
        elif action == "warn":
            await q.message.edit_text((q.message.text or "") + "\n\n⚠️ Замечание зафиксировано", reply_markup=None)
            if fl:
                try:
                    await ctx.bot.send_message(fl["telegram_id"],
                        "⚠️ Директор зафиксировал замечание по витрине букетов.")
                except Exception as e:
                    log.error(e)

    elif data.startswith("close_shift:"):
        florist_id = int(data.split(":")[1])
        fl = db.get_user_by_id(florist_id)
        if not fl: return
        ctx.user_data["closing_shift_florist"] = florist_id
        ctx.user_data["closing_step"] = "receipt"
        try:
            await ctx.bot.send_message(fl["telegram_id"],
                "Закрытие смены!\n\n1️⃣ Пришли фото чека закрытия терминала:")
        except Exception as e:
            log.error(e)

    elif data.startswith("late_ack:"):
        parts      = data.split(":")
        florist_id = int(parts[1])
        late_min   = parts[2] if len(parts) > 2 else "?"
        fl = db.get_user_by_id(florist_id)
        if not fl: return
        try:
            await q.message.edit_caption(
                (q.message.caption or "") + "\n\n👀 Ознакомлена", reply_markup=None)
        except Exception:
            pass
        try:
            await ctx.bot.send_message(fl["telegram_id"],
                f"😤 Директор ознакомлена с опозданием на {late_min} мин.\n"
                f"Директор не доволен. Опоздание записано в KPI.")
        except Exception as e:
            log.error(e)

    elif data.startswith("florist_toggle:"):
        if not is_director(q.from_user.id): return
        florist_id = int(data.split(":")[1])
        fl = db.get_user_by_id(florist_id)
        if not fl: return
        new_active = 0 if fl["active"] else 1
        conn = db.get_conn(); cur = conn.cursor()
        cur.execute("UPDATE users SET active=%s WHERE id=%s", (new_active, florist_id))
        conn.commit(); cur.close(); conn.close()
        status = "активирован" if new_active else "деактивирован"
        await q.message.edit_text(
            f"{fl['name']} {status}.",
            reply_markup=kb.settings_florists_kb(db.get_florists(active_only=False)))

    elif data.startswith("florist_schedule:"):
        florist_id = int(data.split(":")[1])
        fl = db.get_user_by_id(florist_id)
        await q.message.edit_text(
            f"Введи дату первой рабочей смены {fl['name']} в формате ГГГГ-ММ-ДД\n"
            f"Например: 2026-07-01", reply_markup=None)
        ctx.user_data["setting_schedule_florist"] = florist_id

    elif data.startswith("settings:"):
        section = data.split(":")[1]
        if section == "main":
            await q.message.edit_text("Настройки:", reply_markup=kb.settings_main_kb())
        elif section == "times":
            await q.message.edit_text("Время напоминаний:", reply_markup=kb.settings_times_kb())
        elif section == "kpi":
            await q.message.edit_text("Пороги KPI:", reply_markup=kb.settings_kpi_kb())
        elif section == "bouquet":
            await q.message.edit_text("Срок букета:", reply_markup=kb.settings_bouquet_kb())
        elif section == "florists":
            florists = db.get_florists(active_only=False)
            if not florists:
                await q.message.edit_text("Флористов нет.", reply_markup=None)
                return
            ym = datetime.now().strftime("%Y-%m")
            lines = ["Флористов: " + str(len(florists)) + "\n"]
            for f in florists:
                shifts = db.get_month_shifts(f["id"], ym)
                status = "Активна" if f["active"] else "Неактивна"
                lines.append(f"{f['name']} — {status} — смен в {ym}: {len(shifts)}")
            await q.message.edit_text("\n".join(lines),
                reply_markup=kb.settings_florists_kb(florists))

    elif data.startswith("setval:"):
        if not is_director(q.from_user.id): return
        setting_key = data.split(":")[1]
        current = db.get_setting(setting_key, "—")
        ctx.user_data["setting_key"] = setting_key
        label = kb.SETTING_LABELS.get(setting_key, setting_key)
        await q.message.edit_text(f"Текущее: {current}\nВведи новое {label}:")


# ── Photo handler ──────────────────────────────────────────

async def resend_task_kb(bot, florist, task_type, task_id):
    import keyboards as kb
    texts = {
        "vitrina_bouquets":     "⏰ Напоминание — витрина букетов\nПришли фото:",
        "vitrina_compositions": "⏰ Напоминание — витрина композиций\nПришли фото:",
        "flowwow":              "⏰ Напоминание — Flowwow\nПришли фото или скрин:",
    }
    text = texts.get(task_type, "Напоминание — пришли фото:")
    try:
        await bot.send_message(
            florist["telegram_id"], text,
            reply_markup=kb.task_response_kb(task_id, task_type))
    except Exception as e:
        log.error(f"resend_task_kb error: {e}")


async def _send_missed_tasks(bot, user, now_time_str):
    today = TODAY()
    try:
        h, m = map(int, now_time_str.split(":"))
        t = h * 60 + m
    except Exception:
        return
    tasks_schedule = [
        ("vitrina_bouquets",     14 * 60, db.get_setting("vitrina_bouquets_time",     "14:00")),
        ("flowwow",              15 * 60, db.get_setting("flowwow_time",              "15:00")),
        ("vitrina_compositions", 18 * 60, db.get_setting("vitrina_compositions_time", "18:00")),
    ]
    for task_type, task_min, task_time in tasks_schedule:
        if t > task_min:
            existing = db.get_pending_task(user["id"], task_type, today)
            if not existing:
                await send_task(bot, user, task_type, task_time)


async def photo_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user: return
    file_id = update.message.photo[-1].file_id

    # Закрытие смены — фото чека и холодильников
    if ctx.user_data.get("closing_step"):
        step       = ctx.user_data.get("closing_step")
        florist_id = ctx.user_data.get("closing_shift_florist", user["id"])
        today      = TODAY()
        if step == "receipt":
            db.update_shift(florist_id, today, close_receipt_photo=file_id)
            ctx.user_data["closing_step"] = "fridge1"
            await update.message.reply_text("✅ Чек принят!\n\n2️⃣ Пришли фото холодильника (1 из 2):")
        elif step == "fridge1":
            db.update_shift(florist_id, today, fridge_photo1=file_id)
            ctx.user_data["closing_step"] = "fridge2"
            await update.message.reply_text("✅ Фото 1 принято!\n\n3️⃣ Пришли фото холодильника (2 из 2):")
        elif step == "fridge2":
            close_time = NOWT()
            db.update_shift(florist_id, today, fridge_photo2=file_id, closed_at=close_time)
            ctx.user_data.pop("closing_step", None)
            ctx.user_data.pop("closing_shift_florist", None)
            shift = db.get_shift(florist_id, today)
            overtime_txt = ""
            start_time = shift.get("receipt_time") if shift else None
            if start_time:
                worked_min = _time_diff_minutes(start_time, close_time)
                if worked_min is not None:
                    standard_h   = float(db.get_setting("standard_shift_hours", "12"))
                    overtime_min = max(0, worked_min - int(standard_h * 60))
                    db.update_shift(florist_id, today, worked_minutes=worked_min, overtime_minutes=overtime_min)
                    wh, wm = divmod(worked_min, 60)
                    if overtime_min > 0:
                        oh, om = divmod(overtime_min, 60)
                        overtime_txt = f"\n⏱ Отработано: {wh}ч {wm}мин · Переработка: {oh}ч {om}мин — учти при оплате"
                    else:
                        overtime_txt = f"\n⏱ Отработано: {wh}ч {wm}мин"
            await update.message.reply_text("✅ Смена закрыта! Хорошего отдыха 🌸")
            d = db.get_director()
            if d:
                fl = db.get_user_by_id(florist_id)
                await ctx.bot.send_message(d["telegram_id"],
                    f"🔒 {fl['name'] if fl else 'Флорист'} закрыла смену в {close_time}{overtime_txt}")
                try:
                    if shift and shift.get("close_receipt_photo"):
                        await ctx.bot.send_photo(d["telegram_id"],
                            photo=shift["close_receipt_photo"], caption="Чек закрытия терминала")
                    if shift and shift.get("fridge_photo1"):
                        await ctx.bot.send_photo(d["telegram_id"],
                            photo=shift["fridge_photo1"], caption="Холодильник 1/2")
                    if shift and shift.get("fridge_photo2"):
                        await ctx.bot.send_photo(d["telegram_id"],
                            photo=shift["fridge_photo2"], caption="Холодильник 2/2")
                except Exception as e:
                    log.error(e)
        return

    # Определяем состояние
    waiting_receipt    = "waiting_receipt"   in ctx.user_data
    waiting_task_photo = "pending_task_id"   in ctx.user_data
    waiting_manual     = "manual_task_type"  in ctx.user_data
    adding_bouquet     = ctx.user_data.get("bouquet_cost_step") or ctx.user_data.get("adding_bouquet") or "bouquet_photo" in ctx.user_data
    adding_composition = ctx.user_data.get("composition_cost_step") or ctx.user_data.get("adding_composition") or "composition_photo" in ctx.user_data

    shift_needs_receipt = (
        user["role"] == "florist" and
        db.has_shift(user["id"], TODAY()) and
        not db.has_receipt(user["id"], TODAY()) and
        not waiting_task_photo and
        not waiting_manual and
        not adding_bouquet and
        not adding_composition
    )

    if waiting_receipt or shift_needs_receipt:
        florist_id = ctx.user_data.pop("waiting_receipt", user["id"])
        shift_date = ctx.user_data.pop("receipt_shift_date", TODAY())
        now_time   = NOWT()
        late_type  = get_late_type(now_time)
        db.update_shift(florist_id, shift_date,
                        open_receipt_photo=file_id,
                        receipt_time=now_time,
                        late_type=late_type)
        if late_type is None:
            await update.message.reply_text(f"✅ Смена открыта в {now_time} — вовремя!")
            await send_to_director(ctx.bot,
                f"✅ {user['name']} открыла смену в {now_time} — вовремя",
                photo=file_id)
            await _send_missed_tasks(ctx.bot, user, now_time)
        else:
            label = LATE_LABELS.get(late_type, "опоздание")
            ym = datetime.now().strftime("%Y-%m")
            lates = db.get_month_lates(florist_id, ym)
            late_count = lates.get(late_type, 0)
            max_map = {"light": int(db.get_setting("kpi_late_light_max","5")),
                       "medium": int(db.get_setting("kpi_late_medium_max","3")),
                       "heavy": int(db.get_setting("kpi_late_heavy_max","2")),
                       "no_show": 1}
            max_v = max_map.get(late_type, 1)
            try:
                t_receipt = datetime.strptime(now_time, "%H:%M")
                t_start   = datetime.strptime("10:05", "%H:%M")
                late_min  = int((t_receipt - t_start).total_seconds() / 60)
            except Exception:
                late_min = 0
            await update.message.reply_text(
                f"⚠️ Опоздание зафиксировано — {now_time}\n"
                f"({label}, +{late_min} мин)\n"
                f"Таких в месяце: {late_count} из {max_v}\n"
                f"Отправляю информацию директору...")
            await _send_missed_tasks(ctx.bot, user, now_time)
            d = db.get_director()
            if d:
                await ctx.bot.send_photo(
                    d["telegram_id"], photo=file_id,
                    caption=(
                        f"⚠️ {user['name']} опоздала на {late_min} мин\n"
                        f"Время открытия: {now_time} ({label})\n"
                        f"Опозданий в месяце: {late_count}/{max_v}\n"
                        f"Нажми «Ознакомлена» чтобы флорист узнала"
                    ),
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton(
                            "👀 Ознакомлена",
                            callback_data=f"late_ack:{florist_id}:{late_min}")
                    ]]))
        return

    # Фото задачи
    # Фото для разовой задачи с require_photo
    if "pending_custom_task_id" in ctx.user_data:
        task_id = ctx.user_data.pop("pending_custom_task_id")
        task = db.get_task(task_id)
        db.update_task(task_id, status="done", photo_file_id=file_id, submitted_at=NOW())
        await update.message.reply_text("✅ Фото получено, задача засчитана!")
        fl = db.get_user_by_id(task["assigned_to"]) if task else None
        diff_label = TASK_DIFFICULTY_LABELS.get(task.get("difficulty") or "normal", "🟡 Обычная") if task else ""
        d = db.get_director()
        if d:
            await ctx.bot.send_photo(d["telegram_id"], photo=file_id,
                caption=f"✅ {fl['name'] if fl else user['name']} выполнила задачу\n"
                        f"«{task.get('title') or '—'}» ({diff_label})\n\nОцени:",
                reply_markup=kb.rating_kb(task_id))
        return

    if "pending_task_id" in ctx.user_data:
        task_id   = ctx.user_data.pop("pending_task_id")
        task_type = ctx.user_data.pop("pending_task_type", "")
        db.update_task(task_id, status="submitted", photo_file_id=file_id, submitted_at=NOW())
        await update.message.reply_text("Фото получено! Отправляю директору.")
        d = db.get_director()
        if d:
            msg = await ctx.bot.send_photo(d["telegram_id"], photo=file_id,
                caption=f"{TASK_LABELS.get(task_type, task_type)}\n"
                        f"{user['name']} — {datetime.now().strftime('%d.%m %H:%M')}\n\nОцени:",
                reply_markup=kb.rating_kb(task_id))
            db.update_task(task_id, director_msg_id=msg.message_id)
        if task_type == "vitrina_bouquets":
            active_count = db.count_active_bouquets()
            min_v = int(db.get_setting("min_vitrina_bouquets", "6"))
            if active_count < min_v:
                need = min_v - active_count
                await update.message.reply_text(
                    f"На витрине сейчас: {active_count} букетов\n"
                    f"Минимум: {min_v}\nНужно собрать ещё: {need}",
                    reply_markup=kb.vitrina_shortage_kb(user["id"]))
        return

    # Ручной отчёт
    if "manual_task_type" in ctx.user_data:
        task_type = ctx.user_data.pop("manual_task_type")
        task_id   = db.create_task(task_type, user["id"], TODAY(), NOWT())
        db.update_task(task_id, status="submitted", photo_file_id=file_id, submitted_at=NOW())
        await update.message.reply_text("Фото получено! Отправляю директору на оценку.")
        d = db.get_director()
        if d:
            msg = await ctx.bot.send_photo(d["telegram_id"], photo=file_id,
                caption=f"[Ручной] {TASK_LABELS.get(task_type, task_type)}\n"
                        f"{user['name']} — {datetime.now().strftime('%d.%m %H:%M')}\n\nОцени:",
                reply_markup=kb.rating_kb(task_id))
            db.update_task(task_id, director_msg_id=msg.message_id)
        return

    # Букет — фото
    if ctx.user_data.get("adding_bouquet"):
        ctx.user_data["bouquet_photo"]     = file_id
        ctx.user_data["adding_bouquet"]    = False
        ctx.user_data["bouquet_cost_step"] = True
        await update.message.reply_text(
            "Введи через запятую: себестоимость, цена продажи\nНапример: 2000, 3500")
        return

    # Композиция — фото
    if ctx.user_data.get("adding_composition"):
        ctx.user_data["composition_photo"]     = file_id
        ctx.user_data["adding_composition"]    = False
        ctx.user_data["composition_cost_step"] = True
        await update.message.reply_text(
            "Введи через запятую: себестоимость, цена продажи\nНапример: 1500, 2800")
        return

    await update.message.reply_text("Используй /buket для нового букета или команды витрины.")


# ── Text handler ───────────────────────────────────────────

async def text_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Напиши /start чтобы зарегистрироваться.")
        return
    text = update.message.text.strip()

    # Причина нехватки букетов на витрине
    if "shortage_reason_florist" in ctx.user_data:
        florist_id = ctx.user_data.pop("shortage_reason_florist")
        d = db.get_director()
        if d:
            fl = db.get_user_by_id(florist_id)
            name = fl["name"] if fl else "Флорист"
            await ctx.bot.send_message(d["telegram_id"],
                f"❌ {name}: не из чего собрать букеты на витрину\nПричина: {text}",
                reply_markup=kb.director_shortage_kb(florist_id))
        await update.message.reply_text("Причина отправлена директору.")
        return

    # График флориста
    if "setting_schedule_florist" in ctx.user_data:
        florist_id = ctx.user_data.pop("setting_schedule_florist")
        db.update_user(florist_id, schedule_start_date=text.strip())
        fl = db.get_user_by_id(florist_id)
        await update.message.reply_text(f"✅ График {fl['name']} установлен с {text.strip()}")
        return

    # Причина невыполнения задачи
    # Перенос задачи — ввод нового времени
    if "move_task_id" in ctx.user_data:
        task_id  = ctx.user_data.pop("move_task_id")
        new_date = ctx.user_data.pop("move_task_date")
        task     = db.get_task(task_id)
        if text.strip().lower() in ("то же", "тоже", "same"):
            new_time = task["scheduled_time"] if task else NOWT()
        else:
            import re as _re
            m = _re.match(r"^(\d{1,2}):(\d{2})$", text.strip())
            if not m or not (0 <= int(m.group(1)) <= 23 and 0 <= int(m.group(2)) <= 59):
                await update.message.reply_text("Формат времени: ЧЧ:ММ, например 10:30\nИли напиши «то же»")
                ctx.user_data["move_task_id"]   = task_id
                ctx.user_data["move_task_date"] = new_date
                return
            new_time = f"{int(m.group(1)):02d}:{int(m.group(2)):02d}"
        db.update_task(task_id, date=new_date, scheduled_time=new_time,
                       sent_at=None, snoozed_until=None, status="pending")
        await update.message.reply_text(
            f"✅ Задача «{task.get('title') or '—'}» перенесена\n📅 {new_date} в {new_time}")
        fl = db.get_user_by_id(task["assigned_to"]) if task else None
        await send_to_director(ctx.bot,
            f"📅 {fl['name'] if fl else user['name']} перенесла задачу "
            f"«{task.get('title') if task else '—'}» на {new_date} в {new_time}")
        return
    if "reason_task_id" in ctx.user_data:
        task_id = ctx.user_data.pop("reason_task_id")
        task = db.get_task(task_id)
        db.update_task(task_id, no_reason=text, task_reason=text, status="no")
        await update.message.reply_text("Записала. Директор получит причину и оценит.")
        if task and task["type"] == "custom":
            label = task.get("title") or "разовая задача"
            await send_to_director(ctx.bot,
                f"❌ {user['name']} не выполнила задачу\n«{label}»\nПричина: {text}\n\nОцени:",
                reply_markup=kb.reason_rate_kb(task_id))
        else:
            label = TASK_LABELS.get(task["type"], task["type"]) if task else "задача"
            await send_to_director(ctx.bot,
                f"❌ Задача не выполнена — {user['name']}\n{label}\nПричина: {text}")
        return

    # Разовая задача — текст
    if ctx.user_data.get("new_task_step") == "text":
        lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
        if len(lines) > 1:
            # Пакетный режим — несколько задач через перенос строки
            ctx.user_data["new_task_titles"] = lines
            ctx.user_data["new_task_step"]   = "difficulty"
            await update.message.reply_text(
                f"Отлично! {len(lines)} задач:\n" +
                "\n".join(f"• {l}" for l in lines) +
                "\n\nНасколько они сложные? (один уровень для всех)",
                reply_markup=kb.task_difficulty_kb())
        else:
            ctx.user_data["new_task_title"] = lines[0] if lines else text
            ctx.user_data["new_task_step"]  = "difficulty"
            await update.message.reply_text("Насколько сложная задача?", reply_markup=kb.task_difficulty_kb())
        return

    # Разовая задача — дата вручную
    if ctx.user_data.get("new_task_step") == "date":
        from datetime import date as _date, timedelta as _td
        t = text.strip().lower()
        if t in ("сегодня", "today"):
            task_date = _date.today().isoformat()
        elif t in ("завтра", "tomorrow"):
            task_date = (_date.today() + _td(days=1)).isoformat()
        else:
            import re as _re
            m = _re.match(r"^(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?$", text.strip())
            if not m:
                await update.message.reply_text(
                    "Формат даты: ДД.ММ или ДД.ММ.ГГГГ (например 05.07 или 05.07.2026), "
                    "или напиши «сегодня»/«завтра»")
                return
            d, mo = int(m.group(1)), int(m.group(2))
            y = int(m.group(3)) if m.group(3) else _date.today().year
            try:
                task_date = _date(y, mo, d).isoformat()
            except ValueError:
                await update.message.reply_text("Такой даты не существует, проверь и напиши ещё раз.")
                return
        ctx.user_data["new_task_date"] = task_date
        ctx.user_data["new_task_step"] = "time"
        await update.message.reply_text(
            f"Дата: {task_date}\n\n"
            "Во сколько напомнить? Формат ЧЧ:ММ (например 16:30)\n"
            "Или напиши «сейчас» для немедленной отправки.")
        return

    # Разовая задача — время
    if ctx.user_data.get("new_task_step") == "time":
        if text.strip().lower() in ("сейчас", "now"):
            scheduled_time = NOWT()
        else:
            import re as _re
            m = _re.match(r"^(\d{1,2}):(\d{2})$", text.strip())
            if not m or not (0 <= int(m.group(1)) <= 23 and 0 <= int(m.group(2)) <= 59):
                await update.message.reply_text("Формат времени: ЧЧ:ММ, например 16:30 (или «сейчас»)")
                return
            scheduled_time = f"{int(m.group(1)):02d}:{int(m.group(2)):02d}"

        assigned_to   = ctx.user_data.pop("new_task_assigned_to")
        created_by    = ctx.user_data.pop("new_task_created_by")
        difficulty    = ctx.user_data.pop("new_task_difficulty", "normal")
        mandatory     = ctx.user_data.pop("new_task_mandatory", False)
        require_photo = ctx.user_data.pop("new_task_require_photo", False)
        task_date     = ctx.user_data.pop("new_task_date", TODAY())
        titles        = ctx.user_data.pop("new_task_titles", None)
        title         = ctx.user_data.pop("new_task_title", None)
        ctx.user_data.pop("new_task_step", None)

        fl         = db.get_user_by_id(assigned_to)
        creator    = db.get_user_by_id(created_by) if assigned_to != created_by else None
        mand_txt   = "\n❗️ Обязательно сегодня" if mandatory else ""
        photo_txt  = "\n📷 Требуется фото-подтверждение" if require_photo else ""
        diff_label = TASK_DIFFICULTY_LABELS.get(difficulty, difficulty)

        # Пакетный режим — несколько задач
        if titles:
            created_ids = []
            for t_title in titles:
                tid = db.create_custom_task(assigned_to, created_by, task_date, scheduled_time,
                                            t_title, difficulty, mandatory, require_photo)
                db.update_task(tid, sent_at=f"{task_date} {scheduled_time}:00")
                created_ids.append((tid, t_title))
            await update.message.reply_text(
                f"✅ Создано {len(created_ids)} задач!\n" +
                "\n".join(f"• «{t}»" for _, t in created_ids) +
                f"\n{diff_label} · {task_date} в {scheduled_time}{mand_txt}{photo_txt}\n"
                f"Кому: {fl['name'] if fl else '—'}")
            if assigned_to != created_by and fl:
                try:
                    for tid, t_title in created_ids:
                        await ctx.bot.send_message(fl["telegram_id"],
                        f"📝 Новая задача: <b>«{title}»</b>\n"
                        f"⏰ {scheduled_time}{mand_txt}\n"
                        f"{diff_label}",
                        parse_mode="HTML",
                        reply_markup=kb.custom_task_kb(task_id, require_photo=require_photo))
                except Exception as e:
                    log.error(e)
            elif assigned_to == created_by:
                await send_to_director(ctx.bot,
                    f"📝 {fl['name'] if fl else 'Флорист'} поставила себе {len(created_ids)} задач\n" +
                    "\n".join(f"• «{t}»" for _, t in created_ids) +
                    f"\n{diff_label} · {task_date} {scheduled_time}{mand_txt}")
        else:
            # Одна задача
            task_id = db.create_custom_task(assigned_to, created_by, task_date, scheduled_time,
                                            title, difficulty, mandatory, require_photo)
            await update.message.reply_text(
                f"✅ Задача создана!\n«{title}»\n"
                f"{diff_label} · {task_date} в {scheduled_time}{mand_txt}{photo_txt}\n"
                f"Кому: {fl['name'] if fl else '—'}")
            if assigned_to != created_by and fl:
                try:
                    await ctx.bot.send_message(fl["telegram_id"],
                        f"📝 Новая задача: «{title}»\n"
                        f"⏰ {task_date} в {scheduled_time}\n"
                        f"{diff_label}{mand_txt}",
                        reply_markup=kb.custom_task_kb(task_id, require_photo=require_photo))
                except Exception as e:
                    log.error(e)
            else:
                await send_to_director(ctx.bot,
                    f"📝 {fl['name'] if fl else 'Флорист'} поставила себе задачу\n"
                    f"«{title}» · {diff_label} · {task_date} {scheduled_time}{mand_txt}")
        return

    # Новая себестоимость и цена после пересборки букета
    if "reassemble_bouquet_id" in ctx.user_data:
        bouquet_id = ctx.user_data.pop("reassemble_bouquet_id")
        try:
            parts = [p.strip().replace(" ", "") for p in text.replace(",", ",").split(",")]
            if len(parts) != 2:
                raise ValueError
            cost  = int(parts[0])
            price = int(parts[1])
        except:
            await update.message.reply_text(
                "Формат: себестоимость, цена — через запятую\nНапример: 2000, 3500")
            ctx.user_data["reassemble_bouquet_id"] = bouquet_id
            return
        db.update_bouquet(bouquet_id, cost=cost, price=price)
        bouquet = db.get_bouquet(bouquet_id)
        await update.message.reply_text(
            f"✅ Букет #{bouquet_id} обновлён!\n"
            f"Новая себестоимость: {cost:,} ₽\nНовая цена: {price:,} ₽\n"
            f"Срок годности считается с {bouquet.get('created_at', '—')[:10]}".replace(",", " "),
            reply_markup=kb.bouquet_status_kb(bouquet_id))
        fl_name = user["name"]
        await send_to_director(ctx.bot,
            f"🔄 Букет #{bouquet_id} пересобран — {fl_name}\n"
            f"Себестоимость: {cost:,} ₽ · Цена: {price:,} ₽".replace(",", " "))
        return

    # Новая себестоимость и цена после пересборки композиции
    if "reassemble_composition_id" in ctx.user_data:
        composition_id = ctx.user_data.pop("reassemble_composition_id")
        try:
            parts = [p.strip().replace(" ", "") for p in text.replace(",", ",").split(",")]
            if len(parts) != 2:
                raise ValueError
            cost  = int(parts[0])
            price = int(parts[1])
        except:
            await update.message.reply_text(
                "Формат: себестоимость, цена — через запятую\nНапример: 1500, 2800")
            ctx.user_data["reassemble_composition_id"] = composition_id
            return
        db.update_composition(composition_id, cost=cost, price=price)
        composition = db.get_composition(composition_id)
        await update.message.reply_text(
            f"✅ Композиция #{composition_id} обновлена!\n"
            f"Новая себестоимость: {cost:,} ₽\nНовая цена: {price:,} ₽\n"
            f"Срок годности считается с {composition.get('created_at', '—')[:10]}".replace(",", " "),
            reply_markup=kb.composition_status_kb(composition_id))
        await send_to_director(ctx.bot,
            f"🔄 Композиция #{composition_id} пересобрана — {user['name']}\n"
            f"Себестоимость: {cost:,} ₽ · Цена: {price:,} ₽".replace(",", " "))
        return

    # Себестоимость и цена букета
    if ctx.user_data.get("bouquet_cost_step"):
        try:
            parts = [p.strip().replace(" ", "") for p in text.replace(",", ",").split(",")]
            if len(parts) != 2:
                raise ValueError
            cost  = int(parts[0])
            price = int(parts[1])
        except:
            await update.message.reply_text(
                "Формат: себестоимость, цена — через запятую\nНапример: 2000, 3500")
            return
        ctx.user_data["bouquet_cost_step"] = False
        photo = ctx.user_data.pop("bouquet_photo", None)
        if not photo:
            await update.message.reply_text("Что-то пошло не так. Начни заново: /buket")
            return
        bouquet_id = db.create_bouquet(user["id"], photo, cost, price)
        await update.message.reply_text(
            f"Букет #{bouquet_id} добавлен!\n"
            f"Себестоимость: {cost:,} ₽\nЦена: {price:,} ₽".replace(",", " "),
            reply_markup=kb.bouquet_status_kb(bouquet_id))
        d = db.get_director()
        if d:
            caption = (f"🌸 Новый букет #{bouquet_id}\n"
                       f"Флорист: {user['name']}\n"
                       f"Себестоимость: {cost:,} ₽ · Цена: {price:,} ₽\n\nОцени:".replace(",", " "))
            if photo:
                await ctx.bot.send_photo(d["telegram_id"], photo=photo,
                    caption=caption, reply_markup=kb.bouquet_rating_kb(bouquet_id))
            else:
                await ctx.bot.send_message(d["telegram_id"], caption,
                    reply_markup=kb.bouquet_rating_kb(bouquet_id))
        return

    # Себестоимость и цена композиции
    if ctx.user_data.get("composition_cost_step"):
        try:
            parts = [p.strip().replace(" ", "") for p in text.replace(",", ",").split(",")]
            if len(parts) != 2:
                raise ValueError
            cost  = int(parts[0])
            price = int(parts[1])
        except:
            await update.message.reply_text(
                "Формат: себестоимость, цена — через запятую\nНапример: 1500, 2800")
            return
        ctx.user_data["composition_cost_step"] = False
        photo = ctx.user_data.pop("composition_photo", None)
        if not photo:
            await update.message.reply_text("Что-то пошло не так. Начни заново: /kompoziciya")
            return
        composition_id = db.create_composition(user["id"], photo, cost, price)
        await update.message.reply_text(
            f"Композиция #{composition_id} добавлена!\n"
            f"Себестоимость: {cost:,} ₽\nЦена: {price:,} ₽".replace(",", " "),
            reply_markup=kb.composition_status_kb(composition_id))
        d = db.get_director()
        if d:
            caption = (f"🎋 Новая композиция #{composition_id}\n"
                       f"Флорист: {user['name']}\n"
                       f"Себестоимость: {cost:,} ₽ · Цена: {price:,} ₽\n\nОцени:".replace(",", " "))
            if photo:
                await ctx.bot.send_photo(d["telegram_id"], photo=photo,
                    caption=caption, reply_markup=kb.composition_rating_kb(composition_id))
            else:
                await ctx.bot.send_message(d["telegram_id"], caption,
                    reply_markup=kb.composition_rating_kb(composition_id))
        return

    # Новая цена продажи букета
    if "sell_bouquet_id" in ctx.user_data:
        bouquet_id = ctx.user_data.pop("sell_bouquet_id")
        channel    = ctx.user_data.pop("sell_channel", "discount")
        try:
            sold_price = int(text.replace(" ", ""))
        except:
            await update.message.reply_text("Введи цену цифрами, например: 2800")
            ctx.user_data["sell_bouquet_id"] = bouquet_id
            ctx.user_data["sell_channel"]    = channel
            return
        bouquet = db.get_bouquet(bouquet_id)
        if not bouquet:
            await update.message.reply_text("Букет не найден.")
            return
        status = f"sold_{channel}" if channel != "discount" else "sold_discount"
        db.update_bouquet(bouquet_id, status=status, sale_channel=channel,
                          sold_at=NOW(), sold_price=sold_price)
        orig   = bouquet["price"]
        profit = sold_price - (bouquet.get("cost") or 0)
        ch_label = "на Flowwow" if channel == "flowwow" else f"в студии со скидкой (было {orig:,} ₽)".replace(",", " ")
        await update.message.reply_text(
            f"✅ Букет #{bouquet_id} продан {ch_label}!\nЦена: {sold_price:,} ₽".replace(",", " "))
        fl = db.get_user_by_id(bouquet["florist_id"])
        await send_to_director(ctx.bot,
            f"{'🛍' if channel=='flowwow' else '🏷'} Букет #{bouquet_id} продан {ch_label}\n"
            f"Флорист: {fl['name'] if fl else '—'}\n"
            f"Цена: {sold_price:,} ₽ · Прибыль: ~{profit:,} ₽".replace(",", " "))
        return

    # Новая цена продажи композиции
    if "sell_composition_id" in ctx.user_data:
        composition_id = ctx.user_data.pop("sell_composition_id")
        channel        = ctx.user_data.pop("sell_channel", "discount")
        try:
            sold_price = int(text.replace(" ", ""))
        except:
            await update.message.reply_text("Введи цену цифрами, например: 2200")
            ctx.user_data["sell_composition_id"] = composition_id
            ctx.user_data["sell_channel"]        = channel
            return
        composition = db.get_composition(composition_id)
        if not composition:
            await update.message.reply_text("Композиция не найдена.")
            return
        status = f"sold_{channel}" if channel != "discount" else "sold_discount"
        db.update_composition(composition_id, status=status, sale_channel=channel,
                          sold_at=NOW(), sold_price=sold_price)
        orig   = composition["price"]
        profit = sold_price - (composition.get("cost") or 0)
        ch_label = "на Flowwow" if channel == "flowwow" else f"в студии со скидкой (было {orig:,} ₽)".replace(",", " ")
        await update.message.reply_text(
            f"✅ Композиция #{composition_id} продана {ch_label}!\nЦена: {sold_price:,} ₽".replace(",", " "))
        fl = db.get_user_by_id(composition["florist_id"])
        await send_to_director(ctx.bot,
            f"{'🛍' if channel=='flowwow' else '🏷'} Композиция #{composition_id} продана {ch_label}\n"
            f"Флорист: {fl['name'] if fl else '—'}\n"
            f"Цена: {sold_price:,} ₽ · Прибыль: ~{profit:,} ₽".replace(",", " "))
        return

    # Значение настройки
    if "setting_key" in ctx.user_data and user["role"] == "director":
        key = ctx.user_data.pop("setting_key")
        db.set_setting(key, text)
        await update.message.reply_text(f"Сохранено: {key} = {text}", reply_markup=kb.settings_main_kb())
        return

    # Claude для директора
    if user["role"] == "director":
        await update.message.reply_text("Анализирую данные...")
        response = ask_claude(text)
        await update.message.reply_text(f"Claude: {response}")
        return

    await update.message.reply_text(_florist_help())


# ── Commands ───────────────────────────────────────────────

async def cmd_otkryt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user or user["role"] != "florist": return
    if db.has_shift(user["id"], TODAY()):
        if db.has_receipt(user["id"], TODAY()):
            await update.message.reply_text("Смена уже открыта — чек получен.")
        else:
            await update.message.reply_text("Смена начата, но чека нет. Пришли фото чека с терминала:")
            ctx.user_data["waiting_receipt"]    = user["id"]
            ctx.user_data["receipt_shift_date"] = TODAY()
        return
    db.start_shift(user["id"], TODAY())
    await update.message.reply_text("Смена открыта! Пришли фото чека с терминала:")
    ctx.user_data["waiting_receipt"]    = user["id"]
    ctx.user_data["receipt_shift_date"] = TODAY()


async def send_shift_report(bot, florist_id, date_str):
    """Отчёт смены за 10 минут до закрытия."""
    fl    = db.get_user_by_id(florist_id)
    if not fl: return
    today = date_str

    # Смена
    shift = db.get_shift(florist_id, today)
    open_time  = shift.get("receipt_time", "—") if shift else "—"
    late_type  = shift.get("late_type") if shift else None
    if late_type is None:
        time_line = f"Открыта: {open_time} ✅ вовремя"
    else:
        late_labels = {"light": "лёгкое опоздание", "medium": "опоздание",
                       "heavy": "серьёзное опоздание", "no_show": "критическое опоздание"}
        time_line = f"Открыта: {open_time} ⚠️ {late_labels.get(late_type, 'опоздание')}"

    lines = [f"📊 Итог смены · {fl['name']} · {today[8:]}.{today[5:7]}", "",
             "🕐 СМЕНА", f"  {time_line}", ""]

    # Стандартные задачи
    tasks_std = db.get_month_tasks(florist_id, today)
    std_map   = {t["type"]: t for t in tasks_std}

    def task_line(label, emoji, task_type):
        t = std_map.get(task_type)
        if not t: return None
        if t["status"] in ("submitted", "rated", "done"):
            rating = RATING_LABELS.get(t.get("rating"), "")
            return f"{emoji} {label} — ✅ сдала {('(' + rating + ')') if rating else ''}"
        return f"{emoji} {label} — ❌ не сдала"

    std_lines = []
    l = task_line("ВИТРИНА БУКЕТОВ",    "🌸", "vitrina_bouquets")
    if l: std_lines.append(l)
    l = task_line("ВИТРИНА КОМПОЗИЦИЙ", "🎋", "vitrina_compositions")
    if l: std_lines.append(l)

    # Flowwow — только если был сегодня
    flowwow_task = std_map.get("flowwow")
    if flowwow_task:
        if flowwow_task["status"] in ("submitted", "rated", "done"):
            std_lines.append("🛍 FLOWWOW — ✅ сдала")
        else:
            std_lines.append("🛍 FLOWWOW — ❌ не сдала")

    if std_lines:
        lines += std_lines + [""]

    # Разовые задачи
    custom_tasks = db.get_day_custom_tasks(today, florist_id)
    if custom_tasks:
        done_c = [t for t in custom_tasks if t["status"] in ("done","rated","ack")]
        fail_c = [t for t in custom_tasks if t["status"] in ("no","missed","missed_mandatory")]
        pend_c = [t for t in custom_tasks if t["status"] == "pending"]
        lines.append(f"📋 РАЗОВЫЕ ЗАДАЧИ ({len(done_c)} из {len(custom_tasks)})")
        for t in done_c:
            diff = TASK_DIFFICULTY_LABELS.get(t.get("difficulty") or "normal", "")
            lines.append(f"  ✅ {t.get('title') or '—'} {diff}")
        for t in fail_c:
            diff = TASK_DIFFICULTY_LABELS.get(t.get("difficulty") or "normal", "")
            reason = f" · {t.get('no_reason')}" if t.get("no_reason") else ""
            lines.append(f"  ❌ {t.get('title') or '—'} {diff}{reason}")
        for t in pend_c:
            diff = TASK_DIFFICULTY_LABELS.get(t.get("difficulty") or "normal", "")
            lines.append(f"  ⏳ {t.get('title') or '—'} {diff} (не закрыта)")
        lines.append("")

    # Движение витрины за смену
    conn = db.get_conn(); cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM bouquets WHERE florist_id=%s AND created_at LIKE %s",
                (florist_id, f"{today}%"))
    new_b = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM compositions WHERE florist_id=%s AND created_at LIKE %s",
                (florist_id, f"{today}%"))
    new_c = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM bouquets WHERE florist_id=%s AND sold_at LIKE %s AND sale_channel='studio'",
                (florist_id, f"{today}%"))
    sold_studio = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM bouquets WHERE florist_id=%s AND sold_at LIKE %s AND sale_channel='flowwow'",
                (florist_id, f"{today}%"))
    sold_fw = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM bouquets WHERE florist_id=%s AND disassembled_at LIKE %s",
                (florist_id, f"{today}%"))
    disasm_b = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM compositions WHERE florist_id=%s AND disassembled_at LIKE %s",
                (florist_id, f"{today}%"))
    disasm_c = cur.fetchone()[0]
    cur.close(); conn.close()

    vitrina_lines = []
    if new_b or new_c:
        parts = []
        if new_b: parts.append(f"{new_b} букет{'а' if new_b in (2,3,4) else 'ов' if new_b > 4 else ''}")
        if new_c: parts.append(f"{new_c} композиц{'ии' if new_c in (2,3,4) else 'ий' if new_c > 4 else 'ия'}")
        vitrina_lines.append(f"  ➕ Собрано: {', '.join(parts)}")
    if sold_studio or sold_fw:
        parts = []
        if sold_studio: parts.append(f"{sold_studio} в студии")
        if sold_fw:     parts.append(f"{sold_fw} на Flowwow")
        vitrina_lines.append(f"  💰 Продано: {', '.join(parts)}")
    if disasm_b or disasm_c:
        parts = []
        if disasm_b: parts.append(f"{disasm_b} букет")
        if disasm_c: parts.append(f"{disasm_c} композиция")
        vitrina_lines.append(f"  🗑 Разобрано: {', '.join(parts)}")
    if vitrina_lines:
        lines.append("🌹 ВИТРИНА · движение за смену")
        lines += vitrina_lines
        lines.append("")

    # Процент выполнения
    total = len([t for t in tasks_std if t["type"] in ("vitrina_bouquets","vitrina_compositions")
                 and std_map.get(t["type"])]) + (1 if flowwow_task else 0) + len(custom_tasks)
    done  = len([t for t in tasks_std if t["type"] in ("vitrina_bouquets","vitrina_compositions")
                 and std_map.get(t["type"]) and
                 std_map[t["type"]]["status"] in ("submitted","rated","done")]) + \
            (1 if flowwow_task and flowwow_task["status"] in ("submitted","rated","done") else 0) + \
            len(done_c if custom_tasks else [])
    pct   = round(done / total * 100) if total else 100

    lines += ["━" * 16,
              f"📈 СМЕНА ВЫПОЛНЕНА НА {pct}%"]

    text = "\n".join(lines)

    # Флористу
    await bot.send_message(fl["telegram_id"], text)

    # Директору с кнопками оценки
    d = db.get_director()
    if d:
        rating_kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔥 Огонь!", callback_data=f"shift_rate:fire:{florist_id}:{today}"),
            InlineKeyboardButton("👍 Хорошо",  callback_data=f"shift_rate:good:{florist_id}:{today}"),
        ],[
            InlineKeyboardButton("😐 Нормально", callback_data=f"shift_rate:ok:{florist_id}:{today}"),
            InlineKeyboardButton("😤 Плохо",     callback_data=f"shift_rate:bad:{florist_id}:{today}"),
        ]])
        await bot.send_message(d["telegram_id"], text, reply_markup=rating_kb)
async def cmd_zakryt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user or user["role"] != "florist": return
    if not db.has_shift(user["id"], TODAY()):
        await update.message.reply_text("Смена не открыта.")
        return
    if db.has_shift_closed(user["id"], TODAY()):
        await update.message.reply_text("Смена уже закрыта.")
        return
    ctx.user_data["closing_step"]          = "receipt"
    ctx.user_data["closing_shift_florist"] = user["id"]
    await update.message.reply_text("Закрытие смены!\n\n1️⃣ Пришли фото чека закрытия терминала:")


async def cmd_new_task(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user: return
    if user["role"] == "director":
        florists = db.get_florists()
        if not florists:
            await update.message.reply_text("Нет активных флористов.")
            return
        ctx.user_data["new_task_step"] = "pick_florist"
        await update.message.reply_text("Кому ставим задачу?", reply_markup=kb.task_florist_pick_kb(florists))
    else:
        ctx.user_data["new_task_step"]        = "text"
        ctx.user_data["new_task_assigned_to"] = user["id"]
        ctx.user_data["new_task_created_by"]  = user["id"]
        await update.message.reply_text("Опиши задачу:")


async def cmd_view_tasks(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user: return
    tasks = db.get_open_tasks() if user["role"] == "director" else db.get_open_tasks(user["id"])
    if not tasks:
        await update.message.reply_text("Открытых задач нет 🌸")
        return
    await update.message.reply_text(f"📋 Открытых задач: {len(tasks)}")
    for t in tasks:
        diff   = TASK_DIFFICULTY_LABELS.get(t.get("difficulty") or "normal", "")
        mand   = " 🔴 день в день" if t.get("mandatory") else ""
        photo  = " 📷 с фото" if t.get("require_photo") else ""
        who    = f"\nФлорист: {t['florist_name']}" if user["role"] == "director" else ""
        text   = (f"«{t.get('title') or '—'}»{who}\n"
                  f"{t['date']} {t['scheduled_time']} · {diff}{mand}{photo}")
        # Кнопки только для флориста (директор видит список для контроля)
        if user["role"] == "florist":
            await update.message.reply_text(
                text,
                reply_markup=kb.custom_task_kb(t["id"], require_photo=bool(t.get("require_photo"))))
        else:
            await update.message.reply_text(text)


async def cmd_bukет(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user or user["role"] != "florist":
        await update.message.reply_text("Эта команда только для флористов.")
        return
    ctx.user_data["adding_bouquet"] = True
    await update.message.reply_text("Пришли фото нового готового букета:")


async def cmd_kompoziciya(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user or user["role"] != "florist":
        await update.message.reply_text("Эта команда только для флористов.")
        return
    ctx.user_data["adding_composition"] = True
    await update.message.reply_text("Пришли фото новой готовой композиции:")


async def cmd_vitrina(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user: return
    bouquets = db.get_active_bouquets()
    if not bouquets:
        await update.message.reply_text("Активных букетов в витрине нет.")
        return
    import pytz as _ptz
    _msk = _ptz.timezone("Europe/Moscow")
    now  = datetime.now(_msk)
    await update.message.reply_text(f"Активных букетов в витрине: {len(bouquets)} шт.")
    for b in bouquets:
        try:
            created = datetime.fromisoformat(b["created_at"])
            if created.tzinfo is None:
                created = _msk.localize(created)
        except Exception:
            created = now
        days    = (now - created).days
        warn    = " ⚠️ Проверить!" if days >= 4 else ""
        caption = (f"Букет #{b['id']}\nФлорист: {b['florist_name']}\n"
                   f"Себестоимость: {b.get('cost', 0):,} ₽\nЦена: {b['price']:,} ₽\n"
                   f"В витрине: {days} дн.{warn}").replace(",", " ")
        kb_b = kb.bouquet_status_kb(b["id"])
        if b.get("photo_file_id"):
            await update.message.reply_photo(photo=b["photo_file_id"], caption=caption, reply_markup=kb_b)
        else:
            await update.message.reply_text(caption, reply_markup=kb_b)


async def cmd_vitrina_kompozicii(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user: return
    compositions = db.get_active_compositions()
    if not compositions:
        await update.message.reply_text("Активных композиций в витрине нет.")
        return
    import pytz as _ptz
    _msk       = _ptz.timezone("Europe/Moscow")
    now        = datetime.now(_msk)
    check_days = int(db.get_setting("composition_check_days", "4"))
    await update.message.reply_text(f"Активных композиций в витрине: {len(compositions)} шт.")
    for c in compositions:
        try:
            created = datetime.fromisoformat(c["created_at"])
            if created.tzinfo is None:
                created = _msk.localize(created)
        except Exception:
            created = now
        days    = (now - created).days
        warn    = " ⚠️ Пора разобрать!" if days >= check_days else ""
        caption = (f"Композиция #{c['id']}\nФлорист: {c['florist_name']}\n"
                   f"Себестоимость: {c.get('cost', 0):,} ₽\nЦена: {c['price']:,} ₽\n"
                   f"В витрине: {days} дн.{warn}").replace(",", " ")
        kb_c = kb.composition_status_kb(c["id"])
        if c.get("photo_file_id"):
            await update.message.reply_photo(photo=c["photo_file_id"], caption=caption, reply_markup=kb_c)
        else:
            await update.message.reply_text(caption, reply_markup=kb_c)


def format_custom_tasks_stats(tasks):
    total = len(tasks)
    if total == 0:
        return "📋 Разовые задачи: не ставились"
    done   = sum(1 for t in tasks if t["status"] in ("done", "rated"))
    no     = sum(1 for t in tasks if t["status"] == "no")
    pct    = round(done / total * 100)
    points = sum(TASK_DIFFICULTY_WEIGHTS.get(t.get("difficulty") or "normal", 2)
                 for t in tasks if t["status"] in ("done", "rated"))
    return (f"📋 Разовые задачи:\n"
            f"  Поставлено: {total} · Выполнено: {done} ({pct}%) · Не выполнено: {no}\n"
            f"  Баллы с учётом сложности: {points}")


async def cmd_my_kpi(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user or user["role"] != "florist": return
    ym    = datetime.now().strftime("%Y-%m")
    kpi   = calc_kpi(user["id"], ym)
    tasks = db.get_month_custom_tasks(ym, user["id"])
    await update.message.reply_text(
        format_kpi_for_florist(user["name"], kpi) + "\n\n" + format_custom_tasks_stats(tasks))


async def cmd_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_director(update.effective_user.id): return
    await update.message.reply_text("Собираю отчёт...")
    from claude_ai import generate_monthly_report
    report = generate_monthly_report(datetime.now().strftime("%Y-%m"))
    await update.message.reply_text(report)


async def cmd_kpi(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_director(update.effective_user.id): return
    ym = datetime.now().strftime("%Y-%m")
    for f in db.get_florists():
        kpi   = calc_kpi(f["id"], ym)
        tasks = db.get_month_custom_tasks(ym, f["id"])
        await update.message.reply_text(
            format_kpi_for_director(f["name"], kpi) + "\n\n" + format_custom_tasks_stats(tasks))


async def cmd_chasy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_director(update.effective_user.id): return
    ym         = datetime.now(_MSK).strftime("%Y-%m")
    standard_h = db.get_setting("standard_shift_hours", "12")
    lines      = [f"⏱ Часы и переработки — {ym}", f"Норма смены: {standard_h} ч\n"]
    for f in db.get_florists():
        shifts         = db.get_month_shifts(f["id"], ym)
        closed         = [s for s in shifts if s.get("closed_at")]
        total_worked   = sum(s.get("worked_minutes") or 0 for s in closed)
        total_overtime = sum(s.get("overtime_minutes") or 0 for s in closed)
        ot_shifts      = sum(1 for s in closed if (s.get("overtime_minutes") or 0) > 0)
        wh, wm = divmod(total_worked, 60)
        oh, om = divmod(total_overtime, 60)
        lines.append(
            f"{f['name']}:\n"
            f"  Смен закрыто: {len(closed)}\n"
            f"  Отработано всего: {wh}ч {wm}мин\n"
            f"  Переработка: {oh}ч {om}мин ({ot_shifts} смен с переработкой)\n")
    await update.message.reply_text("\n".join(lines))


async def cmd_sales(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user: return
    ym  = datetime.now().strftime("%Y-%m")
    pct = int(db.get_setting("overhead_pct", "25"))
    if user["role"] == "director":
        lines = [f"Продажи и прибыль — {ym}\n"]
        total_rev = 0; total_profit = 0
        for f in db.get_florists():
            bouquets     = db.get_month_bouquets(ym, f["id"])
            compositions = db.get_month_compositions(ym, f["id"])
            lines.append(format_sales_report(bouquets, f["name"], pct))
            lines.append(format_sales_report(compositions, f["name"] + " (композиции)", pct))
            lines.append("")
            for item in bouquets + compositions:
                if item["status"] in ("sold_studio", "sold_flowwow", "sold_discount"):
                    sp = item.get("sold_price") or item.get("price") or 0
                    sc = item.get("cost") or 0
                    total_rev    += sp
                    total_profit += sp - sc - int(sc * pct / 100)
        lines.append(f"ИТОГО:\nВыручка: {total_rev:,} ₽\nПрибыль: ~{total_profit:,} ₽".replace(",", " "))
        await update.message.reply_text("\n".join(lines))
    else:
        bouquets     = db.get_month_bouquets(ym, user["id"])
        compositions = db.get_month_compositions(ym, user["id"])
        await update.message.reply_text(
            format_sales_report(bouquets, user["name"], pct) + "\n\n" +
            format_sales_report(compositions, user["name"] + " (композиции)", pct))


async def cmd_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_director(update.effective_user.id): return
    await update.message.reply_text("Настройки:", reply_markup=kb.settings_main_kb())


async def cmd_manual_vitrina_bukety(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user or user["role"] != "florist": return
    ctx.user_data["manual_task_type"] = "vitrina_bouquets"
    await update.message.reply_text("Пришли фото витрины готовых букетов:")


async def cmd_manual_vitrina_komp(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user or user["role"] != "florist": return
    ctx.user_data["manual_task_type"] = "vitrina_compositions"
    await update.message.reply_text("Пришли фото витрины готовых композиций:")


async def cmd_manual_flowwow(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user or user["role"] != "florist": return
    ctx.user_data["manual_task_type"] = "flowwow"
    await update.message.reply_text("Пришли фото или скрин Flowwow:")


# ── Тестовые команды ─────────────────────────────────────

async def cmd_test_smena(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_director(update.effective_user.id): return
    florists = db.get_florists()
    await shift_prompt(ctx.bot, florists)
    await update.message.reply_text(f"Отправила кнопку смены {len(florists)} флористам.")

async def cmd_test_vitrina(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_director(update.effective_user.id): return
    today   = TODAY()
    workers = db.get_working_florists(today)
    if not workers:
        await update.message.reply_text("Нет флористов на смене сегодня.")
        return
    for f in workers:
        conn = db.get_conn(); cur = conn.cursor()
        cur.execute("DELETE FROM tasks WHERE assigned_to=%s AND type=%s AND date=%s",
                    (f["id"], "vitrina_bouquets", today))
        conn.commit(); cur.close(); conn.close()
        await send_task(ctx.bot, f, "vitrina_bouquets", NOWT())
    await update.message.reply_text(f"Отправила задачу витрины букетов {len(workers)} флористам.")

async def cmd_test_komp(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_director(update.effective_user.id): return
    today   = TODAY()
    workers = db.get_working_florists(today)
    if not workers:
        await update.message.reply_text("Нет флористов на смене сегодня.")
        return
    for f in workers:
        await send_task(ctx.bot, f, "vitrina_compositions", NOWT())
    await update.message.reply_text(f"Отправила задачу витрины композиций {len(workers)} флористам.")

async def cmd_test_flowwow(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_director(update.effective_user.id): return
    today   = TODAY()
    workers = db.get_working_florists(today)
    if not workers:
        await update.message.reply_text("Нет флористов на смене сегодня.")
        return
    for f in workers:
        await send_task(ctx.bot, f, "flowwow", NOWT())
    await update.message.reply_text(f"Отправила задачу Flowwow {len(workers)} флористам.")

async def cmd_test_buket4(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_director(update.effective_user.id): return
    bouquets = db.get_active_bouquets()
    if not bouquets:
        await update.message.reply_text("Нет активных букетов.")
        return
    for b in bouquets:
        caption = f"⚠️ ТЕСТ: Букет #{b['id']} — проверка день 4\nЦена: {b['price']:,} ₽ · Что с ним?".replace(",", " ")
        fl = db.get_user_by_id(b["florist_id"])
        if fl:
            if b.get("photo_file_id"):
                await ctx.bot.send_photo(fl["telegram_id"], photo=b["photo_file_id"],
                    caption=caption, reply_markup=kb.bouquet_check_kb(b["id"]))
            else:
                await ctx.bot.send_message(fl["telegram_id"], caption,
                    reply_markup=kb.bouquet_check_kb(b["id"]))
    await update.message.reply_text(f"Отправила напоминания по {len(bouquets)} букетам.")

async def cmd_test_buket6(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_director(update.effective_user.id): return
    bouquets = db.get_active_bouquets()
    if not bouquets:
        await update.message.reply_text("Нет активных букетов.")
        return
    for b in bouquets:
        caption = f"🔴 ТЕСТ: Букет #{b['id']} — день 6, пора разобрать!\nЦена: {b['price']:,} ₽".replace(",", " ")
        fl = db.get_user_by_id(b["florist_id"])
        if fl:
            if b.get("photo_file_id"):
                await ctx.bot.send_photo(fl["telegram_id"], photo=b["photo_file_id"],
                    caption=caption, reply_markup=kb.bouquet_check_kb(b["id"]))
            else:
                await ctx.bot.send_message(fl["telegram_id"], caption,
                    reply_markup=kb.bouquet_check_kb(b["id"]))
    await update.message.reply_text(f"Отправила напоминания день 6 по {len(bouquets)} букетам.")

async def cmd_test_kompoziciya4(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_director(update.effective_user.id): return
    compositions = db.get_active_compositions()
    if not compositions:
        await update.message.reply_text("Нет активных композиций.")
        return
    for c in compositions:
        caption = f"⚠️ ТЕСТ: Композиции #{c['id']} уже 4 дня — пора разобрать!\nЦена: {c['price']:,} ₽".replace(",", " ")
        fl = db.get_user_by_id(c["florist_id"])
        if fl:
            if c.get("photo_file_id"):
                await ctx.bot.send_photo(fl["telegram_id"], photo=c["photo_file_id"],
                    caption=caption, reply_markup=kb.composition_check_kb(c["id"]))
            else:
                await ctx.bot.send_message(fl["telegram_id"], caption,
                    reply_markup=kb.composition_check_kb(c["id"]))
    await update.message.reply_text(f"Отправила напоминания по {len(compositions)} композициям.")

async def cmd_test_reminder(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_director(update.effective_user.id): return
    florists = db.get_florists()
    for f in florists:
        try:
            await ctx.bot.send_message(f["telegram_id"], "🔴 ТЕСТ: Открой смену! Нажми /otkryt")
        except Exception as e:
            log.error(e)
    await update.message.reply_text(f"Отправила напоминание о смене {len(florists)} флористам.")


async def cmd_reset_users(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_director(update.effective_user.id): return
    conn = db.get_conn(); cur = conn.cursor()
    cur.execute("DELETE FROM tasks WHERE assigned_to IN (SELECT id FROM users WHERE role='florist')")
    cur.execute("DELETE FROM bouquets WHERE florist_id IN (SELECT id FROM users WHERE role='florist')")
    cur.execute("DELETE FROM compositions WHERE florist_id IN (SELECT id FROM users WHERE role='florist')")
    cur.execute("DELETE FROM shifts WHERE user_id IN (SELECT id FROM users WHERE role='florist')")
    cur.execute("DELETE FROM users WHERE role='florist'")
    conn.commit(); cur.close(); conn.close()
    await update.message.reply_text("Все флористы удалены. Теперь они могут зарегистрироваться заново через /start")


async def cmd_migrate_db(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_director(update.effective_user.id): return
    conn = db.get_conn(); cur = conn.cursor()
    try:
        cur.execute("ALTER TABLE shifts ADD COLUMN IF NOT EXISTS open_receipt_photo TEXT")
        cur.execute("ALTER TABLE shifts ADD COLUMN IF NOT EXISTS receipt_time TEXT")
        cur.execute("ALTER TABLE shifts ADD COLUMN IF NOT EXISTS late_type TEXT")
        cur.execute("ALTER TABLE bouquets ADD COLUMN IF NOT EXISTS cost INTEGER DEFAULT 0")
        cur.execute("ALTER TABLE bouquets ADD COLUMN IF NOT EXISTS sold_price INTEGER")
        conn.commit()
        await update.message.reply_text("База данных обновлена!")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")
    finally:
        cur.close(); conn.close()


async def cmd_debug(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_director(update.effective_user.id): return
    import pytz
    tz    = pytz.timezone("Europe/Moscow")
    now   = datetime.now(tz)
    today = now.date().isoformat()
    t     = now.hour * 60 + now.minute
    lines = [
        f"Время МСК: {now.strftime('%H:%M:%S')}",
        f"Сегодня: {today}",
        f"Минут от 00:00: {t}",
    ]
    florists = db.get_florists()
    lines.append(f"Флористов в базе: {len(florists)}")
    for f in florists:
        has_s = db.has_shift(f["id"], today)
        has_r = db.has_receipt(f["id"], today)
        lines.append(f"\n{f['name']}:\n  Смена: {'ДА' if has_s else 'НЕТ'}\n  Чек: {'ДА' if has_r else 'НЕТ'}")
    await update.message.reply_text("\n".join(lines))


async def cmd_test_alert(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_director(update.effective_user.id): return
    today    = TODAY()
    florists = db.get_florists()
    sent     = 0
    for f in florists:
        has_s = db.has_shift(f["id"], today)
        has_r = db.has_receipt(f["id"], today)
        if has_r:
            await update.message.reply_text(f"{f['name']} — чек уже получен")
            continue
        if not has_s:
            try:
                await ctx.bot.send_message(f["telegram_id"], "Открой смену!",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton(f"Начать смену — {f['name']}", callback_data=f"shift:{f['id']}")
                    ]]))
                sent += 1
            except Exception as e:
                await update.message.reply_text(f"Ошибка {f['name']}: {e}")
        else:
            try:
                await ctx.bot.send_message(f["telegram_id"], "Не забудь прислать фото чека с терминала!")
                sent += 1
            except Exception as e:
                await update.message.reply_text(f"Ошибка {f['name']}: {e}")
    await update.message.reply_text(f"Отправила {sent} алертов.")


async def cmd_pravila(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user or user["role"] != "florist": return
    ym    = datetime.now(_MSK).strftime("%Y-%m")
    lates = db.get_month_lates(user["id"], ym)
    max_light  = int(db.get_setting("kpi_late_light_max",  "4"))
    max_medium = int(db.get_setting("kpi_late_medium_max", "3"))
    max_heavy  = int(db.get_setting("kpi_late_heavy_max",  "2"))
    l = lates.get("light", 0); m = lates.get("medium", 0)
    h = lates.get("heavy", 0); n = lates.get("no_show", 0)
    def bar(cur, mx):
        if mx == 0: return "🟢"
        pct = cur / mx
        if pct == 0: return "🟢"
        elif pct < 0.5: return "🟡"
        elif pct < 1.0: return "🟠"
        else: return "🔴"
    fine = 0; warn = []
    if n >= 1:            fine = 2000; warn.append("После 11:00 — штраф начислен!")
    elif h >= max_heavy:  fine = 2000; warn.append(f"Серьёзных {h}/{max_heavy} — штраф!")
    elif m >= max_medium: fine = 2000; warn.append(f"Средних {m}/{max_medium} — штраф!")
    elif l >= max_light:  fine = 2000; warn.append(f"Лёгких {l}/{max_light} — штраф!")
    sep = "—" * 20
    lines = [
        f"📋 Правила студии REN · {ym}", "",
        "🕐 СМЕНА",
        "  Открытие: в 10:00 кнопка «Начать смену»",
        "  После нажатия — фото чека с терминала",
        "  До 10:05 = вовремя · После 10:05 = опоздание",
        "  Закрытие: в 21:00 кнопка «Закрыть смену»",
        "  → фото чека + 2 фото холодильника", "",
        "⏰ ОПОЗДАНИЯ И ШТРАФЫ",
        f"  ✅ До 10:05 — вовремя",
        f"  🟡 10:05–10:15 — лёгкое · штраф на {max_light}-й раз (-2 000 ₽)",
        f"  🟠 10:15–10:30 — среднее · штраф на {max_medium}-й раз (-2 000 ₽)",
        f"  🔴 10:30–11:00 — серьёзное · штраф на {max_heavy}-й раз (-2 000 ₽)",
        f"  🔴 После 11:00 — каждый раз -2 000 ₽", "",
        f"Моя статистика опозданий · {ym}:",
        f"  {bar(l, max_light-1)} Лёгких: {l} / {max_light-1} допустимых",
        f"  {bar(m, max_medium-1)} Средних: {m} / {max_medium-1} допустимых",
        f"  {bar(h, max_heavy-1)} Серьёзных: {h} / {max_heavy-1} допустимых",
        f"  {'🔴' if n else '🟢'} После 11:00: {n}",
        ("\n⚠️ " + " | ".join(warn) + f"\nШтраф: -{fine} ₽") if warn else "\n✅ Штрафов нет!", "",
        sep, "🌸 ЕЖЕДНЕВНЫЕ ОТЧЁТЫ",
        f"  {db.get_setting('vitrina_bouquets_time', '14:00')} — Витрина букетов (фото)",
        f"  {db.get_setting('vitrina_compositions_time', '18:00')} — Витрина композиций (фото)",
        f"  {db.get_setting('flowwow_time', '15:00')} — Flowwow через день (фото/скрин)",
        "  Допустимо пропустить: ≤3 раза в месяц",
        "  На витрине минимум 6 активных букетов", "",
        sep, "🌹 БУКЕТЫ",
        "  /buket → фото → себестоимость, цена",
        "  День 4 — проверить · День 6 — разобрать", "",
        sep, "📊 KPI",
        "  ✅ ≤3 пропусков по каждому отчёту",
        "  ✅ Качество: менее 30% оценок «Плохо»",
        "  ✅ Опоздания: не превышены пороги",
    ]
    await update.message.reply_text("\n".join(lines))


async def cmd_reset_tasks(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_director(update.effective_user.id): return
    from database import get_conn
    today = TODAY()
    conn = get_conn(); cur = conn.cursor()
    cur.execute("DELETE FROM tasks WHERE date=%s", (today,))
    conn.commit(); cur.close(); conn.close()
    await update.message.reply_text(f"Все задачи за {today} удалены.")
