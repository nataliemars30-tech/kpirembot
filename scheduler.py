import logging
from datetime import datetime, date, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

import database as db
from handlers import send_task, shift_prompt, resend_task_kb
from claude_ai import generate_monthly_report

log = logging.getLogger(__name__)


def get_tz():
    from config import TIMEZONE
    return pytz.timezone(TIMEZONE)


def now_msk():
    """Текущее время по московскому времени."""
    return datetime.now(get_tz())


def today_msk():
    return now_msk().date().isoformat()


def parse_time(t):
    h, m = map(int, t.split(":"))
    return h, m


# ── Смена ────────────────────────────────────────────────

async def job_shift_prompt(app):
    """10:00 МСК — кнопка начала смены всем флористам."""
    await shift_prompt(app.bot, db.get_florists())


async def job_shift_reminder(app):
    """
    Каждые 5 минут с 9:50 до 12:00 МСК.
    Напоминает флористу открыть смену или прислать чек.
    """
    now   = now_msk()
    t     = now.hour * 60 + now.minute
    today = today_msk()

    # Окно: от shift_start_time - 10 мин до shift_start_time + 2 часа
    shift_time = db.get_setting("shift_start_time", "10:00")
    sh, sm = map(int, shift_time.split(":"))
    shift_min = sh * 60 + sm
    if not (shift_min - 10 <= t <= shift_min + 120):
        log.info(f"[shift_reminder] вне окна: t={t} shift_min={shift_min} окно={shift_min-10}-{shift_min+120}")
        return

    director = db.get_director()
    florists = db.get_working_florists(today)
    log.info(f"[shift_reminder] t={t} shift_min={shift_min} florists={len(florists)}")

    for f in florists:
        has_r = db.has_receipt(f["id"], today)
        has_s = db.has_shift(f["id"], today)
        log.info(f"[shift_reminder] {f['name']} has_shift={has_s} has_receipt={has_r}")

        # Чек уже есть — не беспокоим
        log.info(f"[shift_reminder] {f['name']} checking: has_r={has_r} has_s={has_s}")
        if has_r:
            log.info(f"[shift_reminder] {f['name']} skipping — receipt exists")
            continue

        log.info(f"[shift_reminder] {f['name']} will send message")
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        if not has_s:
            # Смена не открыта — отправляем с кнопкой
            try:
                await app.bot.send_message(
                    f["telegram_id"],
                    "Открой смену!",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton(
                            f"Начать смену — {f['name']}",
                            callback_data=f"shift:{f['id']}")
                    ]])
                )
                log.info(f"[shift_reminder] sent open_shift to {f['name']}")
            except Exception as e:
                log.error(f"[shift_reminder] ERROR sending to {f['name']}: {e}")
            director_msg = f"{f['name']} не открыла смену"
        else:
            # Смена открыта но нет чека
            try:
                await app.bot.send_message(f["telegram_id"],
                    "Не забудь прислать фото чека с терминала!")
                log.info(f"[shift_reminder] sent receipt_reminder to {f['name']}")
            except Exception as e:
                log.error(f"[shift_reminder] ERROR sending receipt to {f['name']}: {e}")
            director_msg = f"{f['name']} — нет фото чека"

        # Директору каждый раз
        if director:
            try:
                await app.bot.send_message(director["telegram_id"], director_msg)
            except Exception as e:
                log.error(e)


# ── Задачи ────────────────────────────────────────────────

async def job_vitrina_bouquets(app):
    today   = today_msk()
    workers = db.get_working_florists(today)
    t_str   = db.get_setting("vitrina_bouquets_time", "14:00")
    for f in workers:
        await send_task(app.bot, f, "vitrina_bouquets", t_str)


async def job_vitrina_compositions(app):
    today   = today_msk()
    workers = db.get_working_florists(today)
    t_str   = db.get_setting("vitrina_compositions_time", "18:00")
    for f in workers:
        await send_task(app.bot, f, "vitrina_compositions", t_str)


async def job_flowwow(app):
    today   = today_msk()
    workers = db.get_working_florists(today)
    t_str   = db.get_setting("flowwow_time", "13:00")
    for f in workers:
        await send_task(app.bot, f, "flowwow", t_str)


