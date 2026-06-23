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

def parse_time(t):
    h, m = map(int, t.split(":"))
    return h, m


async def job_shift_prompt(app):
    await shift_prompt(app.bot, db.get_florists())


async def job_shift_reminder(app, reminder_type):
    """Напоминания если смена не открыта или нет чека."""
    today    = date.today().isoformat()
    florists = db.get_florists()
    director = db.get_director()

    messages = {
        "10:05": ("Не забудь прислать фото чека с терминала!",
                  "нет чека после 10:05"),
        "10:15": ("Чек ещё не получен — поторопись!",
                  "нет чека после 10:15"),
        "10:30": ("Смена не открыта — это уже опоздание!",
                  "смена не открыта после 10:30"),
        "11:00": ("Смена так и не открыта!",
                  "смена не открыта после 11:00"),
    }
    florist_msg, director_suffix = messages.get(reminder_type, ("Открой смену", "нет смены"))

    for f in florists:
        has_s = db.has_shift(f["id"], today)
        has_r = db.has_receipt(f["id"], today)

        # До 11:00 — напоминаем если нет чека (даже если смена начата)
        if reminder_type in ("10:05", "10:15") and not has_r:
            try:
                await app.bot.send_message(f["telegram_id"], f"⏰ {florist_msg}")
            except Exception as e: log.error(e)
            if director:
                try:
                    await app.bot.send_message(director["telegram_id"],
                        f"⚠️ {f['name']} — {director_suffix}")
                except Exception as e: log.error(e)

        # 10:30 и 11:00 — напоминаем если нет смены вообще
        elif reminder_type in ("10:30", "11:00") and not has_s:
            try:
                await app.bot.send_message(f["telegram_id"], f"🔴 {florist_msg}")
            except Exception as e: log.error(e)
            if director:
                try:
                    await app.bot.send_message(director["telegram_id"],
                        f"🔴 {f['name']} — {director_suffix}")
                except Exception as e: log.error(e)


async def job_vitrina_bouquets(app):
    today    = date.today().isoformat()
    workers  = db.get_working_florists(today)
    time_str = db.get_setting("vitrina_bouquets_time", "14:00")
    for f in workers:
        await send_task(app.bot, f, "vitrina_bouquets", time_str)


async def job_vitrina_compositions(app):
    today    = date.today().isoformat()
    workers  = db.get_working_florists(today)
    time_str = db.get_setting("vitrina_compositions_time", "18:00")
    for f in workers:
        await send_task(app.bot, f, "vitrina_compositions", time_str)


async def job_flowwow(app):
    today     = date.today()
    start_str = db.get_setting("flowwow_start_date", today.isoformat())
    start     = date.fromisoformat(start_str)
    if (today - start).days % 2 != 0: return
    workers  = db.get_working_florists(today.isoformat())
    time_str = db.get_setting("flowwow_time", "15:00")
    for f in workers:
        await send_task(app.bot, f, "flowwow", time_str)


async def job_timeout_check(app):
    timeout  = int(db.get_setting("timeout_minutes", "30"))
    director = db.get_director()
    conn = db.get_conn(); cur = conn.cursor()
    cur.execute("""
        SELECT t.*, u.name as florist_name
        FROM tasks t JOIN users u ON t.assigned_to=u.id
        WHERE t.status='pending'
        AND (t.date || ' ' || t.scheduled_time)::timestamp <= NOW() - INTERVAL '1 minute' * %s
    """, (timeout,))
    rows = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]
    cur.close(); conn.close()
    for t in rows:
        db.update_task(t["id"], status="missed")
        if director:
            labels = {"vitrina_bouquets": "Витрина букетов",
                      "vitrina_compositions": "Витрина композиций",
                      "flowwow": "Flowwow"}
            try:
                await app.bot.send_message(director["telegram_id"],
                    f"⚠️ Нет ответа — {labels.get(t['type'], t['type'])}\n"
                    f"Флорист: {t['florist_name']} · {t['scheduled_time']}")
            except Exception as e: log.error(e)


async def job_autorating(app):
    tasks = db.get_unrated_tasks(24)
    for t in tasks:
        db.update_task(t["id"], rating=1, status="rated", rated_at=datetime.now().isoformat())
        try:
            await app.bot.send_message(t["florist_tg"],
                f"Отчёт за {t['date']} автоматически засчитан как «Норм» "
                f"(директор не оценил за 24 часа)")
        except Exception as e: log.error(e)


