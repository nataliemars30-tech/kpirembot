from datetime import date, datetime, timedelta
import pytz
from telegram.ext import Application
from config import (
    DIRECTOR_ID, TASK_VITRINA_BOUQUETS,
    TASK_VITRINA_COMPOSITIONS, TASK_FLOWWOW, TIMEZONE
)
from database import (
    get_florists_on_shift, get_all_florists, create_task,
    get_bouquets_needing_check, get_bouquets_overdue,
    update_bouquet, get_setting
)
from handlers import send_shift_start_prompt, send_task_to_florist, bouquet_check_keyboard


def parse_time(time_str: str):
    h, m = map(int, time_str.split(":"))
    return h, m


def setup_scheduler(app: Application):
    tz = pytz.timezone(TIMEZONE)
    jq = app.job_queue

    # Shift start — every day
    jq.run_daily(job_shift_start, time=datetime.strptime("10:00", "%H:%M").time().replace(tzinfo=tz), name="shift_start")

    # Vitrina bouquets — every day 14:00 (can be changed via settings)
    jq.run_daily(job_vitrina_bouquets, time=datetime.strptime("14:00", "%H:%M").time().replace(tzinfo=tz), name="vitrina_bouquets")

    # Vitrina compositions — every day 18:00
    jq.run_daily(job_vitrina_compositions, time=datetime.strptime("18:00", "%H:%M").time().replace(tzinfo=tz), name="vitrina_compositions")

    # Flowwow — every day 15:00, but only runs every 2 days
    jq.run_daily(job_flowwow, time=datetime.strptime("15:00", "%H:%M").time().replace(tzinfo=tz), name="flowwow")

    # Check overdue tasks — every 5 minutes
    jq.run_repeating(job_check_overdue, interval=300, first=60, name="overdue_check")

    # Bouquet timers — check hourly
    jq.run_repeating(job_bouquet_timers, interval=3600, first=120, name="bouquet_timers")

    # Weekly Claude check — every Monday 09:05
    jq.run_daily(job_weekly_alert, time=datetime.strptime("09:05", "%H:%M").time().replace(tzinfo=tz), days=(0,), name="weekly_alert")

    # Monthly report — 1st of month at 09:00
    jq.run_daily(job_monthly_report, time=datetime.strptime("09:00", "%H:%M").time().replace(tzinfo=tz), name="monthly_report")


async def job_shift_start(ctx):
    time_str = await get_setting("shift_start_time")
    if time_str != "10:00":
        pass  # Time already handled by job scheduling

    florists = await get_all_florists()
    for florist in florists:
        await send_shift_start_prompt(ctx.bot, florist)


async def job_vitrina_bouquets(ctx):
    today = date.today().isoformat()
    florists = await get_florists_on_shift(today)

    if not florists:
        florists = await get_all_florists()

    for florist in florists:
        task_id = await create_task(florist["id"], TASK_VITRINA_BOUQUETS, today)
        await send_task_to_florist(ctx.bot, florist, TASK_VITRINA_BOUQUETS, task_id)


async def job_vitrina_compositions(ctx):
    today = date.today().isoformat()
    florists = await get_florists_on_shift(today)

    if not florists:
        florists = await get_all_florists()

    for florist in florists:
        task_id = await create_task(florist["id"], TASK_VITRINA_COMPOSITIONS, today)
        await send_task_to_florist(ctx.bot, florist, TASK_VITRINA_COMPOSITIONS, task_id)


async def job_flowwow(ctx):
    from database import get_setting, DB_PATH
    import aiosqlite

    # Check if today is a Flowwow day
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT next_date FROM flowwow_schedule ORDER BY id DESC LIMIT 1") as cur:
            row = await cur.fetchone()

    today = date.today().isoformat()
    interval = await get_setting("flowwow_interval_days")

    if not row:
        # First time — set today as Flowwow day
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT INTO flowwow_schedule (next_date) VALUES (?)", (today,))
            await db.commit()
        is_flowwow_day = True
    else:
        next_date = row[0]
        is_flowwow_day = (today >= next_date)
        if is_flowwow_day:
            new_next = (date.today() + timedelta(days=interval)).isoformat()
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("INSERT INTO flowwow_schedule (next_date) VALUES (?)", (new_next,))
                await db.commit()

    if not is_flowwow_day:
        return

    ctx.bot_data["flowwow_today"] = True

    florists = await get_florists_on_shift(today)
    if not florists:
        florists = await get_all_florists()

    for florist in florists:
        task_id = await create_task(florist["id"], TASK_FLOWWOW, today)
        await send_task_to_florist(ctx.bot, florist, TASK_FLOWWOW, task_id)


async def job_check_overdue(ctx):
    from handlers import check_overdue_tasks
    await check_overdue_tasks(ctx)


async def job_bouquet_timers(ctx):
    # Check bouquets needing 4-day check
    need_check = await get_bouquets_needing_check()
    for b in need_check:
        await update_bouquet(b["id"], reminder_4_sent=1)
        days = await get_setting("bouquet_check_days")
        await ctx.bot.send_photo(
            chat_id=b["florist_tg_id"],
            photo=b["photo_file_id"],
            caption=(
                f"⚠️ Букету #{b['id']} уже {days} дня!\n"
                f"Цена: {b['price']:,} ₽\n\n"
                f"Что с ним?"
            ),
            reply_markup=bouquet_check_keyboard(b["id"])
        )
        await ctx.bot.send_message(
            chat_id=DIRECTOR_ID,
            text=f"📋 Букет #{b['id']} · {b['florist_name']} · {b['price']:,} ₽ — {days} дня, ждёт проверки"
        )

    # Check bouquets overdue (6+ days)
    overdue = await get_bouquets_overdue()
    for b in overdue:
        await update_bouquet(b["id"], reminder_6_sent=1)
        days = await get_setting("bouquet_disassemble_days")
        await ctx.bot.send_photo(
            chat_id=b["florist_tg_id"],
            photo=b["photo_file_id"],
            caption=(
                f"🚨 Букет #{b['id']} — уже {days} дней!\n"
                f"Цена: {b['price']:,} ₽\n\n"
                f"Пора разобрать или отметить как проданный:"
            ),
            reply_markup=bouquet_check_keyboard(b["id"])
        )
        await ctx.bot.send_message(
            chat_id=DIRECTOR_ID,
            text=f"🚨 Букет #{b['id']} · {b['florist_name']} · {b['price']:,} ₽ — {days} дней, не разобран!"
        )


async def job_weekly_alert(ctx):
    if date.today().weekday() != 0:  # Monday only
        return
    from claude_ai import generate_weekly_alert
    alert = await generate_weekly_alert()
    if alert:
        await ctx.bot.send_message(
            chat_id=DIRECTOR_ID,
            text=f"✦ Еженедельный анализ:\n\n{alert}"
        )


async def job_monthly_report(ctx):
    if date.today().day != 1:  # 1st of month only
        return

    import calendar
    today = date.today()
    first_day = today.replace(day=1)
    last_month = first_day - timedelta(days=1)
    month = last_month.strftime("%Y-%m")

    from claude_ai import generate_monthly_report
    report = await generate_monthly_report(month)

    month_name = last_month.strftime("%B %Y")
    await ctx.bot.send_message(
        chat_id=DIRECTOR_ID,
        text=f"📅 Итоговый отчёт за {month_name}\n\n{report}"
    )