async def job_flowwow_copy(app):
    """11:00 — напоминание скопировать готовые букеты на Flowwow."""
    today   = today_msk()
    workers = db.get_working_florists(today)
    import keyboards as kb
    for f in workers:
        task = db.get_pending_task(f["id"], "flowwow_copy", today)
        if task:
            continue
        task_id = db.create_task("flowwow_copy", f["id"], today, "11:00")
        try:
            msg = await app.bot.send_message(
                f["telegram_id"],
                "11:00 — Скопируй готовые букеты на Flowwow!",
                reply_markup=kb.flowwow_copy_kb(task_id))
            db.update_task(task_id, florist_msg_id=msg.message_id)
        except Exception as e:
            log.error(e)


async def job_close_shift_prompt(app):
    """21:00 МСК — кнопка закрытия смены."""
    today   = today_msk()
    workers = db.get_working_florists(today)
    import keyboards as kb
    for f in workers:
        if not db.has_shift_closed(f["id"], today):
            try:
                await app.bot.send_message(
                    f["telegram_id"],
                    "🔒 Пора закрывать смену!",
                    reply_markup=kb.close_shift_kb(f["id"]))
            except Exception as e:
                log.error(e)


async def job_all_task_reminders(app):
    """Единый джоб — каждые 5 минут шлёт текстовое напоминание если нет ответа."""
    now      = now_msk()
    today    = today_msk()
    t        = now.hour * 60 + now.minute
    director = db.get_director()
    workers  = db.get_working_florists(today)

    log.info(f"[reminder] t={t} today={today} workers={len(workers)}")

    def time_to_min(s):
        h, m = map(int, s.split(":")); return h * 60 + m

    tasks_config = [
        ("vitrina_bouquets",
         time_to_min(db.get_setting("vitrina_bouquets_time", "14:00")),
         db.get_setting("vitrina_bouquets_time", "14:00")),
        ("vitrina_compositions",
         time_to_min(db.get_setting("vitrina_compositions_time", "15:00")),
         db.get_setting("vitrina_compositions_time", "15:00")),
        ("flowwow",
         time_to_min(db.get_setting("flowwow_time", "13:00")),
         db.get_setting("flowwow_time", "13:00")),
        ("flowwow_copy", 11 * 60, "11:00"),
    ]

    labels_florist = {
        "vitrina_bouquets":     "витрина букетов — пришли фото!",
        "vitrina_compositions": "витрина композиций — пришли фото!",
        "flowwow":              "Flowwow — пришли фото!",
    }

    for task_type, start_min, task_time in tasks_config:
        if t < start_min + 5:
            continue
        elapsed = t - start_min
        for f in workers:
            task = db.get_pending_task(f["id"], task_type, today)
            log.info(f"[reminder] {task_type} {f['name']} status={task['status'] if task else None}")
            if not task:
                continue
            # Повторяем задачу с кнопками (без создания новой записи в БД)
            try:
                await resend_task_kb(app.bot, f, task_type, task["id"])
                log.info(f"[reminder] sent task kb to {f['name']}")
            except Exception as e:
                log.error(e)
            # Директору каждые 15 минут
            if director and elapsed % 15 == 0:
                try:
                    await app.bot.send_message(director["telegram_id"],
                        f"Нет ответа — {f['name']}, {task_type.replace('_', ' ')} ({task_time})")
                except Exception as e:
                    log.error(e)


async def job_timeout_check(app):
    """Задачи без ответа 30+ минут — закрыть как пропущенные."""
    timeout  = int(db.get_setting("timeout_minutes", "30"))
    director = db.get_director()
    conn = db.get_conn(); cur = conn.cursor()
    cur.execute("""
        SELECT t.*, u.name as florist_name
        FROM tasks t JOIN users u ON t.assigned_to=u.id
        WHERE t.status='pending'
        AND (t.date || ' ' || t.scheduled_time)::timestamp
            <= NOW() - INTERVAL '1 minute' * %s
    """, (timeout,))
    rows = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]
    cur.close(); conn.close()

    labels = {
        "vitrina_bouquets":     "Витрина букетов",
        "vitrina_compositions": "Витрина композиций",
        "flowwow":              "Flowwow",
    }
    for t in rows:
        db.update_task(t["id"], status="missed")
        if director:
            try:
                await app.bot.send_message(director["telegram_id"],
                    f"Задача закрыта — нет ответа\n"
                    f"{labels.get(t['type'], t['type'])} · {t['florist_name']}")
            except Exception as e:
                log.error(e)


