import logging
from datetime import datetime, date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

import database as db
import keyboards as kb
from kpi import calc_kpi, format_kpi_for_florist, format_kpi_for_director, format_sales_report
from claude_ai import ask_claude
from config import (
    REGISTER_NAME, BOUQUET_PHOTO, BOUQUET_PRICE,
    TASK_PHOTO, TASK_REASON, SETTINGS_CHOOSE, SETTINGS_VALUE, FLOWWOW_PHOTO
)

log = logging.getLogger(__name__)

TODAY = lambda: date.today().isoformat()
NOW = lambda: datetime.now().isoformat()


def is_director(telegram_id):
    user = db.get_user(telegram_id)
    return user and user["role"] == "director"


def is_florist(telegram_id):
    user = db.get_user(telegram_id)
    return user and user["role"] == "florist"


async def send_to_director(bot, text, reply_markup=None, photo=None):
    director = db.get_director()
    if not director:
        return None
    if photo:
        msg = await bot.send_photo(director["telegram_id"], photo=photo, caption=text, reply_markup=reply_markup)
    else:
        msg = await bot.send_message(director["telegram_id"], text, reply_markup=reply_markup)
    return msg


# ── /start ───────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if user:
        await update.message.reply_text(
            f"Привет, {user['name']}! Ты уже зарегистрирован(а) как {'директор' if user['role']=='director' else 'флорист'}."
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "👋 Добро пожаловать в REN Bot!\n\nКак тебя зовут?"
    )
    return REGISTER_NAME


async def register_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    tg_id = update.effective_user.id

    director = db.get_director()
    role = "director" if not director else "florist"

    db.create_user(tg_id, name, role)

    if role == "director":
        await update.message.reply_text(
            f"✅ {name}, ты зарегистрирована как директор!\n\n"
            "Команды:\n"
            "/отчет — текущий отчёт\n"
            "/kpi — KPI за месяц\n"
            "/продажи — продажи букетов\n"
            "/настройки — настройки бота\n"
            "Или просто напиши вопрос — отвечу с анализом 🌸"
        )
    else:
        await update.message.reply_text(
            f"✅ {name}, ты зарегистрирована как флорист!\n\n"
            "Команды:\n"
            "/букет — добавить новый готовый букет\n"
            "/витрина — активные букеты\n"
            "/мой_кпи — мой KPI за месяц"
        )
        director = db.get_director()
        if director:
            await ctx.bot.send_message(
                director["telegram_id"],
                f"👩‍🌾 Новый флорист зарегистрирован: {name}"
            )

    return ConversationHandler.END


# ── Shift ────────────────────────────────────────────────

async def shift_prompt(bot, florists):
    """Send shift start prompt to all florists."""
    for f in florists:
        if not db.has_shift(f["id"], TODAY()):
            try:
                await bot.send_message(
                    f["telegram_id"],
                    "🌅 Доброе утро! Начни смену:",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton(
                            f"🟢 Начать смену — {f['name']}",
                            callback_data=f"shift:{f['id']}"
                        )
                    ]])
                )
            except Exception as e:
                log.error(f"shift_prompt error: {e}")


# ── Task sending ─────────────────────────────────────────

TASK_TEXTS = {
    "vitrina_bouquets": "🌸 14:00 — Витрина готовых букетов!\nПришли фото витрины и отметь статус:",
    "vitrina_compositions": "🎋 18:00 — Витрина готовых композиций!\nПришли фото витрины и отметь статус:",
    "flowwow": "🛍 15:00 — Пора обновить букеты на Flowwow!\nПришли фото/скрин и отметь статус:",
}


