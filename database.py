import os
import pg8000.dbapi
import urllib.parse
from datetime import datetime

DATABASE_URL = os.environ.get("DATABASE_URL", "")


def _parse(url):
    p = urllib.parse.urlparse(url)
    return dict(
        host=p.hostname, user=p.username, password=p.password,
        database=p.path.lstrip("/"), port=p.port or 5432, ssl_context=True,
    )

def get_conn():
    conn = pg8000.dbapi.connect(**_parse(DATABASE_URL))
    conn.autocommit = False
    return conn

def _all(cur):
    if not cur.description: return []
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]

def _one(cur):
    if not cur.description: return None
    cols = [d[0] for d in cur.description]
    row = cur.fetchone()
    return dict(zip(cols, row)) if row else None


def init_db():
    conn = get_conn(); cur = conn.cursor()

    cur.execute("""CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        telegram_id BIGINT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'florist',
        active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        schedule_start_date TEXT
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS shifts (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        date TEXT NOT NULL,
        started_at TEXT DEFAULT CURRENT_TIMESTAMP,
        open_receipt_photo TEXT,
        receipt_time TEXT,
        late_type TEXT,
        close_receipt_photo TEXT,
        fridge_photo1 TEXT,
        fridge_photo2 TEXT,
        closed_at TEXT,
        UNIQUE(user_id, date)
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS tasks (
        id SERIAL PRIMARY KEY,
        type TEXT NOT NULL,
        assigned_to INTEGER REFERENCES users(id),
        date TEXT NOT NULL,
        scheduled_time TEXT NOT NULL,
        status TEXT DEFAULT 'pending',
        photo_file_id TEXT,
        submitted_at TEXT,
        in_hour_at TEXT,
        no_reason TEXT,
        rating INTEGER,
        rated_at TEXT,
        florist_msg_id BIGINT,
        director_msg_id BIGINT
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS bouquets (
        id SERIAL PRIMARY KEY,
        florist_id INTEGER NOT NULL REFERENCES users(id),
        photo_file_id TEXT,
        cost INTEGER NOT NULL DEFAULT 0,
        price INTEGER NOT NULL,
        status TEXT DEFAULT 'in_vitrina',
        director_rating INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        checked_at TEXT,
        sold_at TEXT,
        sale_channel TEXT,
        sold_price INTEGER,
        disassembled_at TEXT,
        sent_4day INTEGER DEFAULT 0,
        sent_6day INTEGER DEFAULT 0
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )""")

    # Миграция — добавляем колонки в существующие таблицы
    migrations = [
        "ALTER TABLE shifts ADD COLUMN IF NOT EXISTS open_receipt_photo TEXT",
        "ALTER TABLE shifts ADD COLUMN IF NOT EXISTS receipt_time TEXT",
        "ALTER TABLE shifts ADD COLUMN IF NOT EXISTS late_type TEXT",
        "ALTER TABLE shifts ADD COLUMN IF NOT EXISTS close_receipt_photo TEXT",
        "ALTER TABLE shifts ADD COLUMN IF NOT EXISTS fridge_photo1 TEXT",
        "ALTER TABLE shifts ADD COLUMN IF NOT EXISTS fridge_photo2 TEXT",
        "ALTER TABLE shifts ADD COLUMN IF NOT EXISTS closed_at TEXT",
        "ALTER TABLE bouquets ADD COLUMN IF NOT EXISTS cost INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS schedule_start_date TEXT",
        "ALTER TABLE bouquets ADD COLUMN IF NOT EXISTS sold_price INTEGER",
    ]
    for sql in migrations:
        try:
            cur.execute(sql)
        except Exception:
            pass

    defaults = {
        "vitrina_bouquets_time":     "14:00",
        "min_vitrina_bouquets":       "6",
        "vitrina_compositions_time": "18:00",
        "flowwow_time":              "15:00",
        "shift_start_time":          "10:00",
        "timeout_minutes":           "30",
        "bouquet_check_days":        "4",
        "bouquet_max_days":          "6",
        "flowwow_start_date":        datetime.now().strftime("%Y-%m-%d"),
        "kpi_vitrina_max_skips":     "4",
        "kpi_vitrina_max_norm":      "7",
        "kpi_flowwow_max_skips":     "1",
        "kpi_flowwow_max_norm":      "4",
        "kpi_bouquet_max_bad":       "2",
        "overhead_pct":              "25",
        "kpi_late_light_max":        "4",
        "kpi_late_medium_max":       "3",
        "kpi_late_heavy_max":        "2",
    }
    for k, v in defaults.items():
        cur.execute(
            "INSERT INTO settings (key,value) VALUES (%s,%s) ON CONFLICT (key) DO NOTHING",
            (k, v))

    conn.commit(); cur.close(); conn.close()


