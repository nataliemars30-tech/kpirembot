from datetime import date, datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import (
    DIRECTOR_ID, TASK_NAMES, TASK_VITRINA_BOUQUETS,
    TASK_VITRINA_COMPOSITIONS, TASK_FLOWWOW,
    RATING_BAD, RATING_OK, RATING_EXCELLENT, RATING_LABELS,
    BOUQUET_ACTIVE, BOUQUET_SOLD_STUDIO, BOUQUET_SOLD_FLOWWOW,
    BOUQUET_DISASSEMBLED, BOUQUET_CHECKED,
    STATE_REGISTER_NAME, STATE_TASK_PHOTO, STATE_TASK_REASON,
    STATE_BOUQUET_PHOTO, STATE_BOUQUET_PRICE, STATE_SETTINGS_VALUE,
    STATE_DIRECTOR_QUESTION, DEFAULT_SETTINGS
)
from database import (
    get_user, create_user, get_all_florists, start_shift, has_shift_today,
    create_task, get_task, update_task, get_active_bouquets, create_bouquet,
    get_bouquet, update_bouquet, count_bouquets_this_month,
    get_bouquet_stats_for_month, get_tasks_for_month, get_setting, set_setting,
    get_florists_on_shift
)
from kpi import calc_kpi_for_user, format_kpi_for_florist, format_kpi_for_director
from claude_ai import ask_claude, generate_monthly_report


def is_director(user_id: int) -> bool:
    return user_id == DIRECTOR_ID


def task_keyboard(task_id: int):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Сделано", callback_data=f"task_done:{task_id}"),
        InlineKeyboardButton("⏳ Через час", callback_data=f"task_later:{task_id}"),
        InlineKeyboardButton("❌ Не готово", callback_data=f"task_fail:{task_id}"),
    ]])


def rating_keyboard(task_id: int):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("👎 Плохо", callback_data=f"rate:{task_id}:{RATING_BAD}"),
        InlineKeyboardButton("👌 Норм", callback_data=f"rate:{task_id}:{RATING_OK}"),
        InlineKeyboardButton("⭐ Отлично", callback_data=f"rate:{task_id}:{RATING_EXCELLENT}"),
    ]])


def bouquet_action_keyboard(bouquet_id: int):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Продан в студии", callback_data=f"b_studio:{bouquet_id}"),
        InlineKeyboardButton("🛍 Продан на Flowwow", callback_data=f"b_flowwow:{bouquet_id}"),
    ], [
        InlineKeyboardButton("🗑 Разобрать", callback_data=f"b_disassemble:{bouquet_id}"),
    ]])


def bouquet_check_keyboard(bouquet_id: int):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Продан в студии", callback_data=f"b_studio:{bouquet_id}"),
        InlineKeyboardButton("🛍 Продан на Flowwow", callback_data=f"b_flowwow:{bouquet_id}"),
    ], [
        InlineKeyboardButton("👍 Проверен — всё хорошо", callback_data=f"b_checked:{bouquet_id}"),
        InlineKeyboardButton("🗑 Разобрать", callback_data=f"b_disassemble:{bouquet_id}"),
    ]])


def bouquet_rating_keyboard(bouquet_id: int):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("👎 Плохо", callback_data=f"brate:{bouquet_id}:{RATING_BAD}"),
        InlineKeyboardButton("👌 Норм", callback_data=f"brate:{bouquet_id}:{RATING_OK}"),
        InlineKeyboardButton("⭐ Отлично", callback_data=f"brate:{bouquet_id}:{RATING_EXCELLENT}"),
    ]])


# ─── START / REGISTER ─────────────────────────────────────────────────────────

async def start_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await get_user(update.effective_user.id)
    if user:
        role = "директор" if is_director(update.effective_user.id) else "флорист"
        await update.message.reply_text(
            f"👋 Привет, {user['name']}! Ты зарегистрирован(а) как {role}.\n\n"
            f"{'Команды: /отчет · /kpi · /продажи · /настройки · /витрина' if is_director(update.effective_user.id) else 'Команды: /мой_кпи · /витрина · /букет'}"
        )
        return ConversationHandler.END

    if is_director(update.effective_user.id):
        await create_user(update.effective_user.id, "Директор", "director")
        await update.message.reply_text(
            "✅ Ты зарегистрирована как директор!\n\n"
            "Теперь отправь флористам ссылку на бота чтобы они зарегистрировались."
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "🌸 Привет! Я бот студии REN.\n\nКак тебя зовут?"
    )
    return STATE_REGISTER_NAME