async def job_autorating(app):
    """Авто-оценка Норм если директор не оценил за 24 часа."""
    tasks = db.get_unrated_tasks(24)
    for t in tasks:
        db.update_task(t["id"], rating=1, status="rated",
                       rated_at=datetime.now().isoformat())
        try:
            await app.bot.send_message(t["florist_tg"],
                f"Отчёт за {t['date']} засчитан как «Норм» автоматически")
        except Exception as e:
            log.error(e)


# ── Букеты ───────────────────────────────────────────────

async def job_bouquet_check_4day(app):
    days     = int(db.get_setting("bouquet_check_days", "4"))
    bouquets = db.get_bouquets_for_check(days, "sent_4day")
    director = db.get_director()
    import keyboards as kb
    for b in bouquets:
        try:
            caption = (f"Букету #{b['id']} уже {days} дня!\n"
                       f"Цена: {b['price']:,} ₽ · Что с ним?".replace(",", " "))
            fl = db.get_user_by_id(b["florist_id"])
            if not fl:
                continue
            if b.get("photo_file_id"):
                await app.bot.send_photo(fl["telegram_id"],
                    photo=b["photo_file_id"], caption=caption,
                    reply_markup=kb.bouquet_check_kb(b["id"]))
            else:
                await app.bot.send_message(fl["telegram_id"], caption,
                    reply_markup=kb.bouquet_check_kb(b["id"]))
            db.update_bouquet(b["id"], sent_4day=1)
            if director:
                await app.bot.send_message(director["telegram_id"],
                    f"Напомнила {b['florist_name']} о букете #{b['id']} ({days} дней)")
        except Exception as e:
            log.error(e)


async def job_bouquet_check_6day(app):
    days     = int(db.get_setting("bouquet_max_days", "6"))
    bouquets = db.get_bouquets_for_check(days, "sent_6day")
    director = db.get_director()
    import keyboards as kb
    for b in bouquets:
        try:
            caption = f"Букету #{b['id']} уже {days} дней! Пора разобрать."
            fl = db.get_user_by_id(b["florist_id"])
            if not fl:
                continue
            if b.get("photo_file_id"):
                await app.bot.send_photo(fl["telegram_id"],
                    photo=b["photo_file_id"], caption=caption,
                    reply_markup=kb.bouquet_check_kb(b["id"]))
            else:
                await app.bot.send_message(fl["telegram_id"], caption,
                    reply_markup=kb.bouquet_check_kb(b["id"]))
            db.update_bouquet(b["id"], sent_6day=1)
            if director:
                await app.bot.send_message(director["telegram_id"],
                    f"Букет #{b['id']} — {b['florist_name']} — {days} дней, нужно разобрать!")
        except Exception as e:
            log.error(e)


# ── Отчёты ───────────────────────────────────────────────

async def job_kpi_warning(app):
    """25-го числа — предупреждение флористам если KPI под угрозой."""
    if now_msk().day != 25:
        return
    from kpi import calc_kpi
    ym = now_msk().strftime("%Y-%m")
    for f in db.get_florists():
        kpi = calc_kpi(f["id"], ym)
        at_risk = [name for name, data in [
            ("витрина букетов",    kpi["criteria"]["vitrina_bouquets"]),
            ("витрина композиций", kpi["criteria"]["vitrina_compositions"]),
            ("Flowwow",            kpi["criteria"]["flowwow"]),
            ("качество букетов",   kpi["criteria"]["bouquet_quality"]),
            ("опоздания",          kpi["criteria"]["lates"]),
        ] if data["failed"]]
        if at_risk:
            try:
                await app.bot.send_message(f["telegram_id"],
                    "До конца месяца 5 дней!\n\nKPI под угрозой:\n" +
                    "\n".join(f"— {r}" for r in at_risk) +
                    "\n\nЕщё можно исправить. /moy_kpi для деталей.")
            except Exception as e:
                log.error(e)