async def send_task(bot, florist, task_type, scheduled_time):
    today = TODAY()
    existing = db.get_pending_task(florist["id"], task_type, today)
    if existing:
        return

    if not db.has_shift(florist["id"], today):
        return  # Not their shift

    task_id = db.create_task(task_type, florist["id"], today, scheduled_time)
    text = TASK_TEXTS.get(task_type, "Задача")

    try:
        msg = await bot.send_message(
            florist["telegram_id"],
            text,
            reply_markup=kb.task_response_kb(task_id, task_type)
        )
        db.update_task(task_id, florist_msg_id=msg.message_id)

        # Schedule timeout
        timeout = int(db.get_setting("timeout_minutes", "30"))
        ctx_data = bot.application.bot_data
        if "pending_tasks" not in ctx_data:
            ctx_data["pending_tasks"] = {}
        ctx_data["pending_tasks"][task_id] = {
            "florist_id": florist["id"],
            "florist_tg": florist["telegram_id"],
            "task_type": task_type,
        }
    except Exception as e:
        log.error(f"send_task error: {e}")


# ── Callbacks ────────────────────────────────────────────

async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    user = db.get_user(q.from_user.id)

    # Shift start
    if data.startswith("shift:"):
        florist_id = int(data.split(":")[1])
        fu = db.get_user_by_id(florist_id)
        if not fu or fu["telegram_id"] != q.from_user.id:
            await q.message.reply_text("Это не твоя кнопка.")
            return
        started = db.start_shift(florist_id, TODAY())
        if started:
            await q.message.edit_text(f"✅ Смена начата! Удачного дня, {fu['name']} 🌸")
            await send_to_director(ctx.bot, f"🚀 {fu['name']} начала смену")
        else:
            await q.message.edit_text("Смена уже начата ранее.")

    # Task done
    elif data.startswith("task_done:"):
        _, task_id, task_type = data.split(":")
        task_id = int(task_id)
        task = db.get_task(task_id)
        if not task or task["status"] in ("done", "rated"):
            return
        db.update_task(task_id, status="waiting_photo")
        await q.message.edit_text(
            "✅ Отлично! Пришли фото витрины.",
            reply_markup=None
        )
        ctx.user_data["pending_task_id"] = task_id
        ctx.user_data["pending_task_type"] = task_type

    # Task in hour
    elif data.startswith("task_hour:"):
        _, task_id, task_type = data.split(":")
        task_id = int(task_id)
        task = db.get_task(task_id)
        if not task:
            return
        db.update_task(task_id, status="in_hour", in_hour_at=NOW())
        await q.message.edit_text("⏳ Хорошо! Напомню через час.")

        async def remind_later():
            import asyncio
            await asyncio.sleep(3600)
            t = db.get_task(task_id)
            if t and t["status"] == "in_hour":
                try:
                    await ctx.bot.send_message(
                        q.from_user.id,
                        f"⏰ Час прошёл! Как дела с задачей?",
                        reply_markup=kb.task_after_hour_kb(task_id, task_type)
                    )
                except Exception as e:
                    log.error(e)

        import asyncio
        asyncio.create_task(remind_later())

    # Task not ready
    elif data.startswith("task_no:"):
        _, task_id, task_type = data.split(":")
        task_id = int(task_id)
        db.update_task(task_id, status="no")
        await q.message.edit_text("❌ Понятно. Напиши причину:")
        ctx.user_data["reason_task_id"] = task_id

    # Rating task
    elif data.startswith("rate:"):
        _, rating, task_id = data.split(":")
        rating = int(rating)
        task_id = int(task_id)
        if not is_director(q.from_user.id):
            return
        db.update_task(task_id, rating=rating, status="rated", rated_at=NOW())
        labels = {0: "👎 Плохо", 1: "👌 Норм", 2: "⭐ Отлично"}
        await q.message.edit_caption(
            f"{q.message.caption or ''}\n\nОценка: {labels[rating]}",
            reply_markup=None
        ) if q.message.photo else await q.message.edit_text(
            f"{q.message.text}\n\nОценка: {labels[rating]}",
            reply_markup=None
        )
        task = db.get_task(task_id)
        if task:
            florist = db.get_user_by_id(task["assigned_to"])
            if florist:
                await ctx.bot.send_message(
                    florist["telegram_id"],
                    f"Оценка получена: {labels[rating]}"
                )

    # Bouquet rating
    elif data.startswith("brate:"):
        _, rating, bouquet_id = data.split(":")
        rating = int(rating)
        bouquet_id = int(bouquet_id)
        if not is_director(q.from_user.id):
            return
        db.update_bouquet(bouquet_id, director_rating=rating)
        labels = {0: "👎 Плохо", 1: "👌 Норм", 2: "⭐ Отлично"}
        await q.message.edit_caption(
            f"{q.message.caption or ''}\n\nОценка: {labels[rating]}",
            reply_markup=None
        )

    # Bouquet sell
    elif data.startswith("bsell:"):
        _, channel, bouquet_id = data.split(":")
        bouquet_id = int(bouquet_id)
        bouquet = db.get_bouquet(bouquet_id)
        if not bouquet or bouquet["status"] != "in_vitrina":
            await q.message.reply_text("Этот букет уже не в витрине.")
            return
        db.update_bouquet(bouquet_id, status=f"sold_{channel}", sale_channel=channel, sold_at=NOW())
        ch_label = "в студии" if channel == "studio" else "на Flowwow"
        await q.message.edit_text(
            f"✅ Букет #{bouquet_id} продан {ch_label}!\nЦена: {bouquet['price']:,} ₽".replace(",", " "),
            reply_markup=None
        )
        florist = db.get_user_by_id(bouquet["florist_id"])
        await send_to_director(
            ctx.bot,
            f"💰 Букет #{bouquet_id} продан {ch_label}\n"
            f"Флорист: {florist['name'] if florist else '—'}\n"
            f"Сумма: {bouquet['price']:,} ₽".replace(",", " ")
        )

    # Bouquet disassemble
    elif data.startswith("bdisassemble:"):
        _, bouquet_id = data.split(":")
        bouquet_id = int(bouquet_id)
        bouquet = db.get_bouquet(bouquet_id)
        if not bouquet:
            return
        db.update_bouquet(bouquet_id, status="disassembled", disassembled_at=NOW())
        await q.message.edit_text(
            f"🗑 Букет #{bouquet_id} разобран.\nБыл в витрине: {bouquet['created_at'][:10]}",
            reply_markup=None
        )
        florist = db.get_user_by_id(bouquet["florist_id"])
        await send_to_director(
            ctx.bot,
            f"🗑 Букет #{bouquet_id} разобран\n"
            f"Флорист: {florist['name'] if florist else '—'}\n"
            f"Потеря: {bouquet['price']:,} ₽".replace(",", " ")
        )

    # Bouquet 4-day check ok
    elif data.startswith("bcheck:"):
        _, bouquet_id = data.split(":")
        bouquet_id = int(bouquet_id)
        db.update_bouquet(bouquet_id, checked_at=NOW())
        await q.message.edit_text(
            f"👍 Букет #{bouquet_id} проверен — всё хорошо!\nБудет напоминание через 2 дня.",
            reply_markup=None
        )
        await send_to_director(ctx.bot, f"📋 Букет #{bouquet_id} проверен на 4-й день — в порядке.")

    # Settings navigation
    elif data.startswith("settings:"):
        section = data.split(":")[1]
        if section == "main":
            await q.message.edit_text("⚙️ Настройки:", reply_markup=kb.settings_main_kb())
        elif section == "times":
            await q.message.edit_text("🕐 Время напоминаний:", reply_markup=kb.settings_times_kb())
        elif section == "kpi":
            await q.message.edit_text("📏 Пороги KPI:", reply_markup=kb.settings_kpi_kb())
        elif section == "bouquet":
            await q.message.edit_text("🌹 Срок букета:", reply_markup=kb.settings_bouquet_kb())

    # Settings set value
    elif data.startswith("setval:"):
        setting_key = data.split(":")[1]
        if not is_director(q.from_user.id):
            return
        current = db.get_setting(setting_key, "—")
        label = kb.SETTING_LABELS.get(setting_key, setting_key)
        ctx.user_data["setting_key"] = setting_key
        ctx.user_data["setting_msg_id"] = q.message.message_id
        await q.message.edit_text(
            f"Текущее значение: {current}\nВведи новое {label}:"
        )