async def register_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if len(name) < 2:
        await update.message.reply_text("Напиши имя (минимум 2 символа):")
        return STATE_REGISTER_NAME

    await create_user(update.effective_user.id, name, "florist")
    await update.message.reply_text(
        f"✅ Готово, {name}! Теперь ты в системе.\n\n"
        f"Каждый день в 10:00 нажимай кнопку начала смены — и бот будет присылать тебе задачи.\n\n"
        f"Команды:\n/мой_кпи — мой KPI\n/витрина — активные букеты\n/букет — добавить новый букет"
    )
    return ConversationHandler.END


# ─── SHIFT ────────────────────────────────────────────────────────────────────

async def send_shift_start_prompt(bot, florist):
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            f"🟢 Начать смену · {florist['name']}",
            callback_data=f"shift_start:{florist['id']}"
        )
    ]])
    await bot.send_message(
        chat_id=florist["telegram_id"],
        text=f"🌅 Доброе утро, {florist['name']}!\nНажми кнопку чтобы начать смену.",
        reply_markup=kb
    )


async def handle_shift_start_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = int(query.data.split(":")[1])

    user = await get_user(query.from_user.id)
    if not user or user["id"] != user_id:
        await query.answer("Это не твоя кнопка", show_alert=True)
        return

    if await has_shift_today(user_id):
        await query.edit_message_text(f"✅ Смена уже начата, {user['name']}!")
        return

    await start_shift(user_id)

    shift_time = await get_setting("vitrina_bouquets_time")
    comp_time = await get_setting("vitrina_compositions_time")
    flowwow_time = await get_setting("flowwow_time")

    text = (
        f"✅ {user['name']}, смена начата!\n\n"
        f"Сегодня твои задачи:\n"
        f"🕐 {shift_time} — витрина готовых букетов\n"
        f"🕕 {comp_time} — витрина готовых композиций\n"
    )

    if ctx.bot_data.get("flowwow_today"):
        text += f"🛍 {flowwow_time} — выложить на Flowwow\n"

    await query.edit_message_text(text)


# ─── TASK SENDING ─────────────────────────────────────────────────────────────

async def send_task_to_florist(bot, florist, task_type: str, task_id: int):
    name = TASK_NAMES[task_type]
    now = datetime.now().strftime("%H:%M")
    msg = await bot.send_message(
        chat_id=florist["telegram_id"],
        text=f"📋 {name}\nВремя: {now}\n\nПришли фото и отметь статус:",
        reply_markup=task_keyboard(task_id)
    )
    await update_task(task_id, message_id=msg.message_id)


# ─── TASK CALLBACKS ───────────────────────────────────────────────────────────

async def handle_task_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE, action: str, task_id: int):
    query = update.callback_query
    task = await get_task(task_id)
    if not task:
        await query.answer("Задача не найдена")
        return

    user = await get_user(query.from_user.id)
    if not user or user["id"] != task["user_id"]:
        await query.answer("Это не твоя задача", show_alert=True)
        return

    task_name = TASK_NAMES.get(task["task_type"], "Задача")

    if action == "done":
        await update_task(task_id, status="waiting_photo")
        ctx.user_data["pending_task_id"] = task_id
        await query.edit_message_text(
            f"📷 {task_name}\nОтлично! Теперь пришли фото."
        )

    elif action == "later":
        await update_task(task_id, status="later")
        ctx.job_queue.run_once(
            remind_task_later,
            when=3600,
            data={"task_id": task_id, "chat_id": query.message.chat_id},
            name=f"later_{task_id}"
        )
        await query.edit_message_text(
            f"⏳ {task_name}\nХорошо, напомню через час!"
        )

    elif action == "fail":
        await update_task(task_id, status="waiting_reason")
        ctx.user_data["pending_task_id"] = task_id
        await query.edit_message_text(
            f"❌ {task_name}\nНапиши причину — директор должна знать:"
        )


async def remind_task_later(ctx: ContextTypes.DEFAULT_TYPE):
    data = ctx.job.data
    task_id = data["task_id"]
    chat_id = data["chat_id"]
    task = await get_task(task_id)
    if not task or task["status"] not in ("later", "pending"):
        return

    task_name = TASK_NAMES.get(task["task_type"], "Задача")
    await ctx.bot.send_message(
        chat_id=chat_id,
        text=f"⏰ Прошёл час! {task_name} — как дела?",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Сделано", callback_data=f"task_done:{task_id}"),
            InlineKeyboardButton("❌ Не готово", callback_data=f"task_fail:{task_id}"),
        ]])
    )


