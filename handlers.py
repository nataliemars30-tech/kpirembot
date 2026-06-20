import logging
from datetime import datetime, date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

import database as db
import keyboards as kb
from kpi import calc_kpi, format_kpi_for_florist, format_kpi_for_director, format_sales_report
from claude_ai import ask_claude
from config import REGISTER_NAME

log = logging.getLogger(__name__)

TODAY = lambda: date.today().isoformat()
NOW   = lambda: datetime.now().isoformat()

TASK_LABELS = {
    "vitrina_bouquets":     "Витрина готовых букетов",
    "vitrina_compositions": "Витрина готовых композиций",
    "flowwow":              "Flowwow",
}

def is_director(tid): u = db.get_user(tid); return u and u["role"] == "director"
def is_florist(tid):  u = db.get_user(tid); return u and u["role"] == "florist"

async def send_to_director(bot, text, reply_markup=None, photo=None):
    d = db.get_director()
    if not d: return None
    if photo:
        return await bot.send_photo(d["telegram_id"], photo=photo, caption=text, reply_markup=reply_markup)
    return await bot.send_message(d["telegram_id"], text, reply_markup=reply_markup)


# ── /start ────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if user:
        role = "директор" if user["role"] == "director" else "флорист"
        await update.message.reply_text(
            f"Привет, {user['name']}! Ты уже зарегистрирована как {role}.\n\n"
            + (_director_help() if user["role"] == "director" else _florist_help())
        )
        return ConversationHandler.END
    await update.message.reply_text("Добро пожаловать в REN Bot!\n\nКак тебя зовут?")
    return REGISTER_NAME


async def register_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    name    = update.message.text.strip()
    tid     = update.effective_user.id
    director = db.get_director()
    role    = "director" if not director else "florist"
    db.create_user(tid, name, role)
    if role == "director":
        await update.message.reply_text(
            f"{name}, ты зарегистрирована как директор!\n\n" + _director_help()
        )
    else:
        await update.message.reply_text(
            f"{name}, ты зарегистрирована как флорист!\n\n" + _florist_help()
        )
        if director:
            await ctx.bot.send_message(director["telegram_id"],
                f"Новый флорист зарегистрирован: {name}")
    return ConversationHandler.END


def _director_help():
    return (
        "Команды:\n"
        "/otchet — полный отчёт\n"
        "/kpi — KPI флористов\n"
        "/prodazhi — продажи букетов\n"
        "/vitrina — активные букеты\n"
        "/nastroyki — настройки\n"
        "Любой текст — вопрос Claude"
    )

def _florist_help():
    return (
        "Команды:\n"
        "/buket — добавить новый букет\n"
        "/vitrina — мои активные букеты\n"
        "/moy_kpi — мой KPI за месяц\n"
        "/vitrina_bukety — отчёт витрины букетов\n"
        "/vitrina_komp — отчёт витрины композиций\n"
        "/flowwow_otchet — отчёт Flowwow"
    )


# ── Shift ─────────────────────────────────────────────────

async def shift_prompt(bot, florists):
    for f in florists:
        if not db.has_shift(f["id"], TODAY()):
            try:
                await bot.send_message(
                    f["telegram_id"],
                    "Доброе утро! Начни смену:",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton(
                            f"Начать смену — {f['name']}",
                            callback_data=f"shift:{f['id']}"
                        )
                    ]])
                )
            except Exception as e:
                log.error(e)


# ── Send task ──────────────────────────────────────────────

async def send_task(bot, florist, task_type, scheduled_time):
    today = TODAY()
    if db.get_pending_task(florist["id"], task_type, today):
        return
    if not db.has_shift(florist["id"], today):
        return
    task_id = db.create_task(task_type, florist["id"], today, scheduled_time)
    texts = {
        "vitrina_bouquets":     f"14:00 — Витрина готовых букетов!\nПришли фото:",
        "vitrina_compositions": f"18:00 — Витрина готовых композиций!\nПришли фото:",
        "flowwow":              f"15:00 — Пора обновить букеты на Flowwow!\nПришли фото или скрин:",
    }
    try:
        msg = await bot.send_message(
            florist["telegram_id"],
            texts.get(task_type, "Задача"),
            reply_markup=kb.task_response_kb(task_id, task_type)
        )
        db.update_task(task_id, florist_msg_id=msg.message_id)
    except Exception as e:
        log.error(e)