# ── Photo handler ────────────────────────────────────────

async def photo_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user:
        return

    file_id = update.message.photo[-1].file_id

    # Task photo
    if "pending_task_id" in ctx.user_data:
        task_id = ctx.user_data.pop("pending_task_id")
        task_type = ctx.user_data.pop("pending_task_type", "")
        task = db.get_task(task_id)
        if not task:
            return

        db.update_task(task_id, status="submitted", photo_file_id=file_id, submitted_at=NOW())
        await update.message.reply_text("✅ Фото получено! Отправляю директору на оценку.")

        type_labels = {
            "vitrina_bouquets": "Витрина букетов",
            "vitrina_compositions": "Витрина композиций",
            "flowwow": "Flowwow",
        }
        caption = f"📸 {type_labels.get(task_type, task_type)}\n{user['name']} · {datetime.now().strftime('%d.%m %H:%M')}\n\nОцени:"
        director = db.get_director()
        if director:
            msg = await ctx.bot.send_photo(
                director["telegram_id"],
                photo=file_id,
                caption=caption,
                reply_markup=kb.rating_kb(task_id)
            )
            db.update_task(task_id, director_msg_id=msg.message_id)
        return

    # Bouquet photo (step 1)
    if ctx.user_data.get("adding_bouquet"):
        ctx.user_data["bouquet_photo"] = file_id
        ctx.user_data["adding_bouquet"] = False
        ctx.user_data["bouquet_price_step"] = True
        await update.message.reply_text("💰 Укажи цену букета (только цифры, например: 3500):")
        return

    await update.message.reply_text("Не понимаю зачем это фото 😊 Используй команды /букет или дождись задачи.")