async def handle_task_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await get_user(update.effective_user.id)
    if not user:
        return

    task_id = ctx.user_data.get("pending_task_id")
    if not task_id:
        # Could be a bouquet photo
        bouquet_id = ctx.user_data.get("pending_bouquet_id")
        if bouquet_id:
            await handle_bouquet_photo(update, ctx)
        return

    task = await get_task(task_id)
    if not task or task["status"] != "waiting_photo":
        return

    photo = update.message.photo[-1].file_id
    task_name = TASK_NAMES.get(task["task_type"], "Задача")

    await update_task(
        task_id,
        status="completed",
        photo_file_id=photo,
        completed_at=datetime.now().isoformat()
    )
    ctx.user_data.pop("pending_task_id", None)

    await update.message.reply_text(f"✅ Фото получено! Жду оценки директора.")

    dir_msg = await ctx.bot.send_photo(
        chat_id=DIRECTOR_ID,
        photo=photo,
        caption=(
            f"📸 {task_name}\n"
            f"Флорист: {user['name']} · {datetime.now().strftime('%d.%m %H:%M')}\n\n"
            f"Оцени:"
        ),
        reply_markup=rating_keyboard(task_id)
    )
    await update_task(task_id, director_message_id=dir_msg.message_id)


async def handle_task_reason(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await get_user(update.effective_user.id)
    if not user:
        return

    task_id = ctx.user_data.get("pending_task_id")
    if not task_id:
        return

    task = await get_task(task_id)
    if not task or task["status"] != "waiting_reason":
        return

    reason = update.message.text.strip()
    task_name = TASK_NAMES.get(task["task_type"], "Задача")

    await update_task(
        task_id,
        status="failed",
        reason=reason,
        rating=RATING_BAD
    )
    ctx.user_data.pop("pending_task_id", None)

    await update.message.reply_text("Понял. Директор получила уведомление.")
    await ctx.bot.send_message(
        chat_id=DIRECTOR_ID,
        text=(
            f"⚠️ {task_name} — НЕ ВЫПОЛНЕНА\n"
            f"Флорист: {user['name']} · {datetime.now().strftime('%d.%m %H:%M')}\n"
            f"Причина: {reason}"
        )
    )


# ─── RATING CALLBACK ──────────────────────────────────────────────────────────

async def handle_rating_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE, task_id: int, rating: int):
    query = update.callback_query
    if not is_director(query.from_user.id):
        await query.answer("Только директор может оценивать", show_alert=True)
        return

    task = await get_task(task_id)
    if not task:
        await query.answer("Задача не найдена")
        return

    label = RATING_LABELS[rating]
    await update_task(
        task_id,
        rating=rating,
        rated_at=datetime.now().isoformat()
    )

    task_name = TASK_NAMES.get(task["task_type"], "Задача")
    from database import get_user_by_id
    florist = await get_user_by_id(task["user_id"])

    await query.edit_message_caption(
        caption=f"📸 {task_name} · {florist['name']}\nОценка: {label} ✓"
    )

    await ctx.bot.send_message(
        chat_id=florist["telegram_id"],
        text=f"Оценка по {task_name}: {label}"
    )


# ─── TIMEOUT CHECK ────────────────────────────────────────────────────────────

async def check_overdue_tasks(ctx: ContextTypes.DEFAULT_TYPE):
    timeout = await get_setting("response_timeout_minutes")
    from database import get_pending_tasks_older_than
    overdue = await get_pending_tasks_older_than(timeout)

    for task in overdue:
        task_name = TASK_NAMES.get(task["task_type"], "Задача")
        await update_task(task["id"], status="overdue", rating=RATING_BAD)
        await ctx.bot.send_message(
            chat_id=DIRECTOR_ID,
            text=(
                f"⚠️ Нет ответа!\n"
                f"{task_name}\n"
                f"Флорист: {task['florist_name']}\n"
                f"Прошло: {timeout} минут"
            )
        )
        await ctx.bot.send_message(
            chat_id=task["florist_tg_id"],
            text=f"⚠️ Время на ответ по задаче «{task_name}» истекло. Директор уведомлена."
        )


# ─── BOUQUETS ─────────────────────────────────────────────────────────────────