def get_setting(key, default=None):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key=%s", (key,))
    row = _one(cur); cur.close(); conn.close()
    return row["value"] if row else default

def set_setting(key, value):
    conn = get_conn(); cur = conn.cursor()
    cur.execute(
        "INSERT INTO settings (key,value) VALUES (%s,%s) ON CONFLICT (key) DO UPDATE SET value=%s",
        (key, str(value), str(value)))
    conn.commit(); cur.close(); conn.close()

def get_all_settings():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT key, value FROM settings")
    rows = _all(cur); cur.close(); conn.close()
    return {r["key"]: r["value"] for r in rows}


# ── Users ────────────────────────────────────────────────

def get_user(telegram_id):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE telegram_id=%s", (telegram_id,))
    row = _one(cur); cur.close(); conn.close()
    return row

def get_user_by_id(user_id):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id=%s", (user_id,))
    row = _one(cur); cur.close(); conn.close()
    return row

def create_user(telegram_id, name, role="florist"):
    conn = get_conn(); cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (telegram_id,name,role) VALUES (%s,%s,%s) ON CONFLICT (telegram_id) DO NOTHING",
        (telegram_id, name, role))
    conn.commit(); cur.close(); conn.close()

def get_director():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE role='director' LIMIT 1")
    row = _one(cur); cur.close(); conn.close()
    return row

def get_florists(active_only=True):
    conn = get_conn(); cur = conn.cursor()
    q = "SELECT * FROM users WHERE role='florist'"
    if active_only: q += " AND active=1"
    cur.execute(q)
    rows = _all(cur); cur.close(); conn.close()
    return rows


# ── Shifts ───────────────────────────────────────────────

def start_shift(user_id, date):
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO shifts (user_id,date) VALUES (%s,%s) ON CONFLICT (user_id,date) DO NOTHING",
            (user_id, date))
        changed = cur.rowcount > 0
        conn.commit()
    except Exception:
        changed = False
    cur.close(); conn.close()
    return changed

def update_shift(user_id, date, **kwargs):
    conn = get_conn(); cur = conn.cursor()
    sets = ", ".join(f"{k}=%s" for k in kwargs)
    vals = list(kwargs.values()) + [user_id, date]
    cur.execute(f"UPDATE shifts SET {sets} WHERE user_id=%s AND date=%s", vals)
    conn.commit(); cur.close(); conn.close()

def update_user(user_id, **kwargs):
    if not kwargs: return
    conn = get_conn(); cur = conn.cursor()
    sets = ", ".join(f"{k}=%s" for k in kwargs)
    cur.execute(f"UPDATE users SET {sets} WHERE id=%s",
                (*kwargs.values(), user_id))
    conn.commit(); cur.close(); conn.close()

def has_shift(user_id, date):

def has_shift(user_id, date):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT id FROM shifts WHERE user_id=%s AND date=%s", (user_id, date))
    row = _one(cur); cur.close(); conn.close()
    return row is not None

def has_receipt(user_id, date):
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("SELECT open_receipt_photo FROM shifts WHERE user_id=%s AND date=%s", (user_id, date))
        row = _one(cur)
        result = row is not None and row.get("open_receipt_photo") is not None
    except Exception:
        result = False
    cur.close(); conn.close()
    return result