# ── Callbacks ──────────────────────────────────────────────

async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    await q.answer()
    data = q.data
    user = db.get_user(q.from_user.id)

    if data.startswith("shift:"):
        florist_id = int(data.split(":")[1])
        fu = db.get_user_by_id(florist_id)
        if not fu or fu["telegram_id"] != q.from_user.id:
            return
        if db.start_shift(florist_id, TODAY()):
            await q.message.edit_text(f"Смена начата! Удачного дня, {fu['name']}")
            await send_to_director(ctx.bot, f"{fu['name']} начала смену")
        else:
            await q.message.edit_text("Смена уже начата.")

    elif data.startswith("task_done:"):
        _, task_id, task_type = data.split(":")
        task_id = int(task_id)
        task = db.get_task(task_id)
        if not task or task["status"] in ("done", "rated", "submitted"):
            return
        db.update_task(task_id, status="waiting_photo")
        await q.message.edit_text("Отлично! Пришли фото.", reply_markup=None)
        ctx.user_data["pending_task_id"]   = task_id
        ctx.user_data["pending_task_type"] = task_type

    elif data.startswith("task_hour:"):
        _, task_id, task_type = data.split(":")
        task_id = int(task_id)
        db.update_task(task_id, status="in_hour", in_hour_at=NOW())
        await q.message.edit_text("Хорошо! Напомню через час.")
        import asyncio
        async def remind():
            await asyncio.sleep(3600)
            t = db.get_task(task_id)
            if t and t["status"] == "in_hour":
                try:
                    await ctx.bot.send_message(
                        q.from_user.id,
                        "Час прошёл! Как дела с задачей?",
                        reply_markup=kb.task_after_hour_kb(task_id, task_type)
                    )
                except: pass
        asyncio.create_task(remind())

    elif data.startswith("task_no:"):
        _, task_id, task_type = data.split(":")
        db.update_task(int(task_id), status="no")
        await q.message.edit_text("Понятно. Напиши причину:")
        ctx.user_data["reason_task_id"] = int(task_id)

    elif data.startswith("rate:"):
        _, rating, task_id = data.split(":")
        rating, task_id = int(rating), int(task_id)
        if not is_director(q.from_user.id): return
        db.update_task(task_id, rating=rating, status="rated", rated_at=NOW())
        labels = {0: "Плохо", 1: "Норм", 2: "Отлично"}
        txt = f"\n\nОценка: {labels[rating]}"
        try:
            await q.message.edit_caption((q.message.caption or "") + txt, reply_markup=None)
        except:
            await q.message.edit_text((q.message.text or "") + txt, reply_markup=None)
        task = db.get_task(task_id)
        if task:
            fl = db.get_user_by_id(task["assigned_to"])
            if fl:
                await ctx.bot.send_message(fl["telegram_id"],
                    f"Оценка получена: {labels[rating]}")

    elif data.startswith("brate:"):
        _, rating, bouquet_id = data.split(":")
        rating, bouquet_id = int(rating), int(bouquet_id)
        if not is_director(q.from_user.id): return
        db.update_bouquet(bouquet_id, director_rating=rating)
        labels = {0: "Плохо", 1: "Норм", 2: "Отлично"}
        try:
            await q.message.edit_caption(
                (q.message.caption or "") + f"\n\nОценка: {labels[rating]}",
                reply_markup=None
            )
        except:
            await q.message.edit_text(
                (q.message.text or "") + f"\n\nОценка: {labels[rating]}",
                reply_markup=None
            )

    elif data.startswith("bsell:"):
        _, channel, bouquet_id = data.split(":")
        bouquet_id = int(bouquet_id)
        bouquet = db.get_bouquet(bouquet_id)
        if not bouquet or bouquet["status"] != "in_vitrina":
            await q.message.reply_text("Этот букет уже не в витрине.")
            return
        db.update_bouquet(bouquet_id,
            status=f"sold_{channel}", sale_channel=channel, sold_at=NOW())
        ch = "в студии" if channel == "studio" else "на Flowwow"
        await q.message.edit_text(
            f"Букет #{bouquet_id} продан {ch}!\nЦена: {bouquet['price']} руб.",
            reply_markup=None
        )
        fl = db.get_user_by_id(bouquet["florist_id"])
        await send_to_director(ctx.bot,
            f"Букет #{bouquet_id} продан {ch}\n"
            f"Флорист: {fl['name'] if fl else '-'}\n"
            f"Сумма: {bouquet['price']} руб."
        )

    elif data.startswith("bdisassemble:"):
        bouquet_id = int(data.split(":")[1])
        bouquet = db.get_bouquet(bouquet_id)
        if not bouquet: return
        db.update_bouquet(bouquet_id, status="disassembled", disassembled_at=NOW())
        await q.message.edit_text(f"Букет #{bouquet_id} разобран.", reply_markup=None)
        fl = db.get_user_by_id(bouquet["florist_id"])
        await send_to_director(ctx.bot,
            f"Букет #{bouquet_id} разобран\n"
            f"Флорист: {fl['name'] if fl else '-'}\n"
            f"Потеря: {bouquet['price']} руб."
        )

    elif data.startswith("bcheck:"):
        bouquet_id = int(data.split(":")[1])
        db.update_bouquet(bouquet_id, checked_at=NOW())
        await q.message.edit_text(
            f"Букет #{bouquet_id} проверен — всё хорошо!", reply_markup=None)
        await send_to_director(ctx.bot,
            f"Букет #{bouquet_id} проверен на 4-й день — в порядке.")

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

    elif data.startswith("setval:"):
        if not is_director(q.from_user.id): return
        setting_key = data.split(":")[1]
        current = db.get_setting(setting_key, "-")
        ctx.user_data["setting_key"] = setting_key
        await q.message.edit_text(
            f"Текущее значение: {current}\nВведи новое:")