async def bouquet_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await get_user(update.effective_user.id)
    if not user or user["role"] != "florist":
        await update.message.reply_text("Только флорист может добавлять букеты.")
        return ConversationHandler.END

    ctx.user_data["adding_bouquet"] = True
    await update.message.reply_text("📷 Пришли фото нового готового букета!")
    return STATE_BOUQUET_PHOTO


async def handle_bouquet_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await get_user(update.effective_user.id)
    if not user:
        return ConversationHandler.END

    photo = update.message.photo[-1].file_id
    ctx.user_data["bouquet_photo"] = photo
    ctx.user_data.pop("adding_bouquet", None)

    await update.message.reply_text("💰 Укажи цену букета (только цифры, например: 3500):")
    return STATE_BOUQUET_PRICE


async def handle_bouquet_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await get_user(update.effective_user.id)
    if not user:
        return ConversationHandler.END

    try:
        price = int(update.message.text.strip().replace(" ", "").replace("₽", ""))
    except ValueError:
        await update.message.reply_text("Напиши только цифры, например: 3500")
        return STATE_BOUQUET_PRICE

    photo = ctx.user_data.pop("bouquet_photo", None)
    if not photo:
        await update.message.reply_text("Что-то пошло не так. Начни заново: /букет")
        return ConversationHandler.END

    bouquet_id = await create_bouquet(user["id"], photo, price)
    count = await count_bouquets_this_month(user["id"])

    await update.message.reply_text(
        f"✅ Букет #{bouquet_id} добавлен!\n"
        f"Цена: {price:,} ₽\n"
        f"В этом месяце твоих букетов: {count} шт.\n\n"
        f"Чтобы изменить статус — нажми кнопку на сообщении директора или используй /витрина"
    )

    dir_msg = await ctx.bot.send_photo(
        chat_id=DIRECTOR_ID,
        photo=photo,
        caption=(
            f"🌹 Новый букет #{bouquet_id}\n"
            f"Флорист: {user['name']}\n"
            f"Цена: {price:,} ₽\n"
            f"Букетов в месяце: {count} шт.\n\n"
            f"Оцени:"
        ),
        reply_markup=bouquet_rating_keyboard(bouquet_id)
    )
    await update_bouquet(bouquet_id, director_message_id=dir_msg.message_id)
    return ConversationHandler.END


async def handle_bouquet_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE, action: str, bouquet_id: int):
    query = update.callback_query
    bouquet = await get_bouquet(bouquet_id)
    if not bouquet:
        await query.answer("Букет не найден")
        return

    user = await get_user(query.from_user.id)
    if not user:
        return

    now = datetime.now().isoformat()
    from database import get_user_by_id
    florist = await get_user_by_id(bouquet["user_id"])

    if action == "studio":
        await update_bouquet(bouquet_id, status=BOUQUET_SOLD_STUDIO, sold_at=now, sale_channel="studio")
        status_text = "✅ Продан в студии"
        await ctx.bot.send_message(
            chat_id=DIRECTOR_ID,
            text=f"💚 Букет #{bouquet_id} продан в студии\nФлорист: {florist['name']} · {bouquet['price']:,} ₽"
        )
        await ctx.bot.send_message(
            chat_id=florist["telegram_id"],
            text=f"🎉 Букет #{bouquet_id} отмечен как проданный в студии!"
        )

    elif action == "flowwow":
        await update_bouquet(bouquet_id, status=BOUQUET_SOLD_FLOWWOW, sold_at=now, sale_channel="flowwow")
        status_text = "🛍 Продан на Flowwow"
        await ctx.bot.send_message(
            chat_id=DIRECTOR_ID,
            text=f"🛍 Букет #{bouquet_id} продан на Flowwow\nФлорист: {florist['name']} · {bouquet['price']:,} ₽"
        )
        await ctx.bot.send_message(
            chat_id=florist["telegram_id"],
            text=f"🎉 Букет #{bouquet_id} отмечен как проданный на Flowwow!"
        )

    elif action == "disassemble":
        await update_bouquet(bouquet_id, status=BOUQUET_DISASSEMBLED, disassembled_at=now)
        status_text = "🗑 Разобран"
        await ctx.bot.send_message(
            chat_id=DIRECTOR_ID,
            text=f"🗑 Букет #{bouquet_id} разобран\nФлорист: {florist['name']} · {bouquet['price']:,} ₽ (не продан)"
        )

    elif action == "checked":
        await update_bouquet(bouquet_id, status=BOUQUET_CHECKED, checked_at=now)
        status_text = "👍 Проверен — всё хорошо"
        await ctx.bot.send_message(
            chat_id=DIRECTOR_ID,
            text=f"📋 Букет #{bouquet_id} проверен на {(datetime.now() - datetime.fromisoformat(bouquet['created_at'])).days}-й день\nФлорист: {florist['name']} · статус: хорошо"
        )

    else:
        return

    try:
        await query.edit_message_caption(
            caption=f"🌹 Букет #{bouquet_id} · {florist['name']} · {bouquet['price']:,} ₽\nСтатус: {status_text}"
        )
    except Exception:
        await query.answer(status_text)