def is_scheduled_today(florist, date_str):
    """Проверяет рабочий ли день у флориста по графику 2/2."""
    start = florist.get("schedule_start_date")
    if not start:
        return True  # если график не задан — считаем рабочим всегда
    from datetime import date as _date
    d0 = _date.fromisoformat(start)
    d1 = _date.fromisoformat(date_str)
    diff = (d1 - d0).days
    return diff >= 0 and diff % 2 == 0


def get_scheduled_florists(date_str):
    """Все флористы у кого сегодня рабочий день по графику."""
    all_florists = get_florists()
    return [f for f in all_florists if is_scheduled_today(f, date_str)]
def get_working_florists(date):
    conn = get_conn(); cur = conn.cursor()
    cur.execute(
        "SELECT u.* FROM users u JOIN shifts s ON u.id=s.user_id "
        "WHERE s.date=%s AND u.role='florist' AND u.active=1", (date,))
    rows = _all(cur); cur.close(); conn.close()
    return rows

def get_month_shifts(user_id, year_month):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT * FROM shifts WHERE user_id=%s AND date LIKE %s",
                (user_id, f"{year_month}%"))
    rows = _all(cur); cur.close(); conn.close()
    return rows

def get_month_lates(user_id, year_month):
    conn = get_conn(); cur = conn.cursor()
    cur.execute(
        "SELECT late_type, COUNT(*) as cnt FROM shifts "
        "WHERE user_id=%s AND date LIKE %s AND late_type IS NOT NULL "
        "GROUP BY late_type",
        (user_id, f"{year_month}%"))
    rows = _all(cur); cur.close(); conn.close()
    result = {"light": 0, "medium": 0, "heavy": 0, "no_show": 0}
    for r in rows:
        if r["late_type"] in result:
            result[r["late_type"]] = r["cnt"]
    return result


# ── Tasks ────────────────────────────────────────────────

def create_task(task_type, assigned_to, date, scheduled_time):
    conn = get_conn(); cur = conn.cursor()
    cur.execute(
        "INSERT INTO tasks (type,assigned_to,date,scheduled_time) VALUES (%s,%s,%s,%s) RETURNING id",
        (task_type, assigned_to, date, scheduled_time))
    tid = _one(cur)["id"]
    conn.commit(); cur.close(); conn.close()
    return tid

def get_task(task_id):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT * FROM tasks WHERE id=%s", (task_id,))
    row = _one(cur); cur.close(); conn.close()
    return row

def update_task(task_id, **kwargs):
    conn = get_conn(); cur = conn.cursor()
    sets = ", ".join(f"{k}=%s" for k in kwargs)
    vals = list(kwargs.values()) + [task_id]
    cur.execute(f"UPDATE tasks SET {sets} WHERE id=%s", vals)
    conn.commit(); cur.close(); conn.close()

def get_incomplete_task(user_id, task_type, date):
    """Любая незавершённая задача — pending, in_hour, или missed (для напоминаний)."""
    conn = get_conn(); cur = conn.cursor()
    cur.execute(
        "SELECT * FROM tasks WHERE assigned_to=%s AND type=%s AND date=%s "
        "AND status IN ('pending','in_hour','missed','waiting_photo')",
        (user_id, task_type, date))
    row = _one(cur); cur.close(); conn.close()
    return row


def get_pending_task(user_id, task_type, date):
    conn = get_conn(); cur = conn.cursor()
    cur.execute(
        "SELECT * FROM tasks WHERE assigned_to=%s AND type=%s AND date=%s "
        "AND status IN ('pending')",
        (user_id, task_type, date))
    row = _one(cur); cur.close(); conn.close()
    return row

def get_month_tasks(year_month, florist_id=None):
    conn = get_conn(); cur = conn.cursor()
    q = ("SELECT t.*, u.name as florist_name FROM tasks t "
         "JOIN users u ON t.assigned_to=u.id "
         "WHERE t.date LIKE %s AND u.role='florist'")
    params = [f"{year_month}%"]
    if florist_id:
        q += " AND t.assigned_to=%s"
        params.append(florist_id)
    cur.execute(q, params)
    rows = _all(cur); cur.close(); conn.close()
    return rows

