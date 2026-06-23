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
TODAY  = lambda: date.today().isoformat()
NOW    = lambda: datetime.now().isoformat()
NOWT   = lambda: datetime.now().strftime("%H:%M")

TASK_LABELS = {
    "vitrina_bouquets":     "Витрина готовых букетов",
    "vitrina_compositions": "Витрина готовых композиций",
    "flowwow":              "Flowwow",
}
RATING_LABELS = {0: "👎 Плохо", 1: "👌 Норм", 2: "⭐ Отлично"}

def is_director(tid): u = db.get_user(tid); return u and u["role"] == "director"
def is_florist(tid):  u = db.get_user(tid); return u and u["role"] == "florist"

async def send_to_director(bot, text, reply_markup=None, photo=None):
    d = db.get_director()
    if not d: return None
    if photo:
        return await bot.send_photo(d["telegram_id"], photo=photo, caption=text, reply_markup=reply_markup)
    return await bot.send_message(d["telegram_id"], text, reply_markup=reply_markup)

def get_late_type(receipt_time_str):
    """Определяет тип опоздания по времени чека."""
    try:
        t = datetime.strptime(receipt_time_str, "%H:%M").time()
    except:
        return "no_show"
    deadline = dtime(10, 3)
    if t <= deadline:
        return None  # вовремя
    elif t <= dtime(10, 15):
        return "light"
    elif t <= dtime(10, 30):
        return "medium"
    elif t <= dtime(11, 0):
        return "heavy"
    else:
        return "no_show"

LATE_LABELS = {
    "light":   "лёгкое (10:03–10:15)",
    "medium":  "опоздание (10:15–10:30)",
    "heavy":   "серьёзное (10:30–11:00)",
    "no_show": "критическое (после 11:00)",
}

DIRECTOR_COMMANDS = [
    BotCommand("otchet",    "Полный отчёт"),
    BotCommand("kpi",       "KPI флористов"),
    BotCommand("prodazhi",  "Продажи и прибыль"),
    BotCommand("vitrina",   "Активные букеты"),
    BotCommand("nastroyki", "Настройки"),
]

FLORIST_COMMANDS = [
    BotCommand("otkryt",          "Открыть смену"),
    BotCommand("buket",           "Добавить букет"),
    BotCommand("vitrina",         "Мои активные букеты"),
    BotCommand("moy_kpi",         "Мой KPI за месяц"),
    BotCommand("vitrina_bukety",  "Отчёт витрины букетов"),
    BotCommand("vitrina_komp",    "Отчёт витрины композиций"),
    BotCommand("flowwow_otchet",  "Отчёт Flowwow"),
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
    name    = update.message.text.strip()
    tid     = update.effective_user.id
    director = db.get_director()
    role    = "director" if not director else "florist"
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
    return "/otchet /kpi /prodazhi /vitrina /nastroyki\nЛюбой текст — вопрос Claude"

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
                            f"🟢 Начать смену — {f['name']}",
                            callback_data=f"shift:{f['id']}")
                    ]]))
            except Exception as e:
                log.error(e)