async def handle_bouquet_rating(update: Update, ctx: ContextTypes.DEFAULT_TYPE, bouquet_id: int, rating: int):
    query = update.callback_query
    if not is_director(query.from_user.id):
        await query.answer("Только директор", show_alert=True)
        return

    bouquet = await get_bouquet(bouquet_id)
    if not bouquet:
        await query.answer("Букет не найден")
        return

    await update_bouquet(bouquet_id, rating=rating)
    label = RATING_LABELS[rating]

    from database import get_user_by_id
    florist = await get_user_by_id(bouquet["user_id"])

    try:
        await query.edit_message_caption(
            caption=(
                f"🌹 Букет #{bouquet_id} · {florist['name']} · {bouquet['price']:,} ₽\n"
                f"Оценка: {label} ✓"
            ),
            reply_markup=bouquet_action_keyboard(bouquet_id)
        )
    except Exception:
        pass


# ─── VITRINA COMMAND ──────────────────────────────────────────────────────────

async def vitrina_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await get_user(update.effective_user.id)
    if not user:
        return

    if is_director(update.effective_user.id):
        bouquets = await get_active_bouquets()
    else:
        bouquets = await get_active_bouquets(user["id"])

    if not bouquets:
        await update.message.reply_text("🌸 В витрине сейчас нет активных букетов.")
        return

    now = datetime.now()
    lines = [f"🌸 Активные букеты ({len(bouquets)} шт.):"]
    for b in bouquets:
        created = datetime.fromisoformat(b["created_at"])
        days = (now - created).days
        warning = " ⚠️" if days >= 4 else ""
        name_part = f" · {b['florist_name']}" if is_director(update.effective_user.id) else ""
        lines.append(f"  #{b['id']}{name_part} · {b['price']:,} ₽ · {days} дн.{warning}")

    msg = "\n".join(lines)
    if not is_director(update.effective_user.id):
        msg += "\n\nЧтобы изменить статус — напиши /статус_{номер}\nНапример: /статус_5"

    await update.message.reply_text(msg)


async def status_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await get_user(update.effective_user.id)
    if not user:
        return

    text = update.message.text.strip()
    try:
        bouquet_id = int(text.split("_")[1])
    except (IndexError, ValueError):
        await update.message.reply_text("Формат: /статус_5 (где 5 — номер букета)")
        return

    bouquet = await get_bouquet(bouquet_id)
    if not bouquet:
        await update.message.reply_text(f"Букет #{bouquet_id} не найден.")
        return

    if bouquet["user_id"] != user["id"] and not is_director(update.effective_user.id):
        await update.message.reply_text("Это не твой букет.")
        return

    from database import get_user_by_id
    florist = await get_user_by_id(bouquet["user_id"])
    created = datetime.fromisoformat(bouquet["created_at"])
    days = (datetime.now() - created).days

    await ctx.bot.send_photo(
        chat_id=update.effective_chat.id,
        photo=bouquet["photo_file_id"],
        caption=(
            f"🌹 Букет #{bouquet_id} · {florist['name']}\n"
            f"Цена: {bouquet['price']:,} ₽\n"
            f"Создан: {created.strftime('%d.%m')} ({days} дн. назад)\n"
            f"Статус: В витрине\n\nИзменить статус:"
        ),
        reply_markup=bouquet_check_keyboard(bouquet_id) if days >= 4 else bouquet_action_keyboard(bouquet_id)
    )


# ─── KPI ──────────────────────────────────────────────────────────────────────

async def my_kpi_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await get_user(update.effective_user.id)
    if not user or user["role"] != "florist":
        await update.message.reply_text("Команда только для флористов.")
        return

    await update.message.reply_text("⏳ Считаю...")
    kpi = await calc_kpi_for_user(user["id"])
    text = format_kpi_for_florist(kpi, user["name"])
    await update.message.reply_text(text)