async def job_bouquet_check_4day(app):
    days     = int(db.get_setting("bouquet_check_days", "4"))
    bouquets = db.get_bouquets_for_check(days, "sent_4day")
    director = db.get_director()
    import keyboards as kb
    for b in bouquets:
        try:
            caption = (f"⚠️ Букету #{b['id']} уже {days} дня!\n"
                       f"Цена: {b['price']:,} ₽ · Что с ним?".replace(",", " "))
            if b.get("photo_file_id"):
                await app.bot.send_photo(b["florist_tg"], photo=b["photo_file_id"],
                    caption=caption, reply_markup=kb.bouquet_check_kb(b["id"]))
            else:
                await app.bot.send_message(b["florist_tg"], caption,
                    reply_markup=kb.bouquet_check_kb(b["id"]))
            db.update_bouquet(b["id"], sent_4day=1)
            if director:
                await app.bot.send_message(director["telegram_id"],
                    f"📋 Напомнила {b['florist_name']} о букете #{b['id']} ({days} дней)")
        except Exception as e: log.error(e)


async def job_bouquet_check_6day(app):
    days     = int(db.get_setting("bouquet_max_days", "6"))
    bouquets = db.get_bouquets_for_check(days, "sent_6day")
    director = db.get_director()
    import keyboards as kb
    for b in bouquets:
        try:
            caption = (f"🔴 Букету #{b['id']} уже {days} дней!\n"
                       f"Цена: {b['price']:,} ₽ · Пора разобрать.".replace(",", " "))
            if b.get("photo_file_id"):
                await app.bot.send_photo(b["florist_tg"], photo=b["photo_file_id"],
                    caption=caption, reply_markup=kb.bouquet_check_kb(b["id"]))
            else:
                await app.bot.send_message(b["florist_tg"], caption,
                    reply_markup=kb.bouquet_check_kb(b["id"]))
            db.update_bouquet(b["id"], sent_6day=1)
            if director:
                await app.bot.send_message(director["telegram_id"],
                    f"🔴 Букет #{b['id']} — {b['florist_name']} — {days} дней, нужно разобрать!")
        except Exception as e: log.error(e)


async def job_kpi_warning(app):
    if date.today().day != 25: return
    from kpi import calc_kpi
    ym       = datetime.now().strftime("%Y-%m")
    florists = db.get_florists()
    for f in florists:
        kpi = calc_kpi(f["id"], ym)
        at_risk = []
        for name, data in [
            ("витрина букетов",    kpi["criteria"]["vitrina_bouquets"]),
            ("витрина композиций", kpi["criteria"]["vitrina_compositions"]),
            ("Flowwow",            kpi["criteria"]["flowwow"]),
            ("качество букетов",   kpi["criteria"]["bouquet_quality"]),
            ("опоздания",          kpi["criteria"]["lates"]),
        ]:
            if data["failed"]:
                at_risk.append(name)
        if at_risk:
            try:
                await app.bot.send_message(f["telegram_id"],
                    f"До конца месяца 5 дней!\n\n"
                    f"KPI под угрозой:\n" +
                    "\n".join(f"— {r}" for r in at_risk) +
                    "\n\nЕщё можно исправить. Пиши /moy_kpi для деталей.")
            except Exception as e: log.error(e)


async def job_weekly_report(app):
    director = db.get_director()
    if not director: return
    ym = datetime.now().strftime("%Y-%m")
    from kpi import calc_kpi
    lines = [f"Итог недели — {datetime.now().strftime('%d.%m.%Y')}\n"]
    for f in db.get_florists():
        kpi      = calc_kpi(f["id"], ym)
        shifts   = db.get_month_shifts(f["id"], ym)
        bouquets = db.get_month_bouquets(ym, f["id"])
        sold_sum = sum((b.get("sold_price") or b.get("price") or 0) for b in bouquets
                       if b["status"] in ("sold_studio","sold_flowwow","sold_discount"))
        lates    = db.get_month_lates(f["id"], ym)
        total_late = sum(lates.values())
        status   = "✅ KPI в порядке" if kpi["kpi_passed"] else "⚠️ Есть риски"
        lines.append(
            f"{f['name']}: {len(shifts)} смен · {sold_sum:,} ₽ продаж · "
            f"{total_late} опозданий · {status}".replace(",", " "))
    try:
        await app.bot.send_message(director["telegram_id"], "\n".join(lines))
    except Exception as e: log.error(e)