# ── Photo handler ──────────────────────────────────────────

async def photo_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user: return
    file_id = update.message.photo[-1].file_id

    # Scheduled task photo
    if "pending_task_id" in ctx.user_data:
        task_id   = ctx.user_data.pop("pending_task_id")
        task_type = ctx.user_data.pop("pending_task_type", "")
        db.update_task(task_id,
            status="submitted", photo_file_id=file_id, submitted_at=NOW())
        await update.message.reply_text("Фото получено! Отправляю директору.")
        d = db.get_director()
        if d:
            msg = await ctx.bot.send_photo(
                d["telegram_id"], photo=file_id,
                caption=(
                    f"{TASK_LABELS.get(task_type, task_type)}\n"
                    f"{user['name']} — {datetime.now().strftime('%d.%m %H:%M')}\n\n"
                    f"Оцени:"
                ),
                reply_markup=kb.rating_kb(task_id)
            )
            db.update_task(task_id, director_msg_id=msg.message_id)
        return

    # Manual report photo
    if "manual_task_type" in ctx.user_data:
        task_type = ctx.user_data.pop("manual_task_type")
        today     = TODAY()
        task_id   = db.create_task(task_type, user["id"], today,
                                   datetime.now().strftime("%H:%M"))
        db.update_task(task_id,
            status="submitted", photo_file_id=file_id, submitted_at=NOW())
        await update.message.reply_text("Фото получено! Отправляю директору на оценку.")
        d = db.get_director()
        if d:
            msg = await ctx.bot.send_photo(
                d["telegram_id"], photo=file_id,
                caption=(
                    f"[Ручной отчёт] {TASK_LABELS.get(task_type, task_type)}\n"
                    f"{user['name']} — {datetime.now().strftime('%d.%m %H:%M')}\n\n"
                    f"Оцени:"
                ),
                reply_markup=kb.rating_kb(task_id)
            )
            db.update_task(task_id, director_msg_id=msg.message_id)
        return

    # Bouquet photo
    if ctx.user_data.get("adding_bouquet"):
        ctx.user_data["bouquet_photo"]      = file_id
        ctx.user_data["adding_bouquet"]     = False
        ctx.user_data["bouquet_price_step"] = True
        await update.message.reply_text("Укажи цену букета (только цифры, например: 3500):")
        return

    await update.message.reply_text(
        "Используй /buket чтобы добавить букет, или дождись задачи по расписанию.")


# ── Text handler ───────────────────────────────────────────