def get_unrated_tasks(hours=24):
    conn = get_conn(); cur = conn.cursor()
    cur.execute(
        "SELECT t.*, u.telegram_id as florist_tg, u.name as florist_name "
        "FROM tasks t JOIN users u ON t.assigned_to=u.id "
        "WHERE t.status='submitted' AND t.submitted_at IS NOT NULL "
        "AND t.submitted_at::timestamp < NOW() - INTERVAL '24 hours'")
    rows = _all(cur); cur.close(); conn.close()
    return rows


# ── Bouquets ─────────────────────────────────────────────

def create_bouquet(florist_id, photo_file_id, cost, price):
    conn = get_conn(); cur = conn.cursor()
    cur.execute(
        "INSERT INTO bouquets (florist_id,photo_file_id,cost,price) VALUES (%s,%s,%s,%s) RETURNING id",
        (florist_id, photo_file_id, cost, price))
    bid = _one(cur)["id"]
    conn.commit(); cur.close(); conn.close()
    return bid

def get_bouquet(bouquet_id):
    conn = get_conn(); cur = conn.cursor()
    cur.execute(
        "SELECT b.*, u.name as florist_name FROM bouquets b "
        "JOIN users u ON b.florist_id=u.id WHERE b.id=%s", (bouquet_id,))
    row = _one(cur); cur.close(); conn.close()
    return row

def update_bouquet(bouquet_id, **kwargs):
    conn = get_conn(); cur = conn.cursor()
    sets = ", ".join(f"{k}=%s" for k in kwargs)
    vals = list(kwargs.values()) + [bouquet_id]
    cur.execute(f"UPDATE bouquets SET {sets} WHERE id=%s", vals)
    conn.commit(); cur.close(); conn.close()

def count_active_bouquets():
    """Считает количество активных букетов на витрине."""
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM bouquets WHERE status='in_vitrina'")
    row = cur.fetchone()
    cur.close(); conn.close()
    return row[0] if row else 0


def get_shift(user_id, date):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT * FROM shifts WHERE user_id=%s AND date=%s", (user_id, date))
    row = cur.fetchone()
    if not row:
        cur.close(); conn.close()
        return {}
    cols = [d[0] for d in cur.description]
    result = dict(zip(cols, row))
    cur.close(); conn.close()
    return result
def has_shift_closed(user_id, date):
    """Проверяет закрыта ли смена."""
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("SELECT closed_at FROM shifts WHERE user_id=%s AND date=%s", (user_id, date))
        row = cur.fetchone()
        result = row is not None and row[0] is not None
    except Exception:
        result = False
    cur.close(); conn.close()
    return result


def get_active_bouquets(florist_id=None):
    conn = get_conn(); cur = conn.cursor()
    q = ("SELECT b.*, u.name as florist_name FROM bouquets b "
         "JOIN users u ON b.florist_id=u.id WHERE b.status='in_vitrina'")
    params = []
    if florist_id:
        q += " AND b.florist_id=%s"; params.append(florist_id)
    q += " ORDER BY b.created_at"
    cur.execute(q, params)
    rows = _all(cur); cur.close(); conn.close()
    return rows

def get_bouquets_for_check(days, field):
    conn = get_conn(); cur = conn.cursor()
    cur.execute(
        f"SELECT b.*, u.name as florist_name, u.telegram_id as florist_tg "
        f"FROM bouquets b JOIN users u ON b.florist_id=u.id "
        f"WHERE b.status='in_vitrina' "
        f"AND b.created_at::date = CURRENT_DATE - {days} "
        f"AND b.{field}=0")
    rows = _all(cur); cur.close(); conn.close()
    return rows

def get_month_bouquets(year_month, florist_id=None):
    conn = get_conn(); cur = conn.cursor()
    q = ("SELECT b.*, u.name as florist_name FROM bouquets b "
         "JOIN users u ON b.florist_id=u.id WHERE b.created_at LIKE %s")
    params = [f"{year_month}%"]
    if florist_id:
        q += " AND b.florist_id=%s"; params.append(florist_id)
    cur.execute(q, params)
    rows = _all(cur); cur.close(); conn.close()
    return rows