async def job_monthly_report(app):
    director = db.get_director()
    if not director: return
    prev = (date.today().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    report = generate_monthly_report(prev)
    try:
        await app.bot.send_message(director["telegram_id"], report)
    except Exception as e: log.error(e)


def setup_scheduler(app):
    tz        = get_tz()
    scheduler = AsyncIOScheduler(timezone=tz)

    def wrap(func, *args):
        async def wrapper():
            await func(app, *args)
        return wrapper

    def wrapn(func):
        async def wrapper():
            await func(app)
        return wrapper

    sh, sm = parse_time(db.get_setting("shift_start_time", "10:00"))
    vh, vm = parse_time(db.get_setting("vitrina_bouquets_time", "14:00"))
    ch, cm = parse_time(db.get_setting("vitrina_compositions_time", "18:00"))
    fh, fm = parse_time(db.get_setting("flowwow_time", "15:00"))

    scheduler.add_job(wrapn(job_shift_prompt),         CronTrigger(hour=sh, minute=sm, timezone=tz))
    # Напоминания по смене
    scheduler.add_job(wrap(job_shift_reminder,"10:05"), CronTrigger(hour=10, minute=5,  timezone=tz))
    scheduler.add_job(wrap(job_shift_reminder,"10:15"), CronTrigger(hour=10, minute=15, timezone=tz))
    scheduler.add_job(wrap(job_shift_reminder,"10:30"), CronTrigger(hour=10, minute=30, timezone=tz))
    scheduler.add_job(wrap(job_shift_reminder,"11:00"), CronTrigger(hour=11, minute=0,  timezone=tz))

    scheduler.add_job(wrapn(job_vitrina_bouquets),      CronTrigger(hour=vh, minute=vm, timezone=tz))
    scheduler.add_job(wrapn(job_vitrina_compositions),  CronTrigger(hour=ch, minute=cm, timezone=tz))
    scheduler.add_job(wrapn(job_flowwow),               CronTrigger(hour=fh, minute=fm, timezone=tz))
    scheduler.add_job(wrapn(job_timeout_check),         "interval", minutes=5)
    scheduler.add_job(wrapn(job_autorating),            "interval", hours=1)
    scheduler.add_job(wrapn(job_bouquet_check_4day),    CronTrigger(hour=12, minute=0, timezone=tz))
    scheduler.add_job(wrapn(job_bouquet_check_6day),    CronTrigger(hour=12, minute=0, timezone=tz))
    scheduler.add_job(wrapn(job_kpi_warning),           CronTrigger(hour=10, minute=0, timezone=tz))
    scheduler.add_job(wrapn(job_weekly_report),         CronTrigger(day_of_week="mon", hour=9, minute=5, timezone=tz))
    scheduler.add_job(wrapn(job_monthly_report),        CronTrigger(day=1, hour=9, minute=0, timezone=tz))

    scheduler.start()
    log.info("Scheduler started")
    return scheduler
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


def parse_time(t):
    h, m = map(int, t.split(":"))
    return h, m


async def job_shift_prompt(app):
    florists = db.get_florists()
    await shift_prompt(app.bot, florists)


async def job_shift_reminder(app):
    """Если к 11:00 смена не начата — уведомить директора."""
    today    = date.today().isoformat()
    florists = db.get_florists()
    director = db.get_director()
    if not director:
        return
    for f in florists:
        if not db.has_shift(f["id"], today):
            try:
                await app.bot.send_message(
                    director["telegram_id"],
                    f"Флорист {f['name']} не начала смену к 11:00"
                )
            except Exception as e:
                log.error(e)


async def job_vitrina_bouquets(app):
    today    = date.today().isoformat()
    workers  = db.get_working_florists(today)
    time_str = db.get_setting("vitrina_bouquets_time", "14:00")
    for f in workers:
        await send_task(app.bot, f, "vitrina_bouquets", time_str)


async def job_vitrina_compositions(app):
    today    = date.today().isoformat()
    workers  = db.get_working_florists(today)
    time_str = db.get_setting("vitrina_compositions_time", "18:00")
    for f in workers:
        await send_task(app.bot, f, "vitrina_compositions", time_str)


async def job_flowwow(app):
    today     = date.today()
    start_str = db.get_setting("flowwow_start_date", today.isoformat())
    start     = date.fromisoformat(start_str)
    delta     = (today - start).days
    if delta % 2 != 0:
        return
    workers  = db.get_working_florists(today.isoformat())
    time_str = db.get_setting("flowwow_time", "15:00")
    for f in workers:
        await send_task(app.bot, f, "flowwow", time_str)


async def job_timeout_check(app):
    """Задачи без ответа более 30 минут — уведомить директора."""
    timeout  = int(db.get_setting("timeout_minutes", "30"))
    director = db.get_director()
    conn = db.get_conn()
    cur  = conn.cursor()
    cur.execute("""
        SELECT t.*, u.name as florist_name
        FROM tasks t JOIN users u ON t.assigned_to=u.id
        WHERE t.status='pending'
        AND (t.date || ' ' || t.scheduled_time)::timestamp
            <= NOW() - INTERVAL '1 minute' * %s
    """, (timeout,))
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()

    for t in rows:
        db.update_task(t["id"], status="missed")
        if director:
            labels = {
                "vitrina_bouquets":     "Витрина букетов",
                "vitrina_compositions": "Витрина композиций",
                "flowwow":              "Flowwow",
            }
            try:
                await app.bot.send_message(
                    director["telegram_id"],
                    f"Нет ответа — {labels.get(t['type'], t['type'])}\n"
                    f"Флорист: {t['florist_name']}\n"
                    f"Время задачи: {t['scheduled_time']}"
                )
            except Exception as e:
                log.error(e)


async def job_autorating(app):
    """Задачи поданные флористом но не оценённые 24 часа — авто Норм."""
    tasks = db.get_unrated_tasks(24)
    for t in tasks:
        db.update_task(t["id"], rating=1, status="rated", rated_at=datetime.now().isoformat())
        try:
            await app.bot.send_message(
                t["florist_tg"],
                f"Твой отчёт за {t['date']} автоматически засчитан как «Норм» "
                f"(директор не оценил за 24 часа)"
            )
        except Exception as e:
            log.error(e)


async def job_bouquet_check_4day(app):
    days     = int(db.get_setting("bouquet_check_days", "4"))
    bouquets = db.get_bouquets_for_check(days, "sent_4day")
    director = db.get_director()
    import keyboards as kb
    for b in bouquets:
        try:
            if b.get("photo_file_id"):
                await app.bot.send_photo(
                    b["florist_tg"],
                    photo=b["photo_file_id"],
                    caption=f"Букету #{b['id']} уже {days} дня! Цена: {b['price']} руб.\nЧто с ним?",
                    reply_markup=kb.bouquet_check_kb(b["id"])
                )
            else:
                await app.bot.send_message(
                    b["florist_tg"],
                    f"Букету #{b['id']} уже {days} дня! {b['price']} руб.",
                    reply_markup=kb.bouquet_check_kb(b["id"])
                )
            db.update_bouquet(b["id"], sent_4day=1)
            if director:
                await app.bot.send_message(
                    director["telegram_id"],
                    f"Напоминание {b['florist_name']} — букет #{b['id']} ({days} дней)"
                )
        except Exception as e:
            log.error(e)


async def job_bouquet_check_6day(app):
    days     = int(db.get_setting("bouquet_max_days", "6"))
    bouquets = db.get_bouquets_for_check(days, "sent_6day")
    director = db.get_director()
    import keyboards as kb
    for b in bouquets:
        try:
            if b.get("photo_file_id"):
                await app.bot.send_photo(
                    b["florist_tg"],
                    photo=b["photo_file_id"],
                    caption=f"Букету #{b['id']} уже {days} дней! Пора разобрать.",
                    reply_markup=kb.bouquet_status_kb(b["id"])
                )
            else:
                await app.bot.send_message(
                    b["florist_tg"],
                    f"Букету #{b['id']} {days} дней — разобрать!",
                    reply_markup=kb.bouquet_status_kb(b["id"])
                )
            db.update_bouquet(b["id"], sent_6day=1)
            if director:
                await app.bot.send_message(
                    director["telegram_id"],
                    f"Букет #{b['id']} — {b['florist_name']} — {days} дней, нужно разобрать!"
                )
        except Exception as e:
            log.error(e)


async def job_kpi_warning(app):
    """25-го числа — предупреждение флористам если KPI под угрозой."""
    if date.today().day != 25:
        return
    from kpi import calc_kpi
    ym       = datetime.now().strftime("%Y-%m")
    florists = db.get_florists()
    for f in florists:
        kpi = calc_kpi(f["id"], ym)
        at_risk = [name for name, data in [
            ("витрина букетов",     kpi["criteria"]["vitrina_bouquets"]),
            ("витрина композиций",  kpi["criteria"]["vitrina_compositions"]),
            ("Flowwow",             kpi["criteria"]["flowwow"]),
            ("качество букетов",    kpi["criteria"]["bouquet_quality"]),
        ] if data["failed"]]
        if at_risk:
            try:
                await app.bot.send_message(
                    f["telegram_id"],
                    f"До конца месяца 5 дней!\n\n"
                    f"KPI под угрозой по:\n" +
                    "\n".join(f"— {r}" for r in at_risk) +
                    f"\n\nЕщё можно исправить. Напиши /moy_kpi чтобы увидеть детали."
                )
            except Exception as e:
                log.error(e)


async def job_weekly_report(app):
    """Еженедельный отчёт директору каждый понедельник в 9:05."""
    director = db.get_director()
    if not director:
        return
    ym       = datetime.now().strftime("%Y-%m")
    florists = db.get_florists()
    from kpi import calc_kpi
    lines = [f"Итог недели — {datetime.now().strftime('%d.%m.%Y')}\n"]
    for f in florists:
        kpi      = calc_kpi(f["id"], ym)
        shifts   = db.get_month_shifts(f["id"], ym)
        bouquets = db.get_month_bouquets(ym, f["id"])
        sold     = sum(b["price"] for b in bouquets
                       if b["status"] in ("sold_studio", "sold_flowwow"))
        status   = "KPI в порядке" if kpi["kpi_passed"] else "Есть риски по KPI"
        lines.append(
            f"{f['name']}: {len(shifts)} смен · "
            f"{len(bouquets)} букетов · {sold} руб. продаж · {status}"
        )
    try:
        await app.bot.send_message(director["telegram_id"], "\n".join(lines))
    except Exception as e:
        log.error(e)


async def job_monthly_report(app):
    director = db.get_director()
    if not director:
        return
    prev = (date.today().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    report = generate_monthly_report(prev)
    try:
        await app.bot.send_message(director["telegram_id"], report)
    except Exception as e:
        log.error(e)


def setup_scheduler(app):
    tz        = get_tz()
    scheduler = AsyncIOScheduler(timezone=tz)

    def wrap(func):
        async def wrapper():
            await func(app)
        return wrapper

    sh, sm = parse_time(db.get_setting("shift_start_time", "10:00"))
    vh, vm = parse_time(db.get_setting("vitrina_bouquets_time", "14:00"))
    ch, cm = parse_time(db.get_setting("vitrina_compositions_time", "18:00"))
    fh, fm = parse_time(db.get_setting("flowwow_time", "15:00"))

    scheduler.add_job(wrap(job_shift_prompt),       CronTrigger(hour=sh, minute=sm, timezone=tz))
    scheduler.add_job(wrap(job_shift_reminder),     CronTrigger(hour=11, minute=0,  timezone=tz))
    scheduler.add_job(wrap(job_vitrina_bouquets),   CronTrigger(hour=vh, minute=vm, timezone=tz))
    scheduler.add_job(wrap(job_vitrina_compositions),CronTrigger(hour=ch, minute=cm, timezone=tz))
    scheduler.add_job(wrap(job_flowwow),            CronTrigger(hour=fh, minute=fm, timezone=tz))
    scheduler.add_job(wrap(job_timeout_check),      "interval", minutes=5)
    scheduler.add_job(wrap(job_autorating),         "interval", hours=1)
    scheduler.add_job(wrap(job_bouquet_check_4day), CronTrigger(hour=12, minute=0,  timezone=tz))
    scheduler.add_job(wrap(job_bouquet_check_6day), CronTrigger(hour=12, minute=0,  timezone=tz))
    scheduler.add_job(wrap(job_kpi_warning),        CronTrigger(hour=10, minute=0,  timezone=tz))
    scheduler.add_job(wrap(job_weekly_report),      CronTrigger(day_of_week="mon", hour=9, minute=5, timezone=tz))
    scheduler.add_job(wrap(job_monthly_report),     CronTrigger(day=1,  hour=9,  minute=0,  timezone=tz))

    scheduler.start()
    log.info("Scheduler started")
    return scheduler