async def text_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Напиши /start чтобы зарегистрироваться.")
        return
    text = update.message.text.strip()

    if "reason_task_id" in ctx.user_data:
        task_id = ctx.user_data.pop("reason_task_id")
        db.update_task(task_id, no_reason=text, status="no")
        await update.message.reply_text("Записала. Директор узнает о причине.")
        await send_to_director(ctx.bot,
            f"Задача не выполнена — {user['name']}\nПричина: {text}")
        return

    if ctx.user_data.get("bouquet_price_step"):
        try:
            price = int(text.replace(" ", "").replace("руб", "").replace("р", ""))
        except ValueError:
            await update.message.reply_text("Введи цену цифрами, например: 3500")
            return
        ctx.user_data["bouquet_price_step"] = False
        photo = ctx.user_data.pop("bouquet_photo", None)
        if not photo:
            await update.message.reply_text("Что-то пошло не так. Начни заново: /buket")
            return
        bouquet_id = db.create_bouquet(user["id"], photo, price)
        await update.message.reply_text(
            f"Букет #{bouquet_id} добавлен!\nЦена: {price} руб.\nОтправляю директору на оценку.",
            reply_markup=kb.bouquet_status_kb(bouquet_id)
        )
        d = db.get_director()
        if d:
            await ctx.bot.send_photo(
                d["telegram_id"], photo=photo,
                caption=(
                    f"Новый букет #{bouquet_id}\n"
                    f"Флорист: {user['name']}\n"
                    f"Цена: {price} руб.\n\nОцени:"
                ),
                reply_markup=kb.bouquet_rating_kb(bouquet_id)
            )
        return

    if "setting_key" in ctx.user_data and user["role"] == "director":
        key = ctx.user_data.pop("setting_key")
        db.set_setting(key, text)
        await update.message.reply_text(
            f"Сохранено: {key} = {text}", reply_markup=kb.settings_main_kb())
        return

    if user["role"] == "director":
        await update.message.reply_text("Анализирую данные...")
        response = ask_claude(text)
        await update.message.reply_text(f"Claude: {response}")
        return

    await update.message.reply_text(
        "Команды:\n"
        "/buket — новый букет\n"
        "/vitrina — активные букеты\n"
        "/moy_kpi — мой KPI\n"
        "/vitrina_bukety — отчёт витрины букетов\n"
        "/vitrina_komp — отчёт витрины композиций\n"
        "/flowwow_otchet — отчёт Flowwow"
    )


# ── Commands ───────────────────────────────────────────────

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
    now   = datetime.now()
    lines = ["Активные букеты:\n"]
    for b in bouquets:
        created = datetime.fromisoformat(b["created_at"])
        days    = (now - created).days
        warn    = " [проверить!]" if days >= 4 else ""
        info    = f" — {b['florist_name']}" if user["role"] == "director" else ""
        lines.append(f"Букет #{b['id']}{info} — {b['price']} руб. — {days} дн.{warn}")
    await update.message.reply_text("\n".join(lines))
    if user["role"] == "florist":
        for b in bouquets:
            await update.message.reply_text(
                f"Букет #{b['id']} — {b['price']} руб.",
                reply_markup=kb.bouquet_status_kb(b["id"])
            )


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
    if not is_director(update.effective_user.id): return
    ym         = datetime.now().strftime("%Y-%m")
    lines      = [f"Продажи букетов — {ym}\n"]
    total_sum  = 0
    total_loss = 0
    for f in db.get_florists():
        bouquets = db.get_month_bouquets(ym, f["id"])
        lines.append(format_sales_report(bouquets, f["name"]))
        lines.append("")
        total_sum  += sum(b["price"] for b in bouquets
                          if b["status"] in ("sold_studio", "sold_flowwow"))
        total_loss += sum(b["price"] for b in bouquets
                          if b["status"] == "disassembled")
    lines.append(
        f"Итого по студии:\n"
        f"Продано: {total_sum} руб.\n"
        f"Потери: {total_loss} руб."
    )
    await update.message.reply_text("\n".join(lines))


async def cmd_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_director(update.effective_user.id): return
    await update.message.reply_text("Настройки:", reply_markup=kb.settings_main_kb())


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user: return
    if user["role"] == "florist":
        await cmd_my_kpi(update, ctx)
    else:
        await cmd_report(update, ctx)


# ── Ручные отчёты флориста ────────────────────────────────

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
    await update.message.reply_text("Пришли фото или скрин выкладки на Flowwow:")