# ── Text handler ─────────────────────────────────────────

async def text_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Напиши /start чтобы зарегистрироваться.")
        return

    text = update.message.text.strip()

    # Reason for not completing task
    if "reason_task_id" in ctx.user_data:
        task_id = ctx.user_data.pop("reason_task_id")
        db.update_task(task_id, no_reason=text, status="no")
        await update.message.reply_text("Записала. Директор узнает о причине.")
        task = db.get_task(task_id)
        await send_to_director(
            ctx.bot,
            f"⚠️ Задача не выполнена — {user['name']}\n"
            f"Причина: {text}\nВремя: {datetime.now().strftime('%H:%M')}"
        )
        return

    # Bouquet price
    if ctx.user_data.get("bouquet_price_step"):
        try:
            price = int(text.replace(" ", "").replace("₽", ""))
        except ValueError:
            await update.message.reply_text("Введи цену цифрами, например: 3500")
            return

        ctx.user_data["bouquet_price_step"] = False
        photo = ctx.user_data.pop("bouquet_photo", None)
        if not photo:
            await update.message.reply_text("Что-то пошло не так. Начни заново с /букет")
            return

        bouquet_id = db.create_bouquet(user["id"], photo, price)
        await update.message.reply_text(
            f"✅ Букет #{bouquet_id} добавлен!\nЦена: {price:,} ₽\n\nОтправляю директору на оценку.".replace(",", " "),
            reply_markup=kb.bouquet_status_kb(bouquet_id)
        )

        check_days = int(db.get_setting("bouquet_check_days", "4"))
        director = db.get_director()
        if director:
            await ctx.bot.send_photo(
                director["telegram_id"],
                photo=photo,
                caption=f"🌸 Новый букет #{bouquet_id}\nФлорист: {user['name']}\nЦена: {price:,} ₽\n\nОцени:".replace(",", " "),
                reply_markup=kb.bouquet_rating_kb(bouquet_id)
            )
        return

    # Settings value
    if "setting_key" in ctx.user_data and user["role"] == "director":
        key = ctx.user_data.pop("setting_key")
        db.set_setting(key, text)
        await update.message.reply_text(
            f"✅ Сохранено: {key} = {text}\nИзменение вступит в силу с следующего дня.",
            reply_markup=kb.settings_main_kb()
        )
        return

    # Director free question → Claude
    if user["role"] == "director":
        await update.message.reply_text("⏳ Анализирую данные...")
        response = ask_claude(text)
        await update.message.reply_text(f"✦ {response}")
        return

    await update.message.reply_text(
        "Используй команды:\n/букет — новый букет\n/витрина — активные букеты\n/мой_кпи — мой KPI"
    )