# ─── DIRECTOR REPORTS ─────────────────────────────────────────────────────────

async def report_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_director(update.effective_user.id):
        await update.message.reply_text("Только для директора.")
        return

    await update.message.reply_text("⏳ Собираю отчёт...")
    month = date.today().strftime("%Y-%m")
    florists = await get_all_florists()

    lines = [f"📊 Отчёт · {date.today().strftime('%d.%m.%Y')}\n"]

    total_revenue = 0
    total_losses = 0

    for florist in florists:
        kpi = await calc_kpi_for_user(florist["id"], month)
        lines.append(format_kpi_for_director(kpi, florist["name"]))
        lines.append("")

        stats = await get_bouquet_stats_for_month(florist["id"], month)
        if stats and stats["total"]:
            lines.append(f"💰 Букеты · {florist['name']}:")
            lines.append(f"  Сделано: {stats['total']} шт.")
            lines.append(f"  В студии: {stats['sold_studio']} шт. → {stats['revenue_studio'] or 0:,} ₽")
            lines.append(f"  На Flowwow: {stats['sold_flowwow']} шт. → {stats['revenue_flowwow'] or 0:,} ₽")
            lines.append(f"  Разобрано: {stats['disassembled']} шт. · потери {stats['losses'] or 0:,} ₽")
            lines.append(f"  В витрине: {stats['in_vitrina']} шт.")
            total_revenue += stats["revenue"] or 0
            total_losses += stats["losses"] or 0
        lines.append("")

    lines.append("─────────────────")
    lines.append(f"💚 Итого продаж: {total_revenue:,} ₽")
    lines.append(f"🔴 Итого потерь: {total_losses:,} ₽")

    active = await get_active_bouquets()
    lines.append(f"\n🌸 В витрине сейчас: {len(active)} букетов")

    await update.message.reply_text("\n".join(lines))


async def kpi_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_director(update.effective_user.id):
        return
    await report_command(update, ctx)


async def sales_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_director(update.effective_user.id):
        return

    month = date.today().strftime("%Y-%m")
    florists = await get_all_florists()
    lines = [f"💰 Продажи букетов · {date.today().strftime('%B %Y')}\n"]

    for florist in florists:
        stats = await get_bouquet_stats_for_month(florist["id"], month)
        lines.append(f"👩‍🌾 {florist['name']}:")
        if not stats or not stats["total"]:
            lines.append("  Букетов нет\n")
            continue
        lines.append(f"  Сделано: {stats['total']} шт.")
        lines.append(f"  ✅ Продано в студии: {stats['sold_studio']} шт. → {stats['revenue_studio'] or 0:,} ₽")
        lines.append(f"  🛍 Продано на Flowwow: {stats['sold_flowwow']} шт. → {stats['revenue_flowwow'] or 0:,} ₽")
        lines.append(f"  💚 Итого: {stats['sold_total']} шт. → {stats['revenue'] or 0:,} ₽")
        lines.append(f"  🗑 Разобрано: {stats['disassembled']} шт. · потери {stats['losses'] or 0:,} ₽")
        pct = int(stats['sold_total'] / stats['total'] * 100) if stats['total'] else 0
        lines.append(f"  Процент продаж: {pct}%\n")

    await update.message.reply_text("\n".join(lines))


# ─── DIRECTOR CLAUDE QUESTION ─────────────────────────────────────────────────

async def ask_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_director(update.effective_user.id):
        await update.message.reply_text("Эта функция только для директора.")
        return ConversationHandler.END

    await update.message.reply_text(
        "✦ Задай вопрос — я отвечу на основе данных о работе флористов:\n\n"
        "Например:\n• Как работала Анна на этой неделе?\n• Кто рискует не получить KPI?\n• Что происходит с продажами?"
    )
    return STATE_DIRECTOR_QUESTION


