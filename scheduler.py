import logging
from datetime import datetime, date, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

import database as db
from handlers import send_task, shift_prompt
from claude_ai import generate_monthly_report

log = logging.getLogger(__name__)


def get_tz():
    from config import TIMEZONE
    return pytz.timezone(TIMEZONE)


def parse_time(time_str):
    h, m = map(int, time_str.split(":"))
    return h, m


async def job_shift_prompt(app):
    florists = db.get_florists()
    await shift_prompt(app.bot, florists)


async def job_vitrina_bouquets(app):
    today = date.today().isoformat()
    workers = db.get_working_florists(today)
    time_str = db.get_setting("vitrina_bouquets_time", "14:00")
    for f in workers:
        await send_task(app.bot, f, "vitrina_bouquets", time_str)


async def job_vitrina_compositions(app):
    today = date.today().isoformat()
    workers = db.get_working_florists(today)
    time_str = db.get_setting("vitrina_compositions_time", "18:00")
    for f in workers:
        await send_task(app.bot, f, "vitrina_compositions", time_str)


async def job_flowwow(app):
    today = date.today()
    start_str = db.get_setting("flowwow_start_date", today.isoformat())
    start = date.fromisoformat(start_str)
    delta = (today - start).days
    if delta % 2 != 0:
        return  # Not a Flowwow day

    workers = db.get_working_florists(today.isoformat())
    time_str = db.get_setting("flowwow_time", "15:00")
    for f in workers:
        await send_task(app.bot, f, "flowwow", time_str)


async def job_timeout_check(app):
    """Check tasks that are overdue for 30+ minutes with no response."""
    timeout = int(db.get_setting("timeout_minutes", "30"))
    import sqlite3
    from config import DATABASE_PATH
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT t.*, u.name as florist_name, u.telegram_id as florist_tg
        FROM tasks t JOIN users u ON t.assigned_to=u.id
        WHERE t.status='pending'
        AND datetime(t.date || ' ' || t.scheduled_time) <= datetime('now', ?, 'localtime')
    """, (f"-{timeout} minutes",)).fetchall()
    conn.close()

    director = db.get_director()
    for row in rows:
        t = dict(row)
        db.update_task(t["id"], status="missed")
        if director:
            type_labels = {
                "vitrina_bouquets": "Витрина букетов",
                "vitrina_compositions": "Витрина композиций",
                "flowwow": "Flowwow",
            }
            label = type_labels.get(t["type"], t["type"])
            try:
                await app.bot.send_message(
                    director["telegram_id"],
                    f"⚠️ {label} — нет ответа!\n"
                    f"Флорист: {t['florist_name']}\n"
                    f"Время задачи: {t['scheduled_time']}\n"
                    f"Прошло: {timeout} мин."
                )
            except Exception as e:
                log.error(e)


async def job_bouquet_check_4day(app):
    """Remind about bouquets that are 4 days old."""
    days = int(db.get_setting("bouquet_check_days", "4"))
    bouquets = db.get_bouquets_for_check(days, "sent_4day")
    director = db.get_director()

    for b in bouquets:
        try:
            # Send to florist
            await app.bot.send_photo(
                b["florist_tg"],
                photo=b["photo_file_id"],
                caption=f"⚠️ Букету #{b['id']} уже {days} дня!\nЦена: {b['price']:,} ₽\nЧто с ним?".replace(",", " "),
                reply_markup=__import__("keyboards").bouquet_check_kb(b["id"])
            )
            db.update_bouquet(b["id"], sent_4day=1)

            if director:
                await app.bot.send_message(
                    director["telegram_id"],
                    f"📋 Напоминание флористу {b['florist_name']} — букет #{b['id']} ({days} дней)"
                )
        except Exception as e:
            log.error(e)


async def job_bouquet_check_6day(app):
    """Force disassemble notification for 6-day bouquets."""
    days = int(db.get_setting("bouquet_max_days", "6"))
    bouquets = db.get_bouquets_for_check(days, "sent_6day")
    director = db.get_director()

    for b in bouquets:
        try:
            await app.bot.send_photo(
                b["florist_tg"],
                photo=b["photo_file_id"],
                caption=f"🗑 Букету #{b['id']} уже {days} дней!\nПора разобрать.",
                reply_markup=__import__("keyboards").bouquet_status_kb(b["id"])
            )
            db.update_bouquet(b["id"], sent_6day=1)

            if director:
                await app.bot.send_message(
                    director["telegram_id"],
                    f"🗑 Букет #{b['id']} — {b['florist_name']} — {days} дней, требует разбора!"
                )
        except Exception as e:
            log.error(e)


async def job_monthly_report(app):
    """Send monthly report on the 1st of each month."""
    director = db.get_director()
    if not director:
        return
    prev_month = (date.today().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    report = generate_monthly_report(prev_month)
    try:
        await app.bot.send_message(director["telegram_id"], report)
    except Exception as e:
        log.error(e)


def setup_scheduler(app):
    tz = get_tz()
    scheduler = AsyncIOScheduler(timezone=tz)

    def make_job(func):
        async def wrapper():
            await func(app)
        return wrapper

    def get_hm(key, default):
        t = db.get_setting(key, default)
        return parse_time(t)

    # Shift start 10:00
    sh, sm = parse_time(db.get_setting("shift_start_time", "10:00"))
    scheduler.add_job(make_job(job_shift_prompt), CronTrigger(hour=sh, minute=sm, timezone=tz))

    # Vitrina bouquets 14:00
    vh, vm = parse_time(db.get_setting("vitrina_bouquets_time", "14:00"))
    scheduler.add_job(make_job(job_vitrina_bouquets), CronTrigger(hour=vh, minute=vm, timezone=tz))

    # Vitrina compositions 18:00
    ch, cm = parse_time(db.get_setting("vitrina_compositions_time", "18:00"))
    scheduler.add_job(make_job(job_vitrina_compositions), CronTrigger(hour=ch, minute=cm, timezone=tz))

    # Flowwow 15:00
    fh, fm = parse_time(db.get_setting("flowwow_time", "15:00"))
    scheduler.add_job(make_job(job_flowwow), CronTrigger(hour=fh, minute=fm, timezone=tz))

    # Timeout check every 5 minutes
    scheduler.add_job(make_job(job_timeout_check), "interval", minutes=5)

    # Bouquet checks at 12:00
    scheduler.add_job(make_job(job_bouquet_check_4day), CronTrigger(hour=12, minute=0, timezone=tz))
    scheduler.add_job(make_job(job_bouquet_check_6day), CronTrigger(hour=12, minute=0, timezone=tz))

    # Monthly report on 1st at 09:00
    scheduler.add_job(make_job(job_monthly_report), CronTrigger(day=1, hour=9, minute=0, timezone=tz))

    scheduler.start()
    log.info("Scheduler started")
    return scheduler