# ── Commands ─────────────────────────────────────────────

async def cmd_bukет(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user or user["role"] != "florist":
        await update.message.reply_text("Эта команда только для флористов.")
        return
    ctx.user_data["adding_bouquet"] = True
    await update.message.reply_text("🌸 Пришли фото нового готового букета:")


async def cmd_vitrina(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user:
        return
    fid = user["id"] if user["role"] == "florist" else None
    bouquets = db.get_active_bouquets(fid)
    if not bouquets:
        await update.message.reply_text("Активных букетов в витрине нет.")
        return

    now = datetime.now()
    lines = ["📋 Активные букеты в витрине:\n"]
    for b in bouquets:
        created = datetime.fromisoformat(b["created_at"])
        days = (now - created).days
        warn = " ⚠️" if days >= 4 else ""
        florist_info = f" · {b['florist_name']}" if user["role"] == "director" else ""
        lines.append(f"🌸 Букет #{b['id']}{florist_info} · {b['price']:,} ₽ · {days} дн.{warn}".replace(",", " "))

    await update.message.reply_text("\n".join(lines))
    if user["role"] == "florist":
        for b in bouquets:
            await update.message.reply_text(
                f"Букет #{b['id']} · {b['price']:,} ₽".replace(",", " "),
                reply_markup=kb.bouquet_status_kb(b["id"])
            )


async def cmd_my_kpi(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user or user["role"] != "florist":
        return
    ym = datetime.now().strftime("%Y-%m")
    kpi = calc_kpi(user["id"], ym)
    await update.message.reply_text(format_kpi_for_florist(user["name"], kpi))


async def cmd_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_director(update.effective_user.id):
        return
    await update.message.reply_text("⏳ Собираю отчёт...")
    from claude_ai import generate_monthly_report
    ym = datetime.now().strftime("%Y-%m")
    report = generate_monthly_report(ym)
    await update.message.reply_text(report)


async def cmd_kpi(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_director(update.effective_user.id):
        return
    ym = datetime.now().strftime("%Y-%m")
    florists = db.get_florists()
    for f in florists:
        kpi = calc_kpi(f["id"], ym)
        await update.message.reply_text(format_kpi_for_director(f["name"], kpi))


async def cmd_sales(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_director(update.effective_user.id):
        return
    ym = datetime.now().strftime("%Y-%m")
    florists = db.get_florists()
    lines = [f"💰 Продажи букетов · {ym}\n"]
    total_sold = 0
    total_sum = 0
    total_loss = 0

    for f in florists:
        bouquets = db.get_month_bouquets(ym, f["id"])
        report = format_sales_report(bouquets, f["name"])
        lines.append(report)
        lines.append("")
        total_sold += sum(1 for b in bouquets if b["status"] in ("sold_studio","sold_flowwow"))
        total_sum += sum(b["price"] for b in bouquets if b["status"] in ("sold_studio","sold_flowwow"))
        total_loss += sum(b["price"] for b in bouquets if b["status"]=="disassembled")

    lines.append(f"━━━━━━\n📊 Итого по студии:\nПродано: {total_sold} шт. → {total_sum:,} ₽\nПотери: {total_loss:,} ₽".replace(",", " "))
    await update.message.reply_text("\n".join(lines))


async def cmd_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_director(update.effective_user.id):
        return
    await update.message.reply_text("⚙️ Настройки бота:", reply_markup=kb.settings_main_kb())


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user:
        return
    if user["role"] == "florist":
        await cmd_my_kpi(update, ctx)
    else:
        await cmd_report(update, ctx)