async def send_task(bot, florist, task_type, scheduled_time):
    today = TODAY()
    if db.get_pending_task(florist["id"], task_type, today): return
    if not db.has_shift(florist["id"], today): return
    task_id = db.create_task(task_type, florist["id"], today, scheduled_time)
    texts = {
        "vitrina_bouquets":     "14:00 — Витрина готовых букетов!\nПришли фото:",
        "vitrina_compositions": "18:00 — Витрина готовых композиций!\nПришли фото:",
        "flowwow":              "15:00 — Пора обновить Flowwow!\nПришли фото или скрин:",
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
        # Уведомление директору
        user = db.get_user_by_id(task["assigned_to"])
        label = TASK_LABELS.get(task_type, task_type)
        await send_to_director(ctx.bot,
            f"⏳ {user['name'] if user else '?'} нажала «Через час»\n"
            f"Задача: {label} ({task['scheduled_time']})")
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
            # Запросить фактическую цену
            ctx.user_data["sell_bouquet_id"]  = bouquet_id
            ctx.user_data["sell_channel"]     = channel
            if channel == "flowwow":
                await q.message.reply_text(f"Букет #{bouquet_id}\nВведи фактическую цену продажи на Flowwow:")
            else:
                await q.message.reply_text(f"Букет #{bouquet_id}\nВведи новую цену продажи (со скидкой):")
        else:
            # Продан в студии по обычной цене
            sold_price = bouquet["price"]
            db.update_bouquet(bouquet_id, status="sold_studio", sale_channel="studio",
                              sold_at=NOW(), sold_price=sold_price)
            profit = sold_price - (bouquet.get("cost") or 0)
            await q.message.edit_text(
                f"✅ Букет #{bouquet_id} продан в студии!\nЦена: {sold_price:,} ₽ · Прибыль: {profit:,} ₽".replace(",", " "),
                reply_markup=None)
            fl = db.get_user_by_id(bouquet["florist_id"])
            await send_to_director(ctx.bot,
                f"💰 Букет #{bouquet_id} продан в студии\n"
                f"Флорист: {fl['name'] if fl else '—'}\n"
                f"Цена: {sold_price:,} ₽ · Прибыль: ~{profit:,} ₽".replace(",", " "))

    # Разобрать
    elif data.startswith("bdisassemble:"):
        bouquet_id = int(data.split(":")[1])
        bouquet = db.get_bouquet(bouquet_id)
        if not bouquet: return
        db.update_bouquet(bouquet_id, status="disassembled", disassembled_at=NOW())
        await q.message.edit_text(f"🗑 Букет #{bouquet_id} разобран — цветы пойдут в новый букет.", reply_markup=None)
        fl = db.get_user_by_id(bouquet["florist_id"])
        await send_to_director(ctx.bot,
            f"🗑 Букет #{bouquet_id} разобран\nФлорист: {fl['name'] if fl else '—'}")

    # Букет проверен
    elif data.startswith("bcheck:"):
        bouquet_id = int(data.split(":")[1])
        db.update_bouquet(bouquet_id, checked_at=NOW())
        await q.message.edit_text(f"👍 Букет #{bouquet_id} проверен — всё хорошо, продаётся дальше!", reply_markup=None)
        bouquet = db.get_bouquet(bouquet_id)
        fl = db.get_user_by_id(bouquet["florist_id"]) if bouquet else None
        await send_to_director(ctx.bot,
            f"👍 Букет #{bouquet_id} проверен на {int(db.get_setting('bouquet_check_days','4'))}-й день\n"
            f"Флорист: {fl['name'] if fl else '—'} — продаётся дальше")

    # Настройки
    elif data.startswith("settings:"):
        section = data.split(":")[1]
        if section == "main":    await q.message.edit_text("Настройки:", reply_markup=kb.settings_main_kb())
        elif section == "times": await q.message.edit_text("Время напоминаний:", reply_markup=kb.settings_times_kb())
        elif section == "kpi":   await q.message.edit_text("Пороги KPI:", reply_markup=kb.settings_kpi_kb())
        elif section == "bouquet": await q.message.edit_text("Срок букета:", reply_markup=kb.settings_bouquet_kb())

    elif data.startswith("setval:"):
        if not is_director(q.from_user.id): return
        setting_key = data.split(":")[1]
        current = db.get_setting(setting_key, "—")
        ctx.user_data["setting_key"] = setting_key
        label = kb.SETTING_LABELS.get(setting_key, setting_key)
        await q.message.edit_text(f"Текущее: {current}\nВведи новое {label}:")


# ── Photo handler ──────────────────────────────────────────

async def photo_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user: return
    file_id = update.message.photo[-1].file_id

    # Фото чека открытия смены
    if "waiting_receipt" in ctx.user_data:
        florist_id = ctx.user_data.pop("waiting_receipt")
        shift_date = ctx.user_data.pop("receipt_shift_date", TODAY())
        now_time   = NOWT()
        late_type  = get_late_type(now_time)

        db.update_shift(florist_id, shift_date,
                        open_receipt_photo=file_id,
                        receipt_time=now_time,
                        late_type=late_type)

        if late_type is None:
            status_text = f"✅ Вовремя ({now_time})"
            florist_msg = f"✅ Смена открыта в {now_time} — вовремя!"
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
            status_text = f"⚠️ Опоздание — {label}"
            florist_msg = (f"⚠️ Смена открыта в {now_time}\n"
                           f"Опоздание зафиксировано: {label}\n"
                           f"Таких в этом месяце: {late_count} из {max_v} допустимых")

        await update.message.reply_text(florist_msg)
        await send_to_director(ctx.bot,
            f"{'✅' if late_type is None else '⚠️'} {user['name']} открыла смену в {now_time}\n{status_text}",
            photo=file_id)
        return

    # Фото задачи
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
        ctx.user_data["bouquet_photo"]    = file_id
        ctx.user_data["adding_bouquet"]   = False
        ctx.user_data["bouquet_cost_step"] = True
        await update.message.reply_text(
            "Введи через запятую: себестоимость, цена продажи\n"
            "Например: 2000, 3500")
        return

    await update.message.reply_text("Используй /buket для нового букета или команды витрины.")


# ── Text handler ───────────────────────────────────────────

async def text_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Напиши /start чтобы зарегистрироваться.")
        return
    text = update.message.text.strip()

    # Причина невыполнения задачи
    if "reason_task_id" in ctx.user_data:
        task_id = ctx.user_data.pop("reason_task_id")
        db.update_task(task_id, no_reason=text, status="no")
        await update.message.reply_text("Записала.")
        task = db.get_task(task_id)
        label = TASK_LABELS.get(task["type"], task["type"]) if task else "задача"
        await send_to_director(ctx.bot,
            f"❌ Задача не выполнена — {user['name']}\n{label}\nПричина: {text}")
        return

    # Себестоимость и цена букета одним сообщением
    if ctx.user_data.get("bouquet_cost_step"):
        try:
            parts = [p.strip().replace(" ","") for p in text.replace(",",",").split(",")]
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
            await ctx.bot.send_photo(d["telegram_id"], photo=photo,
                caption=f"🌸 Новый букет #{bouquet_id}\n"
                        f"Флорист: {user['name']}\n"
                        f"Себестоимость: {cost:,} ₽ · Цена: {price:,} ₽\n\nОцени:".replace(",", " "),
                reply_markup=kb.bouquet_rating_kb(bouquet_id))
        return

    # Новая цена продажи (скидка или Flowwow)
    if "sell_bouquet_id" in ctx.user_data:
        bouquet_id = ctx.user_data.pop("sell_bouquet_id")
        channel    = ctx.user_data.pop("sell_channel", "discount")
        try:
            sold_price = int(text.replace(" ",""))
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
        orig  = bouquet["price"]
        profit = sold_price - (bouquet.get("cost") or 0)
        if channel == "flowwow":
            ch_label = "на Flowwow"
        else:
            ch_label = f"в студии со скидкой (было {orig:,} ₽)".replace(",", " ")
        await update.message.reply_text(
            f"✅ Букет #{bouquet_id} продан {ch_label}!\nЦена: {sold_price:,} ₽".replace(",", " "),
            reply_markup=None)
        fl = db.get_user_by_id(bouquet["florist_id"])
        await send_to_director(ctx.bot,
            f"{'🛍' if channel=='flowwow' else '🏷'} Букет #{bouquet_id} продан {ch_label}\n"
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


async def cmd_bukет(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user or user["role"] != "florist":
        await update.message.reply_text("Эта команда только для флористов.")
        return
    ctx.user_data["adding_bouquet"] = True
    await update.message.reply_text("Пришли фото нового готового букета:")


async def cmd_vitrina(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user: return
    fid      = user["id"] if user["role"] == "florist" else None
    bouquets = db.get_active_bouquets(fid)
    if not bouquets:
        await update.message.reply_text("Активных букетов в витрине нет.")
        return
    now = datetime.now()
    await update.message.reply_text(f"Активных букетов: {len(bouquets)} шт.")
    for b in bouquets:
        created = datetime.fromisoformat(b["created_at"])
        days    = (now - created).days
        warn    = " ⚠️" if days >= 4 else ""
        info    = f"Флорист: {b['florist_name']}\n" if user["role"] == "director" else ""
        caption = (f"Букет #{b['id']}\n{info}"
                   f"Себестоимость: {b.get('cost',0):,} ₽\n"
                   f"Цена: {b['price']:,} ₽\n"
                   f"В витрине: {days} дн.{warn}").replace(",", " ")
        kb_b = kb.bouquet_status_kb(b["id"]) if user["role"] == "florist" else None
        if b.get("photo_file_id"):
            await update.message.reply_photo(photo=b["photo_file_id"], caption=caption, reply_markup=kb_b)
        else:
            await update.message.reply_text(caption, reply_markup=kb_b)


async def cmd_my_kpi(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user or user["role"] != "florist": return
    ym  = datetime.now().strftime("%Y-%m")
    kpi = calc_kpi(user["id"], ym)
    await update.message.reply_text(format_kpi_for_florist(user["name"], kpi))


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
        kpi = calc_kpi(f["id"], ym)
        await update.message.reply_text(format_kpi_for_director(f["name"], kpi))


async def cmd_sales(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user: return
    ym  = datetime.now().strftime("%Y-%m")
    pct = int(db.get_setting("overhead_pct", "25"))
    if user["role"] == "director":
        lines = [f"Продажи и прибыль — {ym}\n"]
        total_rev = 0; total_profit = 0
        for f in db.get_florists():
            bouquets = db.get_month_bouquets(ym, f["id"])
            lines.append(format_sales_report(bouquets, f["name"], pct))
            lines.append("")
            for b in bouquets:
                if b["status"] in ("sold_studio","sold_flowwow","sold_discount"):
                    sp = b.get("sold_price") or b.get("price") or 0
                    sc = b.get("cost") or 0
                    total_rev    += sp
                    total_profit += sp - sc - int(sc * pct / 100)
        lines.append(f"ИТОГО:\nВыручка: {total_rev:,} ₽\nПрибыль: ~{total_profit:,} ₽".replace(",", " "))
        await update.message.reply_text("\n".join(lines))
    else:
        bouquets = db.get_month_bouquets(ym, user["id"])
        await update.message.reply_text(format_sales_report(bouquets, user["name"], pct))


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