async def handle_director_question(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_director(update.effective_user.id):
        return ConversationHandler.END

    question = update.message.text.strip()
    await update.message.reply_text("⏳ Анализирую...")

    answer = await ask_claude(question)
    await update.message.reply_text(f"✦ {answer}")
    return ConversationHandler.END


# ─── SETTINGS ─────────────────────────────────────────────────────────────────

async def settings_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_director(update.effective_user.id):
        await update.message.reply_text("Только для директора.")
        return

    b_time = await get_setting("vitrina_bouquets_time")
    c_time = await get_setting("vitrina_compositions_time")
    f_time = await get_setting("flowwow_time")
    s_time = await get_setting("shift_start_time")
    timeout = await get_setting("response_timeout_minutes")
    check_days = await get_setting("bouquet_check_days")
    dis_days = await get_setting("bouquet_disassemble_days")

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🕐 Время напоминаний", callback_data="set:times")],
        [InlineKeyboardButton("📏 Пороги KPI", callback_data="set:kpi")],
        [InlineKeyboardButton("🌹 Срок букета", callback_data="set:bouquet")],
        [InlineKeyboardButton("⏱ Тайм-аут ответа", callback_data="set:timeout")],
        [InlineKeyboardButton("👩‍🌾 Флористы", callback_data="set:florists")],
    ])

    await update.message.reply_text(
        f"⚙️ Настройки бота\n\n"
        f"🌸 Витрина букетов: {b_time}\n"
        f"🎋 Витрина композиций: {c_time}\n"
        f"🛍 Flowwow: {f_time}\n"
        f"🚀 Начало смены: {s_time}\n"
        f"⏱ Тайм-аут: {timeout} мин.\n"
        f"🌹 Проверка букета: день {check_days} / разобрать: день {dis_days}",
        reply_markup=kb
    )


async def handle_settings_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE, section: str):
    query = update.callback_query
    if not is_director(query.from_user.id):
        await query.answer("Только директор", show_alert=True)
        return

    if section == "times":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🌸 Витрина букетов", callback_data="setval:vitrina_bouquets_time")],
            [InlineKeyboardButton("🎋 Витрина композиций", callback_data="setval:vitrina_compositions_time")],
            [InlineKeyboardButton("🛍 Flowwow", callback_data="setval:flowwow_time")],
            [InlineKeyboardButton("🚀 Начало смены", callback_data="setval:shift_start_time")],
        ])
        await query.edit_message_text("Выбери что изменить:", reply_markup=kb)

    elif section == "kpi":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Макс. пропусков витрины", callback_data="setval:kpi_vitrina_max_skips")],
            [InlineKeyboardButton("Макс. «Норм» витрины", callback_data="setval:kpi_vitrina_max_norm")],
            [InlineKeyboardButton("Макс. пропусков Flowwow", callback_data="setval:kpi_flowwow_max_skips")],
            [InlineKeyboardButton("Макс. «Плохо» букеты", callback_data="setval:kpi_bouquet_max_bad")],
        ])
        await query.edit_message_text("Выбери порог:", reply_markup=kb)

    elif section == "bouquet":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📅 День проверки (сейчас 4)", callback_data="setval:bouquet_check_days")],
            [InlineKeyboardButton("🗑 День разборки (сейчас 6)", callback_data="setval:bouquet_disassemble_days")],
        ])
        await query.edit_message_text("Срок букета:", reply_markup=kb)

    elif section == "timeout":
        await query.edit_message_text(
            "Напиши количество минут для тайм-аута ответа (например: 30):"
        )
        ctx.user_data["setting_key"] = "response_timeout_minutes"
        ctx.user_data["waiting_setting"] = True

    elif section == "florists":
        florists = await get_all_florists()
        lines = ["👩‍🌾 Активные флористы:\n"]
        for f in florists:
            lines.append(f"• {f['name']} (ID: {f['telegram_id']})")
        lines.append("\nЧтобы добавить нового — попроси флориста написать /start боту.")
        await query.edit_message_text("\n".join(lines))


async def handle_setval_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE, key: str):
    query = update.callback_query
    if not is_director(query.from_user.id):
        return

    ctx.user_data["setting_key"] = key
    ctx.user_data["waiting_setting"] = True

    hints = {
        "vitrina_bouquets_time": "Введи время в формате ЧЧ:ММ (например: 14:00)",
        "vitrina_compositions_time": "Введи время в формате ЧЧ:ММ (например: 18:00)",
        "flowwow_time": "Введи время в формате ЧЧ:ММ (например: 15:00)",
        "shift_start_time": "Введи время в формате ЧЧ:ММ (например: 10:00)",
        "bouquet_check_days": "Введи количество дней (например: 4)",
        "bouquet_disassemble_days": "Введи количество дней (например: 6)",
        "kpi_vitrina_max_skips": "Макс. пропусков витрины (например: 4)",
        "kpi_vitrina_max_norm": "Макс. оценок «Норм» (например: 7)",
        "kpi_flowwow_max_skips": "Макс. пропусков Flowwow (например: 1)",
        "kpi_bouquet_max_bad": "Макс. «Плохо» по букетам (например: 2)",
    }

    await query.edit_message_text(hints.get(key, f"Введи новое значение для {key}:"))