async def job_weekly_report(app):
    director = db.get_director()
    if not director:
        return
    ym = now_msk().strftime("%Y-%m")
    from kpi import calc_kpi
    lines = [f"Итог недели — {now_msk().strftime('%d.%m.%Y')}\n"]
    for f in db.get_florists():
        kpi      = calc_kpi(f["id"], ym)
        shifts   = db.get_month_shifts(f["id"], ym)
        bouquets = db.get_month_bouquets(ym, f["id"])
        sold_sum = sum((b.get("sold_price") or b.get("price") or 0)
                       for b in bouquets
                       if b["status"] in ("sold_studio", "sold_flowwow", "sold_discount"))
        lates     = db.get_month_lates(f["id"], ym)
        total_l   = sum(lates.values())
        status    = "✅ В порядке" if kpi["kpi_passed"] else "⚠️ Есть риски"
        lines.append(
            f"{f['name']}: {len(shifts)} смен · "
            f"{sold_sum:,} ₽ · {total_l} опозданий · {status}".replace(",", " "))
    try:
        await app.bot.send_message(director["telegram_id"], "\n".join(lines))
    except Exception as e:
        log.error(e)


async def job_monthly_report(app):
    director = db.get_director()
    if not director:
        return
    prev = (now_msk().date().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    report = generate_monthly_report(prev)
    try:
        await app.bot.send_message(director["telegram_id"], report)
    except Exception as e:
        log.error(e)


# ── Запуск планировщика ───────────────────────────────────

def setup_scheduler(app):
    tz        = get_tz()
    scheduler = AsyncIOScheduler(timezone=tz)

    def wrapn(func):
        async def wrapper():
            await func(app)
        return wrapper

    def wrap(func, *args):
        async def wrapper():
            await func(app, *args)
        return wrapper

    sh, sm = parse_time(db.get_setting("shift_start_time", "10:00"))
    vh, vm = parse_time(db.get_setting("vitrina_bouquets_time", "14:00"))
    ch, cm = parse_time(db.get_setting("vitrina_compositions_time", "15:00"))
    fh, fm = parse_time(db.get_setting("flowwow_time", "13:00"))

    # Смена
    scheduler.add_job(wrapn(job_shift_prompt),    CronTrigger(hour=sh, minute=sm, timezone=tz), misfire_grace_time=600)
    scheduler.add_job(wrapn(job_shift_reminder),  "interval", minutes=5)

    # Задачи
    scheduler.add_job(wrapn(job_vitrina_bouquets),     CronTrigger(hour=vh, minute=vm, timezone=tz))
    scheduler.add_job(wrapn(job_vitrina_compositions), CronTrigger(hour=ch, minute=cm, timezone=tz))
    scheduler.add_job(wrapn(job_flowwow),              CronTrigger(hour=fh, minute=fm, timezone=tz))
    scheduler.add_job(wrapn(job_flowwow_copy),         CronTrigger(hour=11, minute=0, timezone=tz))

    # Напоминания по задачам каждые 10 минут
    scheduler.add_job(wrapn(job_all_task_reminders), "interval", minutes=5)

    # Проверки
    scheduler.add_job(wrapn(job_timeout_check),     "interval", minutes=5)
    scheduler.add_job(wrapn(job_autorating),         "interval", hours=1)
    scheduler.add_job(wrapn(job_bouquet_check_4day), CronTrigger(hour=12, minute=0, timezone=tz), misfire_grace_time=3600)
    scheduler.add_job(wrapn(job_bouquet_check_6day), CronTrigger(hour=12, minute=0, timezone=tz), misfire_grace_time=3600)
    scheduler.add_job(wrapn(job_close_shift_prompt), CronTrigger(hour=21, minute=0, timezone=tz))
    scheduler.add_job(wrapn(job_kpi_warning),        CronTrigger(hour=10, minute=0, timezone=tz))
    scheduler.add_job(wrapn(job_weekly_report),      CronTrigger(day_of_week="mon", hour=9, minute=5, timezone=tz))
    scheduler.add_job(wrapn(job_monthly_report),     CronTrigger(day=1, hour=9, minute=0, timezone=tz))

    scheduler.start()
    log.info("Scheduler started")
    return scheduler