async def handle_setting_value(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_director(update.effective_user.id):
        return

    if not ctx.user_data.get("waiting_setting"):
        return

    key = ctx.user_data.pop("setting_key", None)
    ctx.user_data.pop("waiting_setting", None)

    if not key:
        return

    value = update.message.text.strip()
    await set_setting(key, value)
    await update.message.reply_text(f"✅ Сохранено: {key} = {value}\n\nИзменение вступит в силу со следующего запуска задачи.")


# ─── MAIN CALLBACK ROUTER ─────────────────────────────────────────────────────

async def main_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("shift_start:"):
        await handle_shift_start_callback(update, ctx)

    elif data.startswith("task_done:"):
        task_id = int(data.split(":")[1])
        await handle_task_callback(update, ctx, "done", task_id)

    elif data.startswith("task_later:"):
        task_id = int(data.split(":")[1])
        await handle_task_callback(update, ctx, "later", task_id)

    elif data.startswith("task_fail:"):
        task_id = int(data.split(":")[1])
        await handle_task_callback(update, ctx, "fail", task_id)

    elif data.startswith("rate:"):
        _, task_id, rating = data.split(":")
        await handle_rating_callback(update, ctx, int(task_id), int(rating))

    elif data.startswith("b_studio:"):
        bouquet_id = int(data.split(":")[1])
        await handle_bouquet_callback(update, ctx, "studio", bouquet_id)

    elif data.startswith("b_flowwow:"):
        bouquet_id = int(data.split(":")[1])
        await handle_bouquet_callback(update, ctx, "flowwow", bouquet_id)

    elif data.startswith("b_disassemble:"):
        bouquet_id = int(data.split(":")[1])
        await handle_bouquet_callback(update, ctx, "disassemble", bouquet_id)

    elif data.startswith("b_checked:"):
        bouquet_id = int(data.split(":")[1])
        await handle_bouquet_callback(update, ctx, "checked", bouquet_id)

    elif data.startswith("brate:"):
        _, bouquet_id, rating = data.split(":")
        await handle_bouquet_rating(update, ctx, int(bouquet_id), int(rating))

    elif data.startswith("set:"):
        section = data.split(":")[1]
        await handle_settings_callback(update, ctx, section)

    elif data.startswith("setval:"):
        key = data.split(":")[1]
        await handle_setval_callback(update, ctx, key)


# ─── UNIVERSAL MESSAGE HANDLER ────────────────────────────────────────────────

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await get_user(update.effective_user.id)
    if not user:
        await start_command(update, ctx)
        return

    text = update.message.text.strip()

    if text.startswith("/статус_"):
        await status_command(update, ctx)
        return

    # Setting value input
    if ctx.user_data.get("waiting_setting") and is_director(update.effective_user.id):
        await handle_setting_value(update, ctx)
        return

    # Task reason
    task_id = ctx.user_data.get("pending_task_id")
    if task_id:
        task = await get_task(task_id)
        if task and task["status"] == "waiting_reason":
            await handle_task_reason(update, ctx)
            return

    # Director free question
    if is_director(update.effective_user.id):
        await update.message.reply_text("⏳ Анализирую...")
        answer = await ask_claude(text)
        await update.message.reply_text(f"✦ {answer}")
        return

    # Bouquet price
    if ctx.user_data.get("bouquet_photo"):
        await handle_bouquet_price(update, ctx)
        return

    await update.message.reply_text(
        "Используй кнопки или команды:\n/мой_кпи · /витрина · /букет"
    )


async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await get_user(update.effective_user.id)
    if not user:
        return

    # Task photo
    task_id = ctx.user_data.get("pending_task_id")
    if task_id:
        task = await get_task(task_id)
        if task and task["status"] == "waiting_photo":
            await handle_task_photo(update, ctx)
            return

    # Bouquet photo
    if ctx.user_data.get("adding_bouquet"):
        await handle_bouquet_photo(update, ctx)
        return

    await update.message.reply_text(
        "Чтобы добавить букет — напиши /букет\n"
        "Чтобы отчитаться по витрине — нажми кнопку в задаче."
    )
